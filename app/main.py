# backend/app/main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field # Ensure Field is imported from pydantic
from typing import List, Optional, Dict, Any
import datetime
import logging
import uvicorn # For running directly if needed

# --- Pydantic Models for Data Validation ---
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
    server_comm_time_ms: Optional[float] = None # Time car perceives for communication
    server_response_time_ms: Optional[float] = None # Time car perceives for response
    predicted_waypoints: Optional[List[Waypoint]] = None
    sensor_data: SensorData
    inference_mode: str # "local" or "cloud"
    vehicle_controls: VehicleControls
    image1_base64: Optional[str] = None  # <--- RENAMED and for first image
    image2_base64: Optional[str] = None # <--- THIS IS THE ADDED FIELD FOR THE IMAGE
    timestamp_car_sent_utc: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    # This will be added by the server upon receiving the message
    timestamp_server_received_utc: Optional[str] = None

app = FastAPI(
    title="Car Data Backend",
    description="Receives data from a car via WebSockets and provides it to a frontend via HTTP.",
    version="0.1.0"
)

# --- CORS (Cross-Origin Resource Sharing) ---
# Allow all origins for development. Restrict in production.
# You should restrict this to your actual frontend URL in production.
# Example: allow_origins=["https://your-frontend-app.openshiftapps.com", "http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory storage for the latest data ---
# This is a simple approach. For robustness or multiple cars, use Redis, a DB, or a more complex cache.
latest_car_data_store: Optional[CarData] = None
# If you plan to support multiple cars, you'd use a dictionary:
# latest_car_data_store: Dict[str, CarData] = {} # Keyed by a unique car_id

# --- WebSocket Connection Manager (Optional but good practice) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"Car connected: {websocket.client}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logging.info(f"Car disconnected: {websocket.client}")

    async def broadcast(self, message: str): # Example of broadcasting if needed
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# --- WebSocket Endpoint for Car Data ---
@app.websocket("/ws/car_data")
async def websocket_car_data_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    global latest_car_data_store
    try:
        while True:
            data_json = await websocket.receive_json() # Expecting JSON from car
            try:
                # ADD DETAILED LOGGING HERE:
                logging.info(f"RAW JSON received from client: {data_json}") # Log the raw dict

                car_data_received = CarData(**data_json)

                # Log the Pydantic model AFTER parsing. exclude_none=False shows fields that are None.
                logging.info(f"Pydantic model 'car_data_received' after parsing: {car_data_received.model_dump(exclude_none=False)}")

                car_data_received.timestamp_server_received_utc = datetime.datetime.utcnow().isoformat() + "Z"
                latest_car_data_store = car_data_received
                
                logging.info(f"Data received and stored from car {websocket.client}.")

                await websocket.send_json({
                    "status": "received",
                    "message_processed_at": car_data_received.timestamp_server_received_utc
                })

            except Exception as e:
                logging.error(f"Error processing car data: {e} - Raw Data: {data_json}") # Also log raw data on error
                await websocket.send_json({"status": "error", "message": str(e)})

    except WebSocketDisconnect:
        logging.info(f"WebSocket disconnected by client: {websocket.client}")
    except Exception as e:
        logging.error(f"Unexpected WebSocket error for {websocket.client}: {e}")
        # Attempt to close gracefully if not already closed
        try:
            await websocket.close(code=1011) # Internal error
        except RuntimeError: # Already closed or cannot close
            pass
    finally: # Ensure disconnection is handled
        manager.disconnect(websocket)


# --- HTTP GET Endpoint for Frontend to Fetch Data ---
@app.get("/api/latest_car_data", response_model=Optional[CarData])
async def get_latest_car_data():
    """
    Provides the most recent data received from the car.
    """
    if latest_car_data_store:
        return latest_car_data_store
    # You could return a 404 if no data is available yet
    # raise HTTPException(status_code=404, detail="No car data available yet.")
    # Or return a default structure if preferred
    return None

@app.get("/")
async def read_root():
    return {
        "message": "Car Data Backend is running.",
        "documentation": "/docs",
        "openapi_json": "/openapi.json",
        "websocket_car_endpoint": "/ws/car_data (for car client)",
        "latest_data_endpoint": "/api/latest_car_data (for frontend)"
    }

# --- Logging Configuration ---
# Configure logging to be more visible, especially in container environments
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()] # Ensures logs go to stdout/stderr for OpenShift to pick up
)
logger = logging.getLogger(__name__) # Example of getting a specific logger if needed

# To run locally (for testing): uvicorn app.main:app --reload --port 8000
# The __main__ block is usually for direct script execution, not typically used by Uvicorn when it runs module:app.
# For OpenShift, the CMD in Dockerfile ("uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080") will handle this.
# if __name__ == "__main__":
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)