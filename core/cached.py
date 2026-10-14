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
    """화면 자동 표시용 — 오래된 수집 결과라도 보여준다 (새로 받기는 [댓글 새로 수집])."""
    return cache.get("comments", (video_id, limit, sort))


def comments_any(video_id: str, limit: int, sort: str) -> pd.DataFrame | None:
    """요청한 설정의 캐시가 없으면 같은 영상의 다른 저장분(예: CSV로 불러온 3,000개 설정)을 대신 사용."""
    for key in [(limit, sort), (3000, "최신순"), (500, "최신순"), (2000, "최신순"), (500, "인기순")]:
        hit = cache.get("comments", (video_id, *key))
        if hit is not None and len(hit):
            return hit
    return None


def image(url: str) -> bytes | None:
    def _get():
        r = requests.get(url, headers=uc.HEADERS, timeout=10)
        r.raise_for_status()  # 실패는 예외로 → 이전에 받은 썸네일 유지
        return r.content
    try:
        return cache.cached("image", url, _get, IMAGE_TTL)
    except requests.RequestException:
        return None


def dsl_run(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str], refresh: bool = False) -> dict:
    """동일 입력(버전 해시)이면 저장된 결과 재사용. refresh=True면 재실행 후 덮어씀."""
    version = dslasso.input_hash(df[[target] + controls + candidates], target, controls, candidates)
    return cache.cached("dsl2", version, lambda: dslasso.run(df, target, controls, candidates), refresh=refresh)


def dsl_if_cached(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str]) -> dict | None:
    version = dslasso.input_hash(df[[target] + controls + candidates], target, controls, candidates)
    return cache.get("dsl2", version)
