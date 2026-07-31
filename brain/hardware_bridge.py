import asyncio
import json
import sys
import threading
from pathlib import Path

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)


RELAY_URL = "wss://shoulder-relay.onrender.com"


class HardwareBridge:
    """Remote bridge via WebSocket cloud relay.

    Connects to the cloud relay which forwards messages between PC and ESP32.
    Works across different networks (PC at home, ESP32 on phone hotspot).

    双模式连接:
    - 普通模式: connect() → 发命令 → disconnect() (每次命令独立连接)
    - 长连接模式: connect_persistent() → 保持连接 → disconnect() (观察模式专用)
    """

    def __init__(self, esp_ip="192.168.43.251", ws_port=81):
        self.relay_url = RELAY_URL
        self.ws = None
        self._connected = False
        self._send_lock = threading.Lock()
        # 长连接模式状态
        self._persistent = False
        self._reconnect_max = 3
        self._reconnect_count = 0

    @property
    def connected(self):
        return self._connected

    async def connect(self):
        try:
            self.ws = await asyncio.wait_for(
                websockets.connect(self.relay_url, ping_interval=30, ping_timeout=10),
                timeout=15,
            )
            await self.ws.send("PC")
            welcome = await asyncio.wait_for(self.ws.recv(), timeout=10)
            if isinstance(welcome, bytes):
                welcome = welcome.decode()
            self._connected = True
            print(f"[bridge] relay connected: {welcome}")
            return True
        except Exception as e:
            print(f"[bridge] connect failed: {e}")
            self._connected = False
            return False

    async def _drain_pending(self, timeout=0.3):
        """读取并丢弃残留的 WebSocket 数据，恢复同步。

        拍照超时后，ESP32 可能仍会发回旧的 JPEG 数据，
        导致后续命令读到错误类型的数据。此方法清空缓冲。
        """
        if not self.ws:
            return
        try:
            while True:
                _ = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            pass  # 正常：没有残留数据了
        except Exception:
            pass  # 连接问题，由下一个命令处理

    async def _send_cmd(self, cmd: str, binary=False, timeout_sec=5):
        if not self.ws or not self._connected:
            print("[bridge] not connected")
            return None
        try:
            await self.ws.send(cmd)
            for _ in range(2):  # 最多读2次（第1次可能拿到上个命令残留的数据）
                resp = await asyncio.wait_for(self.ws.recv(), timeout=timeout_sec)
                # 类型匹配 → 返回
                if binary and isinstance(resp, bytes):
                    return resp
                if not binary and isinstance(resp, str):
                    return resp
                # 类型不匹配 → 丢弃残留数据，重试
                print(f"[bridge] 丢弃残留数据 ({type(resp).__name__}), 重试 {cmd}")
            return None  # 读了2次都是残留数据，放弃
        except asyncio.TimeoutError:
            print(f"[bridge] timeout: {cmd}")
            return None
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
        resp = await self._send_cmd("servo 90 45")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def temp(self) -> dict | None:
        """Read DHT11 temperature/humidity."""
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

    # ════════════════════════════════════════════════════════════
    # 长连接模式（观察模式专用）
    # ════════════════════════════════════════════════════════════

    async def connect_persistent(self, max_retries=3):
        """建立持久化长连接。失败时自动重试，最多 max_retries 次。"""
        self._persistent = True
        self._reconnect_max = max_retries
        self._reconnect_count = 0
        for attempt in range(max_retries):
            if attempt > 0:
                import asyncio
                print(f"[bridge] 重连第 {attempt+1} 次...")
                await asyncio.sleep(2)
            try:
                ok = await self.connect()
                if ok:
                    self._reconnect_count = 0
                    print("[bridge] 长连接已建立")
                    return True
            except Exception as e:
                print(f"[bridge] 连接尝试 {attempt+1} 失败: {e}")
        print("[bridge] 长连接建立失败，已达最大重试次数")
        return False

    async def _ensure_connected(self) -> bool:
        """检查连接状态，断开时尝试自动重连（仅长连接模式）。"""
        if self._connected and self.ws:
            return True
        if not self._persistent:
            return False
        self._reconnect_count += 1
        if self._reconnect_count > self._reconnect_max:
            print("[bridge] 重连次数已达上限")
            return False
        print(f"[bridge] 连接断开，尝试重连 ({self._reconnect_count}/{self._reconnect_max})...")
        return await self.connect_persistent(max_retries=self._reconnect_max)

    async def disconnect(self):
        self._persistent = False
        self._reconnect_count = 0
        if self.ws:
            await self.ws.close()
            self._connected = False

    # ── 长连接模式下的命令发送（带自动重连） ────────────────

    async def _send_cmd_persistent(self, cmd: str, binary=False, timeout_sec=5):
        """长连接模式下发送命令，断开时自动重连。发送前清空残留数据防不同步。"""
        if not await self._ensure_connected():
            return None
        # 发送前快速 drain，避免上个超时命令的残留数据
        await self._drain_pending(timeout=0.2)
        return await self._send_cmd(cmd, binary=binary, timeout_sec=timeout_sec)

    async def photo_persistent(self, save_path=None) -> bytes | None:
        """长连接模式下拍照（复用已有连接）。超时 25 秒。"""
        data = await self._send_cmd_persistent("photo", binary=True, timeout_sec=25)
        if data and isinstance(data, bytes) and len(data) > 100:
            if save_path:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                Path(save_path).write_bytes(data)
                print(f"[bridge] photo saved: {save_path} ({len(data)} bytes)")
            return data
        return None

    async def status_persistent(self) -> dict | None:
        """长连接模式下查询状态。"""
        resp = await self._send_cmd_persistent("status")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def pan_persistent(self, angle: int) -> dict | None:
        """长连接模式下水平旋转。"""
        resp = await self._send_cmd_persistent(f"pan {angle}")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def tilt_persistent(self, angle: int) -> dict | None:
        """长连接模式下垂直俯仰。"""
        resp = await self._send_cmd_persistent(f"tilt {angle}")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    async def center_persistent(self) -> dict | None:
        """长连接模式下云台复位到 (90°, 45°)。"""
        resp = await self._send_cmd_persistent("servo 90 45")
        if resp:
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                pass
        return None

    # ── 跟踪模式：只发不收（ESP32 在推流，不能 drain/read 响应） ──

    async def send_cmd_tracking(self, cmd: str):
        """跟踪模式下发送命令，不读取响应（ESP32 正在持续推流）。"""
        if not self.ws or not self._connected:
            return
        try:
            with self._send_lock:
                await self.ws.send(cmd)
        except Exception:
            pass


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

    print("--- temp ---")
    print(await bridge.temp())

    print("--- photo ---")
    await bridge.photo("test_photo.jpg")

    await bridge.disconnect()
    print("done")


if __name__ == "__main__":
    asyncio.run(test())
