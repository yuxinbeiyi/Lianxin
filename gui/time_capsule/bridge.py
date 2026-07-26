"""Time Capsule Web 前端与 Python 数据层之间的稳定桥接。"""

from __future__ import annotations

import base64
import binascii
import json
import re
import shutil
import uuid
from datetime import date
from pathlib import Path
from threading import Lock, Thread

from PyQt5.QtCore import QObject, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices, QImage
from PyQt5.QtWidgets import QFileDialog

from config import get_user_name
from config import get_diary_config, save_diary_config
from utils.paths import get_user_data_dir
from .database import TimeCapsuleDatabase


class TimeCapsuleBridge(QObject):
    state_changed = pyqtSignal(str)
    page_state_changed = pyqtSignal(str, str)
    page_invalidated = pyqtSignal(str)
    tree_reply_ready = pyqtSignal(int, str)
    generation_requested = pyqtSignal(str)
    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal()
    settings_changed = pyqtSignal()
    companion_ready = pyqtSignal(str)

    def __init__(self, parent=None, db_path=None):
        super().__init__(parent)
        self.db = TimeCapsuleDatabase(db_path)
        self._memory_linking = set()
        self._memory_linking_lock = Lock()
        self._companion_running = False
        self._companion_lock = Lock()
        self._companion_source = ("", "all")
        self._tree_reply_running = set()
        self._tree_reply_lock = Lock()

    @staticmethod
    def _json(payload) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _state(self, day: str | None = None) -> dict:
        # Only the visible Today page is sent at startup. Other pages are
        # fetched when opened, avoiding an expensive all-history WebEngine
        # render before the window becomes interactive.
        config = get_diary_config()
        return {
            "today": self.db.get_day(day or date.today().isoformat()),
            "user_name": get_user_name(),
            "timeline_count": self.db.timeline_count(),
            "companion": {},
            "ui_settings": {
                "timeline_page_size": config.get("timeline_page_size", 15),
                "animations_enabled": config.get("animations_enabled", True),
                "low_power_mode": config.get("low_power_mode", False),
            },
        }

    def _page_state(self, page: str) -> dict:
        if page == "corridor":
            config = get_diary_config()
            return {
                "contribution": self.db.contribution(),
                "recent_collections": self.db.recent_collections(),
                "timeline_page": self.db.timeline_page(
                    1, config.get("timeline_page_size", 15), "all"
                ),
            }
        if page == "tree":
            return {"tree_page": self.db.tree_notes_page()}
        if page == "museum":
            return {"museum_page": self.db.favorite_diaries_page()}
        return self._state()

    def emit_state(self, day: str | None = None) -> None:
        self.state_changed.emit(self._json(self._state(day)))

    def emit_page_state(self, page: str) -> None:
        self.page_invalidated.emit(page)

    @pyqtSlot(result=str)
    def get_initial_state(self):
        return self._json(self._state())

    @pyqtSlot(str, result=str)
    def get_day(self, day):
        try:
            # 侧栏只展示当日最终书页和后续笔迹；旧版自动保存产生的
            # revision 不再作为独立日记展示。
            return self._json(self.db.get_day(str(day)))
        except Exception as exc:
            return self._json({"ok": False, "error": f"无法读取这一天的日记：{exc}"})

    @pyqtSlot(str, result=str)
    def get_page_state(self, page):
        try:
            return self._json(self._page_state(str(page)))
        except Exception as exc:
            return self._json({"ok": False, "error": f"页面读取失败：{exc}"})

    @pyqtSlot(int, int, str, result=str)
    def get_corridor_page(self, page, page_size, author="all"):
        try:
            return self._json({
                "contribution": self.db.contribution(),
                "recent_collections": self.db.recent_collections(),
                "timeline_page": self.db.timeline_page(
                    int(page), int(page_size), str(author)
                ),
            })
        except Exception as exc:
            return self._json({"ok": False, "error": f"时间长廊读取失败：{exc}"})

    @pyqtSlot(int, int, str, str, result=str)
    def get_museum_page(self, page, page_size, query, sort):
        try:
            return self._json({
                "museum_page": self.db.favorite_diaries_page(
                    int(page), int(page_size), str(query), str(sort)
                )
            })
        except Exception as exc:
            return self._json({"ok": False, "error": f"收藏馆读取失败：{exc}"})

    @pyqtSlot(int, int, str, str, str, bool, result=str)
    def get_tree_page(self, page, page_size, filter_name, query, sort, archived):
        try:
            return self._json({
                "tree_page": self.db.tree_notes_page(
                    int(page), int(page_size), str(filter_name), str(query),
                    str(sort), bool(archived),
                )
            })
        except Exception as exc:
            return self._json({"ok": False, "error": f"纸匣子读取失败：{exc}"})

    @pyqtSlot(str, str, result=str)
    def save_user_content(self, day, content):
        result = self.db.save_user_content(str(day), str(content))
        # 中文输入法组合文字期间若回推整份状态，旧版 Qt WebEngine 会反复重绘
        # 页面并让候选框闪烁。保存成功即可，完整状态只在显式操作后刷新。
        return self._json(result)

    @pyqtSlot(str, str, result=str)
    def seal_day(self, day, user_content):
        day = str(day)
        self.db.save_user_content(day, str(user_content))
        result = self.db.seal_day(day)
        self._start_memory_link(day, result)
        if not str(result.get("lianxin_content", "")).strip():
            self.generation_requested.emit(day)
        self.emit_state(day)
        self.emit_page_state("corridor")
        return self._json(result)

    @pyqtSlot(str, result=str)
    def toggle_day_favorite(self, day):
        try:
            result = self.db.toggle_day_favorite(str(day))
            self.emit_page_state("corridor")
            self.emit_page_state("museum")
            return self._json({"ok": True, "day": result})
        except Exception as exc:
            return self._json({"ok": False, "error": f"收藏状态保存失败：{exc}"})

    def _start_memory_link(self, day: str, result: dict) -> None:
        """封存先完成；较慢的向量记忆写入在后台继续。"""
        if int((result.get("source") or {}).get("memory_fact_id", 0) or 0):
            return
        with self._memory_linking_lock:
            if day in self._memory_linking:
                return
            self._memory_linking.add(day)
        Thread(
            target=self._register_sealed_memory,
            args=(day, result),
            name=f"capsule-memory-{day}",
            daemon=True,
        ).start()

    def _register_sealed_memory(self, day: str, result: dict) -> None:
        """Explicit sealing is the consent boundary for long-term memory linking."""
        if int((result.get("source") or {}).get("memory_fact_id", 0) or 0):
            return
        user_text = str(result.get("user_content", "")).strip()
        lianxin_text = str(result.get("lianxin_content", "")).strip()
        if not user_text and not lianxin_text:
            return
        run_id = 0
        try:
            from brain.workflow import get_workflow_store
            workflow = get_workflow_store()
            run = workflow.begin_run(
                kind="time_capsule_seal", title=f"封存 {day} 的时间胶囊",
                channel="desktop", metadata={"date": day},
            )
            run_id = int(run["id"])
            from brain.graph_memory import add_fact
            shared_parts = []
            if user_text:
                shared_parts.append(f"主人留下：{user_text}")
            if lianxin_text:
                shared_parts.append(f"莲心留下：{lianxin_text}")
            compact = " ".join("；".join(shared_parts).split())[:700]
            fact_id = add_fact(
                f"时间胶囊 {day}：{compact}", "events", source="time_capsule",
                source_channel="desktop", occurred_at=f"{day} 23:59:00",
            )
            self.db.link_memory_fact(day, fact_id)
            workflow.finish_run(
                run_id, status="completed",
                result_summary=f"sealed capsule linked to memory fact {fact_id}",
            )
        except Exception as exc:
            if run_id:
                try:
                    from brain.workflow import get_workflow_store
                    get_workflow_store().finish_run(run_id, status="failed", error=str(exc))
                except Exception:
                    pass
        finally:
            with self._memory_linking_lock:
                self._memory_linking.discard(day)

    @pyqtSlot(str, str, str, result=str)
    def add_trace(self, day, author, content):
        result = self.db.add_trace(str(day), str(author), str(content))
        self.emit_state(str(day))
        self.emit_page_state("corridor")
        return self._json(result)

    @pyqtSlot(str, str, str, str, result=str)
    def add_collection(self, day, kind, title, uri):
        result = self.db.add_collection(str(day), str(kind), str(title), str(uri))
        self.emit_state(str(day))
        self.emit_page_state("corridor")
        return self._json(result)

    @pyqtSlot(str, result=str)
    def choose_collection_file(self, kind):
        kind = str(kind)
        filters = {
            "photo": "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)",
            "music": "音频文件 (*.mp3 *.wav *.flac *.m4a *.ogg)",
            "file": "所有文件 (*)",
        }
        path, _ = QFileDialog.getOpenFileName(
            None, "选择要一起收藏的内容", "", filters.get(kind, "所有文件 (*)")
        )
        if not path:
            return ""
        return str(Path(path).resolve())

    @staticmethod
    def _default_media_root() -> Path:
        return get_user_data_dir() / "time_capsule_media"

    @classmethod
    def _media_root(cls) -> Path:
        configured = str(get_diary_config().get("media_directory") or "").strip()
        root = Path(configured).expanduser() if configured else cls._default_media_root()
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    @staticmethod
    def _safe_filename(filename: str, fallback: str = "attachment") -> str:
        name = Path(str(filename or fallback)).name
        name = re.sub(r'[^0-9A-Za-z._()\-\u4e00-\u9fff]+', "_", name).strip("._")
        return name[:120] or fallback

    def _store_collection_file(self, day: str, kind: str, source: Path, *, title: str = "") -> dict:
        if kind == "photo" and source.suffix.lower() not in {
            ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"
        }:
            raise ValueError("记忆相簿只支持图片文件")
        if not source.is_file():
            raise FileNotFoundError("所选附件已不存在")
        if source.stat().st_size > 25 * 1024 * 1024:
            raise ValueError("单个附件暂时限制为 25 MB")
        source_image = QImage(str(source)) if kind == "photo" else None
        if kind == "photo" and source_image.isNull():
            raise ValueError("所选文件不是可读取的图片")
        folder = self._media_root() / str(day)
        folder.mkdir(parents=True, exist_ok=True)
        filename = self._safe_filename(source.name)
        target = folder / f"{uuid.uuid4().hex[:10]}_{filename}"
        shutil.copy2(str(source), str(target))
        metadata = {"managed_copy": True, "original_name": source.name}
        if kind == "photo":
            thumbnail_dir = folder / ".thumbs"
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail = thumbnail_dir / f"{target.stem}.jpg"
            preview = source_image.scaled(
                480, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            if preview.save(str(thumbnail), "JPG", 82):
                metadata["thumbnail_uri"] = str(thumbnail)
        result = self.db.add_collection(
            str(day), str(kind), title or source.stem or filename, str(target),
            metadata=metadata,
        )
        return result

    @pyqtSlot(str, result=str)
    def import_photos(self, day):
        paths, _ = QFileDialog.getOpenFileNames(
            None, "把难忘时刻放进记忆相簿", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        if not paths:
            return self._json({"ok": False, "cancelled": True})
        imported = 0
        errors = []
        for path in paths:
            try:
                self._store_collection_file(str(day), "photo", Path(path))
                imported += 1
            except (OSError, ValueError) as exc:
                errors.append(f"{Path(path).name}: {exc}")
        if imported:
            self.emit_state(str(day))
            self.emit_page_state("corridor")
        return self._json({
            "ok": imported > 0,
            "count": imported,
            "errors": errors,
            "error": "；".join(errors[:3]) if not imported else "",
        })

    @pyqtSlot(str, str, result=str)
    def import_collection_file(self, day, kind):
        """从系统选择附件并复制到莲心自己的媒体库，避免源文件移动后失效。"""
        kind = str(kind)
        filters = {
            "photo": "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
            "music": "音频文件 (*.mp3 *.wav *.flac *.m4a *.ogg)",
            "file": "所有文件 (*)",
        }
        path, _ = QFileDialog.getOpenFileName(
            None, "选择要一起收藏的内容", "", filters.get(kind, "所有文件 (*)")
        )
        if not path:
            return self._json({"ok": False, "cancelled": True})
        try:
            result = self._store_collection_file(str(day), kind, Path(path))
            self.emit_state(str(day))
            self.emit_page_state("corridor")
            return self._json({"ok": True, "day": result})
        except (OSError, ValueError) as exc:
            return self._json({"ok": False, "error": str(exc)})

    @pyqtSlot(str, str, str, result=str)
    def import_collection_path(self, day, kind, path):
        """兼容 Qt WebEngine 拖入文件时提供的本地路径。"""
        try:
            result = self._store_collection_file(str(day), str(kind), Path(str(path)))
            self.emit_state(str(day))
            self.emit_page_state("corridor")
            return self._json({"ok": True, "day": result})
        except (OSError, ValueError) as exc:
            return self._json({"ok": False, "error": str(exc)})

    @pyqtSlot(str, str, str, str, result=str)
    def import_collection_data(self, day, kind, filename, data_url):
        """保存网页拖入的附件；无法暴露本地路径时使用 data URL 安全落盘。"""
        try:
            if str(kind) != "photo":
                raise ValueError("记忆相簿只接收图片")
            header, encoded = str(data_url).split(",", 1)
            if ";base64" not in header:
                raise ValueError("附件格式不受支持")
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > 25 * 1024 * 1024:
                raise ValueError("单个附件暂时限制为 25 MB")
            folder = self._media_root() / str(day)
            folder.mkdir(parents=True, exist_ok=True)
            safe_name = self._safe_filename(str(filename))
            target = folder / f"{uuid.uuid4().hex[:10]}_{safe_name}"
            target.write_bytes(raw)
            metadata = {"managed_copy": True, "original_name": safe_name}
            thumbnail_dir = folder / ".thumbs"
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            thumbnail = thumbnail_dir / f"{target.stem}.jpg"
            image = QImage(str(target))
            if image.isNull():
                target.unlink(missing_ok=True)
                raise ValueError("拖入的文件不是可读取的图片")
            preview = image.scaled(480, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if preview.save(str(thumbnail), "JPG", 82):
                metadata["thumbnail_uri"] = str(thumbnail)
            result = self.db.add_collection(
                str(day), "photo", Path(safe_name).stem, str(target),
                metadata=metadata,
            )
            self.emit_state(str(day))
            self.emit_page_state("corridor")
            return self._json({"ok": True, "day": result})
        except (ValueError, OSError, binascii.Error) as exc:
            return self._json({"ok": False, "error": str(exc)})

    @pyqtSlot(str, result=str)
    def open_collection(self, uri):
        path = Path(str(uri or ""))
        if not path.is_file():
            return self._json({"ok": False, "error": "附件文件已不存在"})
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return self._json({"ok": bool(opened)})

    @pyqtSlot(int, result=str)
    def toggle_collection_favorite(self, collection_id):
        self.db.toggle_collection_favorite(int(collection_id))
        self.emit_state()
        self.emit_page_state("corridor")
        return self._json({"ok": True})

    @pyqtSlot(str, result=str)
    def add_tree_note(self, content):
        note_id = self.db.add_tree_note("user", str(content))
        self.emit_page_state("tree")
        if note_id:
            self._start_tree_reply(note_id)
        return self._json({"ok": bool(note_id), "id": note_id})

    @pyqtSlot(int, result=str)
    def request_tree_reply(self, note_id):
        note = self.db.get_tree_note(int(note_id))
        if not note:
            return self._json({"ok": False, "error": "纸条已经找不到了"})
        if note.get("reply"):
            return self._json({"ok": True, "pending": False, "reply": note["reply"]})
        self._start_tree_reply(int(note_id))
        return self._json({"ok": True, "pending": True})

    def _start_tree_reply(self, note_id: int) -> None:
        with self._tree_reply_lock:
            if note_id in self._tree_reply_running:
                return
            self._tree_reply_running.add(note_id)
        Thread(
            target=self._generate_tree_reply,
            args=(note_id,),
            name=f"capsule-tree-reply-{note_id}",
            daemon=True,
        ).start()

    def _generate_tree_reply(self, note_id: int) -> None:
        result = {"ok": False, "error": "莲心暂时没有写完回应，可以稍后重试。"}
        try:
            note = self.db.get_tree_note(note_id)
            if not note or note.get("author") != "user":
                result = {"ok": False, "error": "纸条已经找不到了。"}
            elif note.get("reply"):
                result = {"ok": True, "reply": note["reply"]}
            else:
                from brain.agent import AgentCore
                from brain.persona.runtime import active_assistant_name, capture_persona_snapshot
                persona = capture_persona_snapshot()
                assistant_name = active_assistant_name(persona)
                prompt = (
                    f"你是{assistant_name}。主人把下面这段话放进了只属于你们的树洞。\n"
                    "请写一段温柔、克制、真诚的回应，像写在纸条背面的短笺。"
                    "不要分析、说教、复述规则或使用标题，控制在80到220个中文字符。\n\n"
                    f"纸条：{str(note.get('content', ''))[:1200]}"
                )
                response = AgentCore()._call_api_with_retry([{"role": "user", "content": prompt}])
                text = str(response.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("empty tree reply")
                reply_id = self.db.add_tree_note("lianxin", text[:800], echo_of=note_id)
                updated = self.db.get_tree_note(note_id)
                result = {"ok": bool(reply_id), "reply": updated.get("reply")}
                self.emit_page_state("tree")
        except Exception as exc:
            result = {"ok": False, "error": f"莲心暂时没有写完回应：{exc}"}
        finally:
            with self._tree_reply_lock:
                self._tree_reply_running.discard(note_id)
            try:
                self.tree_reply_ready.emit(note_id, self._json(result))
            except RuntimeError:
                pass

    @pyqtSlot(int, result=str)
    def toggle_tree_favorite(self, note_id):
        self.db.toggle_tree_favorite(int(note_id))
        self.emit_page_state("tree")
        return self._json({"ok": True})

    @pyqtSlot(int, result=str)
    def toggle_tree_archive(self, note_id):
        result = self.db.toggle_tree_archive(int(note_id))
        self.emit_page_state("tree")
        return self._json({"ok": bool(result), "note": result})

    @pyqtSlot(str, result=str)
    def search(self, query):
        return self._json(self.db.search(str(query)))

    @pyqtSlot(result=str)
    def get_settings(self):
        try:
            payload = get_diary_config()
            payload["media_directory"] = str(self._media_root())
            payload["default_media_directory"] = str(self._default_media_root().resolve())
            return self._json({"ok": True, **payload})
        except Exception as exc:
            return self._json({
                "ok": False,
                "error": f"设置读取失败：{exc}",
                "media_directory": str(self._default_media_root()),
                "default_media_directory": str(self._default_media_root()),
            })

    @pyqtSlot(result=str)
    def choose_media_directory(self):
        try:
            selected = QFileDialog.getExistingDirectory(None, "选择时间胶囊附件保存位置", str(self._media_root()))
            return str(Path(selected).resolve()) if selected else ""
        except Exception:
            return ""

    @pyqtSlot(str, result=str)
    def open_media_directory(self, path):
        try:
            target = Path(str(path or "")).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))
            return self._json({"ok": bool(opened)})
        except Exception as exc:
            return self._json({"ok": False, "error": f"无法打开附件目录：{exc}"})

    @pyqtSlot(result=str)
    def get_default_media_directory(self):
        return str(self._default_media_root().resolve())

    @pyqtSlot(bool, str, int, str, str, int, bool, bool, result=str)
    def save_settings(self, scheduled_enabled, scheduled_time, max_messages, direction,
                      media_directory, timeline_page_size, animations_enabled, low_power_mode):
        payload = get_diary_config()
        raw_media_directory = str(media_directory or "").strip()
        try:
            media_root = Path(raw_media_directory).expanduser() if raw_media_directory else self._default_media_root()
            media_root.mkdir(parents=True, exist_ok=True)
            media_root = media_root.resolve()
        except OSError as exc:
            return self._json({"ok": False, "error": f"附件目录不可用：{exc}"})
        try:
            payload.update({
                "scheduled_enabled": bool(scheduled_enabled),
                "scheduled_time": str(scheduled_time or "23:55"),
                "max_messages": max(1, min(200, int(max_messages))),
                "direction": "earliest" if direction == "earliest" else "latest",
                "media_directory": str(media_root),
                "timeline_page_size": max(5, min(50, int(timeline_page_size))),
                "animations_enabled": bool(animations_enabled),
                "low_power_mode": bool(low_power_mode),
            })
            save_diary_config(payload)
            self.settings_changed.emit()
            return self._json({"ok": True, **payload})
        except Exception as exc:
            return self._json({"ok": False, "error": f"设置保存失败：{exc}"})

    @pyqtSlot(str, result=str)
    def visit_diary(self, source_date):
        day = self.db.get_day(str(source_date))
        if not day:
            return self._json({"ok": False})
        self.db.record_visit(0, str(source_date))
        return self._json({"ok": True, "date": str(source_date)})

    @pyqtSlot(str, str, result=str)
    def invite_lianxin(self, source_date, author="all"):
        source_date = str(source_date or "")
        author = str(author or "all")
        author = author if author in {"user", "lianxin"} else "all"
        if not source_date:
            return self._json({"ok": False, "error": "请先打开一篇想和莲心一起看的日记。"})
        day = self.db.get_day(source_date)
        selected_content = (
            day.get("user_content", "") if author == "user"
            else day.get("lianxin_content", "") if author == "lianxin"
            else day.get("user_content", "") or day.get("lianxin_content", "")
        )
        if not str(selected_content or "").strip():
            return self._json({"ok": False, "error": "这篇日记目前还没有可以阅读的内容。"})
        with self._companion_lock:
            if self._companion_running:
                active_date, active_author = self._companion_source
                return self._json({
                    "ok": True, "pending": True,
                    "date": active_date, "author": active_author,
                })
            self._companion_running = True
            self._companion_source = (source_date, author)
        Thread(
            target=self._prepare_companion_memory,
            args=(source_date, author),
            name="capsule-companion",
            daemon=True,
        ).start()
        return self._json({
            "ok": True, "pending": True, "date": source_date, "author": author,
        })

    def _prepare_companion_memory(self, source_date: str, author: str = "all") -> None:
        """用已有 RAG 找相关回忆；不调用聊天模型，不增加生成 Token。"""
        try:
            day = self.db.get_day(source_date) if source_date else {}
            user_content = str(day.get("user_content") or "").strip()
            lianxin_content = str(day.get("lianxin_content") or "").strip()
            if author == "user":
                content = user_content
                author_label = f"{get_user_name()}的日记"
            elif author == "lianxin":
                content = lianxin_content
                author_label = "莲心的日记"
            else:
                parts = []
                if user_content:
                    parts.append(f"{get_user_name()}：{user_content}")
                if lianxin_content:
                    parts.append(f"莲心：{lianxin_content}")
                content = "\n\n".join(parts)
                author_label = "共同书页"
            if not content:
                message = "这一页还没有写满。不过我愿意陪你慢慢看，等它以后长成一段回忆。"
            else:
                related = []
                try:
                    from brain.memory_rag import search_similar
                    related = search_similar(
                        content[:600], top_k=3, threshold=0.28,
                        track_access=False, hybrid=True,
                    )
                except Exception:
                    related = []
                memory_text = ""
                for _, memory in related:
                    candidate = " ".join(str(memory.get("content", "")).split())
                    if candidate and source_date not in candidate:
                        memory_text = candidate[:120]
                        break
                day_excerpt = " ".join(content.split())[:100]
                if memory_text:
                    message = (
                        f"陪你翻到这一页时，我又想起了：{memory_text}"
                        f"。它和这一天的「{day_excerpt}」像是隔着时间轻轻照应。"
                    )
                else:
                    message = (
                        f"我记得这一页里的「{day_excerpt}」。"
                        "当时看起来很普通的片刻，现在再看，已经有了回忆的光。"
                    )
            try:
                self.companion_ready.emit(self._json({
                    "message": message,
                    "date": source_date,
                    "title": self.db._memory_title(source_date, content),
                    "author": author,
                    "author_label": author_label,
                }))
            except RuntimeError:
                # 窗口可能在后台检索完成前已经关闭。
                pass
        finally:
            with self._companion_lock:
                self._companion_running = False
                self._companion_source = ("", "all")

    @pyqtSlot()
    def request_close(self):
        self.close_requested.emit()

    @pyqtSlot()
    def request_minimize(self):
        self.minimize_requested.emit()

    @pyqtSlot()
    def request_fullscreen(self):
        self.fullscreen_requested.emit()
