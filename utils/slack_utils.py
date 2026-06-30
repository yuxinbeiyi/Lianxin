"""
slack_utils.py：莲心摸鱼-本地系统数据采集工具
"""
import os
import random
import shutil
import platform
from datetime import datetime
from typing import Optional


# ── 翻相册：扫描图片文件夹 ──────────────────────────────────

def get_random_photo_path(folder: str = None) -> Optional[str]:
    """从文件夹中随机获取一张图片路径"""
    if not folder:
        folder = os.path.join(os.path.expanduser("~"), "Pictures")
    if not os.path.isdir(folder):
        return None

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
    images = []
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in image_exts:
                images.append(os.path.join(root, f))
        if len(images) > 500:
            break

    if not images:
        return None
    return random.choice(images)


def get_photo_info(path: str) -> dict:
    """获取图片信息"""
    name = os.path.basename(path)
    folder = os.path.dirname(path)
    size = os.path.getsize(path)
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return {
        "name": name,
        "folder": folder,
        "size_kb": round(size / 1024, 1),
        "modified": mtime.strftime("%Y-%m-%d %H:%M"),
    }


# ── 读本地文件：txt/docx/pdf ────────────────────────────────

def get_random_document(scan_dirs: list = None) -> Optional[dict]:
    """从常见目录中随机获取一个文档文件"""
    if scan_dirs is None:
        scan_dirs = [
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Documents"),
        ]

    doc_exts = {".txt", ".md", ".docx", ".pdf"}
    docs = []
    for d in scan_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if os.path.splitext(f)[1].lower() in doc_exts:
                    docs.append(os.path.join(root, f))
            if len(docs) > 300:
                break

    if not docs:
        return None

    path = random.choice(docs)
    ext = os.path.splitext(path)[1].lower()
    snippet = _read_file_snippet(path, ext)
    return {
        "name": os.path.basename(path),
        "folder": os.path.dirname(path),
        "ext": ext,
        "snippet": snippet,
        "size_kb": round(os.path.getsize(path) / 1024, 1),
    }


def _read_file_snippet(path: str, ext: str, max_chars: int = 500) -> str:
    """读取文件的前若干字符"""
    try:
        if ext == ".txt" or ext == ".md":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(max_chars)
        elif ext == ".docx":
            try:
                from docx import Document
                doc = Document(path)
                text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                return text[:max_chars]
            except ImportError:
                return "（需要安装 python-docx 库才能读取 .docx 文件）"
            except Exception:
                return "（无法读取此 docx 文件）"
        elif ext == ".pdf":
            try:
                import PyPDF2  # type: ignore
                reader = PyPDF2.PdfReader(path)
                text = ""
                for page in reader.pages[:3]:
                    text += page.extract_text() or ""
                return text[:max_chars]
            except ImportError:
                return "（需要安装 PyPDF2 库才能读取 .pdf 文件）"
            except Exception:
                return "（无法读取此 PDF 文件）"
    except Exception:
        return "（文件读取失败）"


# ── 浏览器历史记录 ──────────────────────────────────────────

def get_browser_history_snippet(max_entries: int = 10) -> Optional[str]:
    """从浏览器历史记录中获取最近访问的网址"""
    history_paths = _find_browser_history_paths()
    if not history_paths:
        return None

    entries = []
    for browser, path in history_paths.items():
        if not os.path.exists(path):
            continue
        try:
            import sqlite3
            import tempfile
            # 复制数据库以避免锁定问题
            tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
            tmp.close()
            shutil.copy2(path, tmp.name)
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT url, title, last_visit_time FROM urls "
                "ORDER BY last_visit_time DESC LIMIT ?",
                (max_entries,)
            )
            rows = cursor.fetchall()
            conn.close()
            os.unlink(tmp.name)
            for url, title, ts in rows:
                entries.append(f"[{browser}] {title or '无标题'} - {url}")
        except Exception:
            continue

    if not entries:
        return None
    return "\n".join(entries[:max_entries])


def _find_browser_history_paths() -> dict:
    """查找常见浏览器的历史记录路径"""
    paths = {}
    home = os.path.expanduser("~")
    if platform.system() == "Windows":
        paths["Chrome"] = os.path.join(
            home, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "History"
        )
        paths["Edge"] = os.path.join(
            home, "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "History"
        )
    return paths


# ── 查看CPU/磁盘 ────────────────────────────────────────────

def get_system_status() -> dict:
    """获取CPU和磁盘状态"""
    info = {"cpu_percent": None, "disk_info": ""}

    try:
        import psutil
        info["cpu_percent"] = psutil.cpu_percent(interval=1)
        info["memory_percent"] = psutil.virtual_memory().percent

        processes = []
        for proc in psutil.process_iter(["name", "cpu_percent"]):
            try:
                p = proc.info
                if p["cpu_percent"] and p["cpu_percent"] > 5:
                    processes.append(f"{p['name']} (CPU {p['cpu_percent']:.1f}%)")
            except Exception:
                pass
        info["top_processes"] = processes[:5]
    except ImportError:
        info["cpu_percent"] = "（需要 psutil 库）"
        info["memory_percent"] = "（需要 psutil 库）"

    # 磁盘信息
    try:
        if platform.system() == "Windows":
            drives = []
            for letter in "CDEFGH":
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    usage = shutil.disk_usage(drive)
                    free_gb = usage.free / (1024 ** 3)
                    total_gb = usage.total / (1024 ** 3)
                    if free_gb < 10:
                        drives.append(f"{drive} 剩余 {free_gb:.1f}GB / 共 {total_gb:.1f}GB ⚠️")
            if drives:
                info["disk_info"] = "\n".join(drives)
            else:
                info["disk_info"] = "磁盘空间充足"
        else:
            usage = shutil.disk_usage("/")
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            info["disk_info"] = f"剩余 {free_gb:.1f}GB / 共 {total_gb:.1f}GB"
    except Exception:
        info["disk_info"] = "（无法获取磁盘信息）"

    return info


# ── 查看回收站 ──────────────────────────────────────────────

def get_recycle_bin_info() -> Optional[str]:
    """获取回收站信息"""
    if platform.system() != "Windows":
        return "（回收站读取仅支持 Windows）"

    try:
        import winshell  # type: ignore
        items = list(winshell.recycle_bin())
        if not items:
            return "回收站是空的，很干净哦～"

        total_size = sum(item.size() for item in items if hasattr(item, 'size'))
        files = []
        for item in items[:10]:
            name = item.original_filename() if hasattr(item, 'original_filename') else str(item)
            files.append(name)
        info = f"回收站里有 {len(items)} 个文件"
        if total_size > 0:
            info += f"（约 {total_size / (1024**2):.1f} MB）"
        if files:
            info += f"\n最近删除的：{', '.join(files[:5])}"
        return info
    except ImportError:
        return "（需要安装 winshell 库才能读取回收站，pip install winshell）"
    except Exception as e:
        return "（无法读取回收站）"