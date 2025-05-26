# backend/app/main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import datetime
import logging
import uvicorn
import json # Not strictly needed if using .model_dump() with send_json

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
    server_comm_time_ms: Optional[float] = None
    server_response_time_ms: Optional[float] = None
    predicted_waypoints: Optional[List[Waypoint]] = None
    sensor_data: SensorData
    inference_mode: str
    vehicle_controls: VehicleControls
    image1_base64: Optional[str] = None # For main camera image
    image2_base64: Optional[str] = None # For second/aux camera image
    energy_used_wh: Optional[float] = None
    timestamp_car_sent_utc: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    timestamp_server_received_utc: Optional[str] = None
# --- End Pydantic Models ---

app = FastAPI(
    title="Car Data Backend",
    description="Receives car data, provides it via HTTP GET, and broadcasts live updates via WebSockets to UI clients.",
    version="1.2.0" # Incremented version for clarity
)

# --- CORS Middleware ---
# In production, restrict origins to your actual frontend URL(s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory Data Store ---
latest_car_data_store: Optional[CarData] = None

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self, manager_name: str = "default"):
        self.active_connections: List[WebSocket] = []
        self.manager_name = manager_name # For logging

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"[{self.manager_name}] WebSocket client connected: {websocket.client.host}:{websocket.client.port}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logging.info(f"[{self.manager_name}] WebSocket client disconnected: {websocket.client.host}:{websocket.client.port}")

    async def broadcast_json_object(self, data: dict):
        if not self.active_connections:
            # logging.debug(f"[{self.manager_name}] No active clients to broadcast to.")
            return
        
        disconnected_clients: List[WebSocket] = []
        # Iterate over a copy of the list in case of modifications during iteration
        for connection in list(self.active_connections): 
            try:
                await connection.send_json(data)
            except (WebSocketDisconnect, RuntimeError) as e:
                disconnected_clients.append(connection)
                logging.warning(f"[{self.manager_name}] Client {connection.client.host}:{connection.client.port} disconnected or runtime error during broadcast: {type(e).__name__}")
            except Exception as e:
                logging.error(f"[{self.manager_name}] Unexpected error sending to {connection.client.host}:{connection.client.port}: {e}")
        
        for client in disconnected_clients:
            if client in self.active_connections : # Check again before removing
                 self.disconnect(client) # Ensure proper cleanup via manager's disconnect method

# --- Managers for different client types ---
car_connection_manager = ConnectionManager(manager_name="CarClients")
ui_connection_manager = ConnectionManager(manager_name="UIClients")

# --- WebSocket Endpoint for Car Data ---
@app.websocket("/ws/car_data")
async def websocket_car_data_endpoint(websocket: WebSocket):
    await car_connection_manager.connect(websocket)
    global latest_car_data_store
    try:
        while True:
            data_json = await websocket.receive_json() # Expecting JSON from car
            try:
                car_data_received = CarData(**data_json)
                car_data_received.timestamp_server_received_utc = datetime.datetime.utcnow().isoformat() + "Z"
                
                latest_car_data_store = car_data_received # Update the global store
                
                logging.info(f"Data from car {websocket.client.host}:{websocket.client.port} stored.")

                # Broadcast the new data to all connected UI clients
                if latest_car_data_store:
                    # .model_dump() creates a dict suitable for JSON serialization
                    await ui_connection_manager.broadcast_json_object(latest_car_data_store.model_dump())
                    logging.debug(f"Broadcasted latest data to {len(ui_connection_manager.active_connections)} UI clients.")

                # Send acknowledgment back to the car
                await websocket.send_json({
                    "status": "received",
                    "message_processed_at": car_data_received.timestamp_server_received_utc
                })

            except Exception as e: # Pydantic validation error or other processing error
                logging.error(f"Error processing car data from {websocket.client.host}:{websocket.client.port}: {e} - Raw Data: {data_json}")
                await websocket.send_json({"status": "error", "message": str(e)})

    except WebSocketDisconnect:
        logging.info(f"Car WebSocket disconnected by client: {websocket.client.host}:{websocket.client.port}")
    except Exception as e:
        logging.error(f"Unexpected Car WebSocket error for {websocket.client.host}:{websocket.client.port}: {e}")
        try:
            await websocket.close(code=1011) # Internal error
        except RuntimeError: pass # Already closed
    finally:
        car_connection_manager.disconnect(websocket)


# --- WebSocket Endpoint for UI Clients ---
@app.websocket("/ws/ui_updates")
async def websocket_ui_endpoint(websocket: WebSocket):
    await ui_connection_manager.connect(websocket)
    try:
        # Send the current latest data immediately upon connection if available
        if latest_car_data_store:
            try:
                await websocket.send_json(latest_car_data_store.model_dump())
            except Exception as e:
                logging.error(f"Error sending initial data to UI client {websocket.client.host}:{websocket.client.port}: {e}")
        
        # Keep the connection alive and detect disconnections
        while True:
            # This loop waits for the client to close the connection or send data (which we ignore here)
            # FastAPI/Uvicorn handles WebSocket ping/pongs by default to keep connections alive.
            # If client sends data, it will be received here. We are not expecting any for now.
            await websocket.receive_text() # This will raise WebSocketDisconnect if client closes

    except WebSocketDisconnect:
        logging.info(f"UI WebSocket disconnected by client: {websocket.client.host}:{websocket.client.port}")
    except Exception as e:
        logging.error(f"Unexpected UI WebSocket error for {websocket.client.host}:{websocket.client.port}: {e}")
        # No need to explicitly close here if an exception occurs, FastAPI handles it,
        # but ensure disconnect is called in finally.
    finally:
        ui_connection_manager.disconnect(websocket)


# --- HTTP GET Endpoint for Frontend to Fetch Data (for SSR or non-WebSocket clients) ---
@app.get("/api/latest_car_data", response_model=Optional[CarData])
async def get_latest_car_data():
    """
    Provides the most recent data received from the car.
    Useful for initial data load or clients not using WebSockets.
    """
    if latest_car_data_store:
        return latest_car_data_store
    return None # Or return a default empty structure if preferred by frontend

@app.get("/")
async def read_root():
    return {
        "message": "Car Data Backend is running.",
        "documentation": "/docs",
        "openapi_json": "/openapi.json",
        "car_websocket_endpoint": "/ws/car_data",
        "ui_websocket_endpoint": "/ws/ui_updates",
        "latest_data_http_endpoint": "/api/latest_car_data"
    }

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()] # Ensures logs go to stdout/stderr for OpenShift
)
# logger = logging.getLogger(__name__) # Example of getting a specific logger if needed

# To run locally: uvicorn backend.app.main:app --reload --port 8000
# (Assuming file is in backend/app/main.py)