# backend/app/main.py

import datetime
import logging
# import time # Not strictly needed for this specific metric, but can be useful for other diagnostics
from dateutil import parser # For robust ISO 8601 parsing

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uvicorn # For local running if needed

# --- Pydantic Models ---
class Waypoint(BaseModel):
    lat: float
    lon: float

class SensorData(BaseModel):
    gps_lat: float
    gps_lon: float
    altitude: float
    velocity: float
    accel_x: float
    accel_y: float
    yaw_rate: float

class VehicleControls(BaseModel):
    steering: float
    throttle: float

class CarData(BaseModel):
    predicted_waypoints: Optional[List[Waypoint]] = None
    sensor_data: SensorData
    inference_mode: str
    vehicle_controls: VehicleControls
    image1_base64: Optional[str] = None
    unique_id_image1: Optional[str] = None # e.g., "frame_0.jpg_timestampms"
    image2_base64: Optional[str] = None
    unique_id_image2: Optional[str] = None # e.g., "frame_1.jpg_timestampms"
    energy_used_wh: Optional[float] = None
    timestamp_car_sent_utc: str # Car MUST send this accurately (ISO 8601 with 'Z')
    
    # Fields to be added by the server:
    timestamp_server_received_utc: Optional[str] = None
    data_transit_time_to_server_ms: Optional[float] = None 
# --- End Pydantic Models ---

app = FastAPI(
    title="Car Data Backend",
    description="Calculates data transit time from car and broadcasts updates.",
    version="1.3.0" 
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

latest_car_data_store: Optional[CarData] = None

class ConnectionManager:
    def __init__(self, manager_name: str = "default"):
        self.active_connections: List[WebSocket] = []
        self.manager_name = manager_name

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"[{self.manager_name}] WS client connected: {websocket.client.host}:{websocket.client.port}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logging.info(f"[{self.manager_name}] WS client disconnected: {websocket.client.host}:{websocket.client.port}")

    async def broadcast_json_object(self, data: dict):
        if not self.active_connections: return
        disconnected_clients: List[WebSocket] = []
        for connection in list(self.active_connections): 
            try:
                await connection.send_json(data)
            except (WebSocketDisconnect, RuntimeError) as e:
                disconnected_clients.append(connection)
                logging.warning(f"[{self.manager_name}] Client {connection.client.host}:{connection.client.port} disconnected or error during broadcast: {type(e).__name__}")
            except Exception as e:
                logging.error(f"[{self.manager_name}] Error sending to {connection.client.host}:{connection.client.port}: {e}")
        for client in disconnected_clients:
            if client in self.active_connections: self.disconnect(client)

car_connection_manager = ConnectionManager(manager_name="CarClients")
ui_connection_manager = ConnectionManager(manager_name="UIClients")

@app.websocket("/ws/car_data")
async def websocket_car_data_endpoint(websocket: WebSocket):
    await car_connection_manager.connect(websocket)
    global latest_car_data_store
    try:
        while True:
            server_receive_time_obj = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
            data_json = await websocket.receive_json()

            try:
                car_data_received = CarData(**data_json) 
                car_data_received.timestamp_server_received_utc = server_receive_time_obj.isoformat().replace("+00:00", "Z")

                try:
                    car_sent_time_obj = parser.isoparse(car_data_received.timestamp_car_sent_utc)
                    if car_sent_time_obj.tzinfo is None or car_sent_time_obj.tzinfo.utcoffset(car_sent_time_obj) is None:
                        logging.warning(f"Car timestamp '{car_data_received.timestamp_car_sent_utc}' was naive. Assuming UTC.")
                        car_sent_time_obj = car_sent_time_obj.replace(tzinfo=datetime.timezone.utc)
                    
                    latency_delta = server_receive_time_obj - car_sent_time_obj
                    transit_time_ms = round(latency_delta.total_seconds() * 1000.0, 2)
                    car_data_received.data_transit_time_to_server_ms = transit_time_ms
                    
                    if transit_time_ms < -10: # Allow small negative tolerance
                        logging.warning(f"Negative transit time ({transit_time_ms} ms). Clock skew suspected.")
                    elif transit_time_ms > 10000: 
                         logging.warning(f"High transit time ({transit_time_ms} ms). Possible clock skew/network issue.")
                except Exception as time_parse_error:
                    logging.error(f"Error parsing car timestamp or calculating transit: {time_parse_error}. TS was: '{car_data_received.timestamp_car_sent_utc}'")
                    car_data_received.data_transit_time_to_server_ms = None
                
                latest_car_data_store = car_data_received
                logging.info(f"Data stored. Transit: {car_data_received.data_transit_time_to_server_ms} ms.")

                if latest_car_data_store:
                    await ui_connection_manager.broadcast_json_object(latest_car_data_store.model_dump())

                await websocket.send_json({
                    "status": "received",
                    "message_processed_at_utc": car_data_received.timestamp_server_received_utc
                })
            except Exception as e:
                logging.error(f"Error processing car data: {e} - Raw: {data_json}")
                await websocket.send_json({"status": "error", "message": str(e)})
    except WebSocketDisconnect:
        logging.info(f"Car WS disconnected: {websocket.client.host}:{websocket.client.port}")
    except Exception as e:
        logging.error(f"Car WS error: {e} for {websocket.client.host}:{websocket.client.port}")
        try: await websocket.close(code=1011)
        except RuntimeError: pass
    finally:
        car_connection_manager.disconnect(websocket)

@app.websocket("/ws/ui_updates")
async def websocket_ui_endpoint(websocket: WebSocket):
    # ... (This endpoint remains the same as in the previous full backend example) ...
    await ui_connection_manager.connect(websocket)
    try:
        if latest_car_data_store:
            try: await websocket.send_json(latest_car_data_store.model_dump())
            except Exception as e: logging.error(f"Error sending initial data to UI {websocket.client.host}:{websocket.client.port}: {e}")
        while True: await websocket.receive_text() # Keep alive, detect close
    except WebSocketDisconnect: logging.info(f"UI WS disconnected: {websocket.client.host}:{websocket.client.port}")
    except Exception as e: logging.error(f"UI WS error: {e} for {websocket.client.host}:{websocket.client.port}")
    finally: ui_connection_manager.disconnect(websocket)


@app.get("/api/latest_car_data", response_model=Optional[CarData])
async def get_latest_car_data():
    # ... (This endpoint remains the same) ...
    if latest_car_data_store: return latest_car_data_store
    return None

@app.get("/")
async def read_root():
    # ... (This endpoint remains the same, update descriptions if needed) ...
    return {
        "message": "Car Data Backend is running.",
        "car_websocket_endpoint": "/ws/car_data",
        "ui_websocket_endpoint": "/ws/ui_updates",
        "latest_data_http_endpoint": "/api/latest_car_data"
    }


@app.get("/debug/time_check") # Changed endpoint name slightly for clarity
async def get_server_time_check():
    return {
        "description": "Current time as seen by the backend server application",
        "server_utc_timestamp_iso": datetime.datetime.utcnow().isoformat() + "Z",
        "server_datetime_object_utc": str(datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)),
        "server_datetime_object_local": str(datetime.datetime.now().astimezone()), # Includes local TZ info
    }

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]
)