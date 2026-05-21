import json
from pathlib import Path
from utils.paths import get_user_data_dir

_NOTE_FILE = get_user_data_dir() / "note.json"

def read_note() -> str:
    if _NOTE_FILE.exists():
        with open(_NOTE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("content", "")
    return ""

def write_note(content: str):
    _NOTE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_NOTE_FILE, "w", encoding="utf-8") as f:
        json.dump({"content": content}, f, ensure_ascii=False, indent=2)