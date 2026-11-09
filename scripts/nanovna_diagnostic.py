"""Display NanoVNA diagnostics without retaining session data."""
import argparse,asyncio,json,logging,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.nanovna.device import SerialNanoVNA
async def run(port,baudrate):
    dev=SerialNanoVNA(port,baudrate); logging.basicConfig(level=logging.DEBUG,force=True)
    try:
        info=await dev.connect(); print(json.dumps(info,indent=2))
    finally: await dev.disconnect()
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--port",default="COM4");p.add_argument("--baudrate",type=int,default=115200);a=p.parse_args();asyncio.run(run(a.port,a.baudrate))

