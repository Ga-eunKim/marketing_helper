"""네트워크·연산 결과의 디스크 캐시 래퍼 (앱과 scripts/warm_cache.py 공용)."""
from __future__ import annotations

import pandas as pd
import requests

from . import cache, dslasso
from . import comments as cm
from . import url_connector as uc

LINK_TTL = cache.DAY          # 링크 메타데이터·지표
COMMENT_TTL = cache.DAY       # 댓글
IMAGE_TTL = 7 * cache.DAY     # 썸네일


def link(url: str, refresh: bool = False) -> dict:
    key = uc.parse_url(url)  # 같은 영상/게시물이면 URL 형태가 달라도 같은 캐시
    return cache.cached("link", key, lambda: uc.fetch(url), LINK_TTL, refresh)


def comments(video_id: str, limit: int, sort: str, refresh: bool = False) -> pd.DataFrame:
    return cache.cached("comments", (video_id, limit, sort),
                        lambda: cm.fetch_youtube_comments(video_id, limit=limit, sort=sort), COMMENT_TTL, refresh)


def comments_if_cached(video_id: str, limit: int, sort: str) -> pd.DataFrame | None:
    return cache.get("comments", (video_id, limit, sort), COMMENT_TTL)


def image(url: str) -> bytes | None:
    def _get():
        try:
            r = requests.get(url, headers=uc.HEADERS, timeout=10)
            return r.content if r.ok else None
        except requests.RequestException:
            return None
    return cache.cached("image", url, _get, IMAGE_TTL)


def dsl_run(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str], refresh: bool = False) -> dict:
    """동일 입력(버전 해시)이면 저장된 결과 재사용. refresh=True면 재실행 후 덮어씀."""
    version = dslasso.input_hash(df[[target] + controls + candidates], target, controls, candidates)
    return cache.cached("dsl", version, lambda: dslasso.run(df, target, controls, candidates), refresh=refresh)


def dsl_if_cached(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str]) -> dict | None:
    version = dslasso.input_hash(df[[target] + controls + candidates], target, controls, candidates)
    return cache.get("dsl", version)
