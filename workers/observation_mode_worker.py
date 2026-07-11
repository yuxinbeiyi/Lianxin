"""
ObservationModeWorker：观察模式后台线程。
在独立的 QThread 中运行循环：转头→拍照→分析→发送→检查消息。
"""

import asyncio
import os
import random
import time
from pathlib import Path
from config import get_user_name

from PyQt5.QtCore import QThread, pyqtSignal


# ── 舵机角度限制 ─────────────────────────────────────────
PAN_MIN = 20
PAN_MAX = 150
TILT_CENTER = 45


def get_qq_bridge():
    """获取 QQBridgeWorker 实例（复用 tools.py 中的全局引用）。"""
    from brain import tools
    return tools._qq_bridge_worker


class ObservationModeWorker(QThread):
    """观察模式后台循环线程。

    每分钟最多 2 轮完整观察，剩余时间 idle 随机转头（不拍照）。
    水平舵机限制 20~150°，垂直每轮复位到 90°。
    """

    cycle_completed = pyqtSignal(str)   # 每轮完成时发射（消息摘要）
    mode_exited = pyqtSignal(str)       # 观察模式退出时发射（原因文本）
    pending_messages = pyqtSignal(list) # 有待处理的用户消息

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self._state = state
        self._bridge = None
        self._loop = None
        self._current_pan = 90
        self._current_tilt = 90
        self._cost_tracker = None
        self._rate_limiter = None
        self._cycle_limiter = None
        self._qq = None
        self._photo_save_dir = Path.home() / ".lianxin" / "observations"
        self._photo_save_dir.mkdir(parents=True, exist_ok=True)
        # 连续失败追踪（防止无限重试风暴）
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3

    def run(self):
        """主循环入口。"""
        from brain.observation_mode import get_cost_tracker, get_rate_limiter, CycleRateLimiter
        from brain.hardware_bridge import HardwareBridge

        self._cost_tracker = get_cost_tracker()
        self._rate_limiter = get_rate_limiter()
        self._cycle_limiter = CycleRateLimiter(max_per_minute=2)
        self._qq = get_qq_bridge()
        self._bridge = HardwareBridge()

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        if not self._loop.run_until_complete(self._bridge.connect_persistent()):
            self._safe_exit("连接肩载设备失败，请检查 ESP32 是否在线")
            return

        exit_reason = None
        try:
            self._observation_loop()
        except Exception as e:
            exit_reason = f"观察模式异常退出：{e}"
        finally:
            if exit_reason:
                self._safe_exit(exit_reason)
            else:
                self._center_gimbal()
            self._cleanup()

    # ════════════════════════════════════════════════════════
    # 主循环
    # ════════════════════════════════════════════════════════

    def _observation_loop(self):
        """核心循环体。
        每分钟最多 2 轮完整观察（拍照+分析+发送），
        剩余时间 idle 随机转头但不拍照。
        """
        while self._state.is_active:
            # ── 检查是否可以开始一轮完整观察（≤2次/分钟） ──
            if self._cycle_limiter.can_start_cycle():
                if not self._full_observation_cycle():
                    break  # 循环内出错或模式退出
            else:
                # ── idle 时间：随机转头但不拍照 ──
                wait_sec = min(self._cycle_limiter.next_slot_in, 10)
                if wait_sec > 0.5:
                    # 在等待期间左顾右盼
                    self._idle_pan_around(wait_sec)

            # ── 每轮（或每次idle）后统一检查 ──
            if not self._state.is_active:
                break
            if self._state.check_idle_and_exit():
                break
            self._check_pending_messages()

    def _full_observation_cycle(self) -> bool:
        """执行一轮完整观察：复位→转头→拍照→分析→发送。返回 False 表示需退出。"""
        round_num = self._cost_tracker._daily_calls + 1
        print(f"[观察模式] === 第 {round_num} 轮观察 ===")

        # ① 好奇转头 1~8 次（范围 20~150°）
        if not self._curious_look_around():
            return False

        # ③ 拍照 + 压缩 ≤200KB
        photo_path = self._take_photo()
        if not photo_path:
            # 拍照失败：记录循环次数防止忙等，连续超阈值则退出
            self._consecutive_failures += 1
            self._cycle_limiter.record_cycle()
            print(f"[观察模式] 拍照失败 ({self._consecutive_failures}/{self._max_consecutive_failures})")
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._safe_exit(
                    "连续多次拍照失败，请检查肩载设备状态，退出【观察模式】"
                )
                return False
            return True

        # ④ 检查费用
        if self._cost_tracker.is_over_limit():
            self._safe_exit(
                "今天视觉功能用的有点多了哦，我先退出啦～\n"
                "除非你再次启动【观察模式】，我就可以继续看哦(｀・ω・´)"
            )
            return False

        # ⑤ 视觉 API 分析
        description = self._analyze_image(photo_path)
        if not description.startswith("错误"):
            self._cost_tracker.record_call()

        # ⑥ LLM 生成简洁拟人化描述（≤300 字）
        cute_message = self._generate_message(description)

        # ⑦ 发送图片 + 文字到 QQ（带打字延迟）
        self._send_observation(photo_path, cute_message)

        # 发射桌面信号
        self.cycle_completed.emit(cute_message[:80])

        # ⑧ 检查 ESP32 健康
        if not self._check_esp32_health():
            self._safe_exit("肩载设备状态异常，已退出【观察模式】")
            return False

        # 登记本轮完成（用于 2 次/分钟限频）
        self._cycle_limiter.record_cycle()
        self._consecutive_failures = 0
        return True

    # ════════════════════════════════════════════════════════
    # idle 空闲期：只转头不拍照
    # ════════════════════════════════════════════════════════

    def _idle_pan_around(self, duration_seconds: float):
        """在循环等待期间，水平随机转头但不拍照。"""
        end = time.time() + duration_seconds
        count = 0
        while time.time() < end and self._state.is_active:
            delta = random.choice([-40, -30, -20, -15, 15, 20, 30, 40])
            new_pan = max(PAN_MIN, min(PAN_MAX, self._current_pan + delta))
            try:
                self._loop.run_until_complete(self._bridge.pan_persistent(new_pan))
                self._current_pan = new_pan
                count += 1
            except Exception:
                break
            time.sleep(random.uniform(0.5, 1.2))

        if count > 0:
            print(f"[观察模式] 🐾 idle 转头 {count} 次")

    # ════════════════════════════════════════════════════════
    # 各环节具体实现
    # ════════════════════════════════════════════════════════

    def _do_center_tilt(self) -> bool:
        """垂直舵机复位到 TILT_CENTER。失败时计数，超阈值退出。"""
        try:
            self._loop.run_until_complete(self._bridge.tilt_persistent(TILT_CENTER))
            self._current_tilt = TILT_CENTER
            time.sleep(0.3)
            self._consecutive_failures = 0
            return True
        except Exception as e:
            print(f"[观察模式] 垂直复位失败: {e}")
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._safe_exit("肩载设备连续多次无响应，退出【观察模式】")
                return False
            return self._state.is_active

    def _curious_look_around(self) -> bool:
        """随机水平转头 1~8 次，范围 20~150°。失败时计数，超阈值退出。"""
        n = random.randint(1, 8)
        print(f"[观察模式] 🐾 扭头 {n} 次 ({self._current_pan}°→...)")
        for _ in range(n):
            if not self._state.is_active:
                return False
            delta = random.choice([-50, -40, -30, -20, -15, 15, 20, 30, 40, 50])
            new_pan = max(PAN_MIN, min(PAN_MAX, self._current_pan + delta))
            try:
                self._loop.run_until_complete(self._bridge.pan_persistent(new_pan))
                self._current_pan = new_pan
                self._consecutive_failures = 0
            except Exception as e:
                print(f"[观察模式] 转头失败: {e}")
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._max_consecutive_failures:
                    self._safe_exit("肩载设备连续多次无响应，退出【观察模式】")
                    return False
                return self._state.is_active
            time.sleep(random.uniform(0.5, 1.5))
        return True

    def _take_photo(self) -> str:
        """拍照并压缩到 ≤200KB。

        先拍一张丢弃（预热摄像头传感器），第二张才正式使用。
        解决 ESP32-CAM 在某些条件下返回旧帧缓存的问题。
        """
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_path = str(self._photo_save_dir / f"obs_{timestamp}.jpg")

            # 第一张：预热摄像头（丢弃），唤醒传感器，清空帧缓冲
            warmup = self._loop.run_until_complete(
                self._bridge.photo_persistent()
            )
            if warmup:
                print(f"[观察模式] 📸 预热完成 ({len(warmup)} bytes)")
            time.sleep(0.3)

            # 第二张：正式拍照
            data = self._loop.run_until_complete(
                self._bridge.photo_persistent(save_path=save_path)
            )
            if not data or len(data) < 100:
                print("[观察模式] 拍照失败：未收到图片数据")
                return ""
            compressed = self._compress_image(save_path)
            return compressed
        except Exception as e:
            print(f"[观察模式] 拍照异常: {e}")
            return ""

    def _compress_image(self, path: str, max_kb=200) -> str:
        """JPEG 质量压缩到 ≤200KB。"""
        try:
            from PIL import Image
            img = Image.open(path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            stem, ext = os.path.splitext(path)
            compressed_path = f"{stem}_c{ext}"
            quality = 85
            while quality >= 20:
                img.save(compressed_path, "JPEG", quality=quality)
                if os.path.getsize(compressed_path) <= max_kb * 1024:
                    break
                quality -= 5
            return compressed_path
        except ImportError:
            return path
        except Exception as e:
            print(f"[观察模式] 压缩失败: {e}")
            return path

    def _analyze_image(self, path: str) -> str:
        """调用 SiliconFlow 视觉 API 分析图片内容。"""
        from brain.vision import describe_image
        prompt = (
            "请详细描述这张画面里的内容。注意观察——"
            "画面中有什么人物、物体、场景、颜色、动作、文字等。"
            "尽量关注细节，比如物品的位置、状态、颜色、人物表情动作。"
        )
        result = describe_image(path, prompt=prompt)
        print(f"[观察模式] 👁 分析完成 ({len(result)} 字)")
        return result

    def _generate_message(self, description: str) -> str:
        """LLM 生成简洁拟人化描述（≤300 字）。失败时对原文加前缀降级。"""
        from openai import OpenAI
        from config import get_api_config, get_agnes_config

        cfg = get_api_config()
        provider = cfg.get("provider", "deepseek")
        if provider == "agnes":
            agnes_cfg = get_agnes_config()
            api_key = agnes_cfg["api_key"]
            base_url = agnes_cfg["base_url"]
            model = agnes_cfg["model"]
        else:
            api_key = cfg["api_key"]
            base_url = cfg["base_url"]
            model = cfg["model"]

        if not api_key:
            print("[观察模式] 无 API Key，使用原始描述")
            return _truncate(description)

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=400,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是莲心，刚刚通过肩载摄像头看了一眼周围环境。\n"
                            "用可爱简短的语气说一句话。要求：\n"
                            "- 控制在 300 字以内，越短越好\n"
                            "- 保留视觉识别的核心内容（人物/物体/场景/动作）\n"
                            "- 语气活泼好奇，可以加颜文字 (｀・ω・´)\n"
                            f"- 称呼用户为'{get_user_name()}'\n"
                            "- 直接说看到的内容，不要'我看到了'开头\n"
                            "- 每次描述角度不同，不重复说法"
                        ),
                    },
                    {"role": "user", "content": f"画面内容：{description}"},
                ],
                timeout=20,
            )
            msg = resp.choices[0].message.content
            if msg and msg.strip():
                # LLM 成功生成
                if len(msg) > 300:
                    msg = msg[:297] + "..."
                print(f"[观察模式] 💬 LLM 生成消息 ({len(msg)} 字)")
                return msg

            # LLM 返回了空内容 → 降级
            print("[观察模式] LLM 返回空，降级使用原始描述")
            # 给原始描述加个简短的前缀，让它看起来不像是"直接输出"
            return f"我看到啦——{_truncate(description)}"
        except Exception as e:
            print(f"[观察模式] LLM 生成失败 ({e})，降级使用原始描述")
            return f"我看到啦——{_truncate(description)}"

    def _send_observation(self, photo_path: str, message: str):
        """发送图片+文字到 QQ，带打字速度延迟。"""
        if not self._qq:
            print("[观察模式] QQ 桥接未注册，跳过发送")
            return

        # 限速等待（每分钟 2 张图）
        wait = self._rate_limiter.wait_time()
        if wait > 0:
            print(f"[观察模式] 图片限速等待 {wait:.0f} 秒")
            self._interruptible_sleep(wait)

        if not self._state.is_active:
            return

        # 发图片
        self._rate_limiter.record_send()
        try:
            self._qq.send_file_to_qq(photo_path)
            print(f"[观察模式] 📷 图片已发送 ({os.path.getsize(photo_path)} 字节)")
        except Exception as e:
            print(f"[观察模式] 发送图片失败: {e}")

        # 打字速度延迟（模拟输入时间，1~3 秒）
        typing_delay = random.uniform(1.0, 3.0)
        self._interruptible_sleep(typing_delay)

        # 发文字描述
        if message:
            try:
                self._qq.send_to_owner(message)
                print(f"[观察模式] 💬 描述已发送 ({len(message)} 字)")
            except Exception as e:
                print(f"[观察模式] 发送描述失败: {e}")

    def _check_esp32_health(self) -> bool:
        """检查 ESP32 free_heap。"""
        try:
            status = self._loop.run_until_complete(self._bridge.status_persistent())
            if status and isinstance(status, dict):
                heap = status.get("free_heap", 99999)
                if heap < 20000:
                    print(f"[观察模式] ESP32 内存不足: {heap} bytes")
                    return False
            return True
        except Exception as e:
            print(f"[观察模式] 健康检查失败: {e}")
            return True

    def _check_pending_messages(self):
        """检查是否有用户消息排队等待处理。"""
        if not self._state.has_pending:
            return

        print(f"[观察模式] 📨 发现待处理用户消息")
        msgs = self._state.drain_pending()
        self.pending_messages.emit(msgs)
        self._state.notify_processing_started()
        self._state.wait_resume()

    # ════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════

    def _interruptible_sleep(self, seconds: float) -> bool:
        """可中断休眠。返回 False 表示模式已退出。"""
        end = time.time() + seconds
        while time.time() < end:
            if not self._state.is_active:
                return False
            time.sleep(0.2)
        return True

    def _center_gimbal(self):
        """复位云台到中心 (90°, 90°)。"""
        if self._loop and self._bridge:
            try:
                self._loop.run_until_complete(self._bridge.center_persistent())
            except Exception:
                pass

    def _safe_exit(self, reason: str):
        """安全退出：停用状态、复位云台、断开连接、发送通知。"""
        self._state.deactivate()
        self._center_gimbal()
        if self._qq:
            try:
                self._qq.send_to_owner(
                    f"{reason}\n【观察模式】已退出～(｡•́︿•̀｡)"
                )
            except Exception:
                pass
        self.mode_exited.emit(reason)

    def _cleanup(self):
        """清理资源。"""
        if self._loop and self._bridge:
            try:
                self._loop.run_until_complete(self._bridge.disconnect())
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
        print("[观察模式] 资源已清理")


def _truncate(text: str, max_len: int = 300) -> str:
    """截断文本到最大长度，保留关键信息。"""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."