import asyncio
import json
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)


class HardwareBridge:
    """ESP32-CAM WebSocket bridge for 莲心AI."""

    def __init__(self, esp_ip="192.168.43.251", ws_port=81):
        self.uri = f"ws://{esp_ip}:{ws_port}"
        self.ws = None
        self._connected = False

    @property
    def connected(self):
        return self._connected

    async def connect(self):
        try:
            self.ws = await asyncio.wait_for(
                websockets.connect(self.uri, ping_interval=30, ping_timeout=10),
                timeout=10,
            )
            self._connected = True
            hello = await asyncio.wait_for(self.ws.recv(), timeout=5)
            info = json.loads(hello)
            print(f"[bridge] connected: {info}")
            return True
        except Exception as e:
            print(f"[bridge] connect failed: {e}")
            self._connected = False
            return False

    async def _send_cmd(self, cmd: str, binary=False, timeout_sec=5):
        if not self.ws or not self._connected:
            print("[bridge] not connected")
            return None
        try:
            await self.ws.send(cmd)
            resp = await asyncio.wait_for(self.ws.recv(), timeout=timeout_sec)
            if binary or isinstance(resp, bytes):
                return resp
            return resp if isinstance(resp, str) else resp.decode()
        except Exception as e:
            print(f"[bridge] error: {e}")
            return None

    async def ping(self) -> bool:
        resp = await self._send_cmd("ping")
        return resp is not None and "pong" in str(resp)

    async def status(self) -> dict | None:
        resp = await self._send_cmd("status")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def photo(self, save_path=None) -> bytes | None:
        data = await self._send_cmd("photo", binary=True, timeout_sec=15)
        if data and isinstance(data, bytes) and len(data) > 100:
            if save_path:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                Path(save_path).write_bytes(data)
                print(f"[bridge] photo saved: {save_path} ({len(data)} bytes)")
            return data
        return None

    async def servo(self, pan: int, tilt: int) -> dict | None:
        resp = await self._send_cmd(f"servo {pan} {tilt}")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def pan(self, angle: int) -> dict | None:
        resp = await self._send_cmd(f"pan {angle}")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def tilt(self, angle: int) -> dict | None:
        resp = await self._send_cmd(f"tilt {angle}")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def center(self) -> dict | None:
        resp = await self._send_cmd("center")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def temp(self) -> dict | None:
        """读取 DHT11 温湿度，返回 {"temp": 25.0, "humidity": 60.0}"""
        resp = await self._send_cmd("temp")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def scan(self, steps=30) -> list[bytes]:
        """Pan across range, taking photos at each step. Returns list of JPEGs."""
        photos = []
        for a in range(0, 181, steps):
            await self.servo(a, 90)
            await asyncio.sleep(0.4)
            data = await self.photo()
            if data:
                photos.append(data)
        await self.center()
        return photos

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self._connected = False


async def test():
    bridge = HardwareBridge()
    if not await bridge.connect():
        return

    print("--- ping ---")
    print(await bridge.ping())

    print("--- center ---")
    print(await bridge.center())
    await asyncio.sleep(0.5)

    print("--- pan 45 ---")
    print(await bridge.pan(45))
    await asyncio.sleep(0.5)

    print("--- tilt 120 ---")
    print(await bridge.tilt(120))
    await asyncio.sleep(0.5)

    print("--- servo 90 60 ---")
    print(await bridge.servo(90, 60))
    await asyncio.sleep(0.5)

    print("--- center ---")
    print(await bridge.center())

    print("--- photo ---")
    await bridge.photo("test_photo.jpg")

    await bridge.disconnect()
    print("done")


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.43.251"
    bridge = HardwareBridge(esp_ip=ip)
    asyncio.run(test())
