"""data/ 디렉터리의 JSON 파일 기반 간이 저장소 (노트, 실행 이력, 리포트, 공유 링크)."""
import json
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_lock = threading.Lock()


def _path(name: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR / f"{name}.json"


def load(name: str, default=None):
    p = _path(name)
    if not p.exists():
        return {} if default is None else default
    with _lock:
        return json.loads(p.read_text(encoding="utf-8"))


def save(name: str, obj) -> None:
    with _lock:
        _path(name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def append(name: str, record: dict) -> None:
    rows = load(name, default=[])
    rows.append(record)
    save(name, rows)
