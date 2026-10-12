"""디스크 캐시 (data/cache/*.pkl) — 서버를 재시작해도 유지되는 링크·댓글·썸네일·분석 결과 캐시.

예외·빈 결과는 캐시하지 않는다. refresh=True면 새로 받아 덮어쓰되, 실패하면 이전 값을 그대로 쓴다.
"""
from __future__ import annotations

import hashlib
import pickle
import time
from typing import Any, Callable

from .store import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
DAY = 24 * 3600


def _path(ns: str, key: Any):
    h = hashlib.sha1(repr(key).encode()).hexdigest()[:20]
    return CACHE_DIR / f"{ns}_{h}.pkl"


def get(ns: str, key: Any, max_age: float | None = None):
    p = _path(ns, key)
    if not p.exists() or (max_age is not None and time.time() - p.stat().st_mtime > max_age):
        return None
    try:
        return pickle.loads(p.read_bytes())
    except Exception:  # 손상된 캐시 파일 → 없는 것으로 취급
        return None


def put(ns: str, key: Any, value) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(ns, key).with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(value))
    tmp.replace(_path(ns, key))


def cached(ns: str, key: Any, fn: Callable[[], Any], max_age: float | None = None, refresh: bool = False):
    if not refresh:
        hit = get(ns, key, max_age)
        if hit is not None:
            return hit
    try:
        value = fn()
    except Exception:
        stale = get(ns, key)  # 새로 받기 실패 시 만료됐더라도 이전 값을 유지 (없으면 오류 그대로)
        if stale is not None:
            return stale
        raise
    if value is not None and not getattr(value, "empty", False):  # 빈 결과(예: 댓글 0개)는 캐시하지 않음
        put(ns, key, value)
    return value
