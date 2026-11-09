from abc import ABC,abstractmethod
import asyncio, logging, time, numpy as np
from .protocol import NanoVNAProtocol,NanoVNAV2Protocol,ProtocolError
log=logging.getLogger(__name__)
class DeviceError(RuntimeError): pass
class BaseNanoVNA(ABC):
    connected=False
    @abstractmethod
    async def connect(self): ...
    @abstractmethod
    async def disconnect(self): ...
    @abstractmethod
    async def acquire_segment(self,start,stop,points): ...

class SerialNanoVNA(BaseNanoVNA):
    def __init__(self,port,baudrate=115200,timeout=3,protocol=None): self.port=port; self.baudrate=baudrate; self.timeout=timeout; self.protocol=protocol or NanoVNAProtocol(); self.serial=None; self.info={}
    async def _command(self,cmd):
        def run():
            self.serial.reset_input_buffer(); self.serial.write(cmd); self.serial.flush(); return self.serial.read_until(self.protocol.prompt)
        raw=await asyncio.to_thread(run); log.debug("NanoVNA raw response to %r: %r",cmd,raw); return raw
    async def connect(self):
        try:
            import serial
            self.serial=serial.Serial(self.port,self.baudrate,timeout=self.timeout,write_timeout=self.timeout); self.connected=True
            replies=[(await self._command(c)).decode(errors="replace") for c in self.protocol.info_commands()]; self.info={"device":self.port,"firmware":" | ".join(replies).strip()}; return self.info
        except Exception as exc: await self.disconnect(); raise DeviceError(f"Unable to connect to {self.port}: {exc}") from exc
    async def disconnect(self):
        if self.serial:
            await asyncio.to_thread(self.serial.close); self.serial=None
        self.connected=False
    async def acquire_segment(self,start,stop,points):
        if not self.connected: raise DeviceError("Device is not connected")
        try:
            await self._command(self.protocol.sweep_command(int(start),int(stop),points)); s11=self.protocol.parse_complex(await self._command(self.protocol.data_command(0)),points); s21=self.protocol.parse_complex(await self._command(self.protocol.data_command(1)),points)
            return np.linspace(start,stop,points),np.asarray(s11),np.asarray(s21)
        except Exception as exc: raise DeviceError(f"Serial acquisition failed: {exc}") from exc

class NanoVNAV2(BaseNanoVNA):
    """Direct binary-protocol driver for NanoRFE NanoVNA V2 hardware."""
    def __init__(self,port,baudrate=115200,timeout=3,protocol=None):
        self.port=port; self.baudrate=baudrate; self.timeout=timeout; self.protocol=protocol or NanoVNAV2Protocol(); self.serial=None; self.info={}
    def _read_exact(self,size):
        data=bytearray(); deadline=time.monotonic()+self.timeout
        while len(data)<size and time.monotonic()<deadline:
            chunk=self.serial.read(size-len(data))
            if chunk: data.extend(chunk)
        if len(data)!=size: raise ProtocolError(f"Timed out after receiving {len(data)} of {size} bytes")
        return bytes(data)
    def _read_register(self,address):
        self.serial.write(self.protocol.read_register(address)); self.serial.flush(); return self._read_exact(1)[0]
    async def connect(self):
        try:
            import serial
            self.serial=serial.Serial(self.port,self.baudrate,timeout=.1,write_timeout=self.timeout); self.serial.reset_input_buffer(); self.serial.write(self.protocol.reset_command()); self.serial.flush(); await asyncio.sleep(.05)
            variant=await asyncio.to_thread(self._read_register,self.protocol.DEVICE_VARIANT); protocol=await asyncio.to_thread(self._read_register,self.protocol.PROTOCOL_VERSION); hardware=await asyncio.to_thread(self._read_register,self.protocol.HARDWARE_REVISION); major=await asyncio.to_thread(self._read_register,self.protocol.FIRMWARE_MAJOR); minor=await asyncio.to_thread(self._read_register,self.protocol.FIRMWARE_MINOR)
            if variant!=2: raise ProtocolError(f"Expected NanoVNA V2 variant 2, received {variant}")
            self.connected=True; self.info={"device":self.port,"model":"NanoVNA V2","variant":variant,"protocol_version":protocol,"hardware_revision":hardware,"firmware":f"{major}.{minor}"}; return self.info
        except Exception as exc: await self.disconnect(); raise DeviceError(f"Unable to connect to NanoVNA V2 on {self.port}: {exc}") from exc
    async def disconnect(self):
        if self.serial:
            await asyncio.to_thread(self.serial.close); self.serial=None
        self.connected=False
    def _acquire_sync(self,start,stop,points):
        p=self.protocol; self.serial.reset_input_buffer(); self.serial.write(p.reset_command()); self.serial.write(p.configure_sweep(start,stop,points)); self.serial.flush(); time.sleep(.06)
        self.serial.write(p.clear_fifo()); self.serial.flush(); time.sleep(.06); self.serial.reset_input_buffer()
        self.serial.write(p.read_fifo(points)); self.serial.flush(); payload=self._read_exact(points*p.RECORD_SIZE); s11,s21=p.parse_fifo(payload,points)
        step=round((stop-start)/(points-1)); frequency=np.asarray([start+i*step for i in range(points)],dtype=float)
        return frequency,np.asarray(s11),np.asarray(s21)
    async def acquire_segment(self,start,stop,points):
        if not self.connected: raise DeviceError("Device is not connected")
        try: return await asyncio.to_thread(self._acquire_sync,int(start),int(stop),points)
        except Exception as exc: raise DeviceError(f"NanoVNA V2 binary acquisition failed: {exc}") from exc

def available_ports():
    try:
        from serial.tools import list_ports
        return [{"port":p.device,"description":p.description,"vid":p.vid,"pid":p.pid,"protocol":"nanovna_v2" if (p.vid,p.pid)==(0x04B4,0x0008) else "shell"} for p in list_ports.comports()]
    except Exception: return []

def device_for_port(port,baudrate=115200,timeout=3):
    try:
        from serial.tools import list_ports
        match=next((p for p in list_ports.comports() if p.device.upper()==port.upper()),None)
        if match and (match.vid,match.pid)==(0x04B4,0x0008): return NanoVNAV2(port,baudrate,timeout)
    except Exception: pass
    return SerialNanoVNA(port,baudrate,timeout)
