from contextlib import asynccontextmanager
from pathlib import Path
import json,logging
from fastapi import FastAPI,HTTPException,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field
from .predictor import Predictor,WARNING
from .live_manager import LiveManager
from .nanovna.device import available_ports,device_for_port
ROOT=Path(__file__).resolve().parents[1]; logging.basicConfig(level=logging.INFO)
cfg=json.loads((ROOT/"config"/"device.json").read_text()); predictor=Predictor(); live=LiveManager(predictor,cfg)
@asynccontextmanager
async def lifespan(app):
    yield
    await live.disconnect()
app=FastAPI(title="BoneWave AI",lifespan=lifespan); app.mount("/static",StaticFiles(directory=ROOT/"app"/"static"),name="static")
class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    port: str = Field(min_length=1)
@app.get("/")
def index(): return FileResponse(ROOT/"app"/"static"/"index.html")
@app.get("/api/health")
def health(): return {"status":"ok","warning":WARNING}
@app.get("/api/model-info")
def model_info():
    references=predictor.reference_status()
    return {
        "mode":"real_three_class_reference_bank",
        "usage":"Same-specimen, multi-angle research prototype",
        **references,
        "independent_test_specimens":0,
        "warning":"No generalization or medical accuracy claim; Normal and Crack each contain angles from one specimen.",
    }
@app.get("/api/device/ports")
def ports(): return {"ports":available_ports()}
@app.post("/api/device/connect")
async def connect(req:ConnectRequest):
    try:
        if req.port not in {item["port"] for item in available_ports()}:
            raise HTTPException(400,"Select an available serial device and rescan if needed")
        if live.device and live.device.connected and live.device.port == req.port:
            return {"status":"already_connected","info":live.device.info}
        device=device_for_port(req.port,cfg["baudrate"],cfg["serial_timeout_seconds"])
        return {"status":"connected","info":await live.connect(device)}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(503,str(exc)) from exc
@app.post("/api/device/disconnect")
async def disconnect(): await live.disconnect(); return live.status()
@app.post("/api/live/start")
async def start():
    try:
        await live.start()
        return {"status":"started"}
    except RuntimeError as exc: raise HTTPException(409,str(exc)) from exc
@app.post("/api/live/stop")
async def stop(): await live.stop(); return live.status()
@app.get("/api/live/status")
def status(): return live.status()
@app.websocket("/ws/live")
async def websocket(ws:WebSocket):
    await ws.accept(); live.clients.add(ws); await ws.send_json({"status":"connected","device":live.status(),"warning":WARNING})
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: live.clients.discard(ws)
