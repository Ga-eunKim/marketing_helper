"""Google Trends (pytrends) 래퍼: 디스크 캐시 + 429 백오프 재시도."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime

import pandas as pd
from pytrends.request import TrendReq

from .store import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
GEOS = {"대한민국": "KR", "전 세계": "", "미국": "US", "일본": "JP"}


class TrendsError(Exception):
    pass


def _cache_key(keywords, start, end, geo) -> str:
    raw = json.dumps([sorted(keywords), str(start), str(end), geo], ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _latest_cached(keywords: list[str], geo: str):
    """같은 키워드·지역으로 받아 둔 결과 중 가장 최근 것 (기간이 달라도)."""
    best = None
    for mp in CACHE_DIR.glob("trends_*.json"):
        meta = json.loads(mp.read_text(encoding="utf-8"))
        if sorted(meta["keywords"]) != sorted(keywords) or meta.get("geo") != (geo or "전 세계"):
            continue
        if best is None or meta["fetched_at"] > best[1]["fetched_at"]:
            best = (mp, meta)
    if best is None:
        return None
    mp, meta = best
    df = pd.read_csv(mp.with_suffix(".csv"), parse_dates=["date"], index_col="date")
    meta = dict(meta, from_cache=True, stale=True)
    return df, meta


def interest_over_time(keywords: list[str], start: date, end: date, geo: str = "KR",
                       use_cache: bool = True, retries: int = 3) -> tuple[pd.DataFrame, dict]:
    """키워드별 검색 관심도 (0–100 상대지수) 시계열과 메타정보 반환."""
    keywords = [k.strip() for k in keywords if k and k.strip()][:5]
    if not keywords:
        raise TrendsError("키워드가 없습니다. 최소 1개, 최대 5개를 입력하세요.")
    if start >= end:
        raise TrendsError("분석 기간의 시작일이 종료일보다 빨라야 합니다.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(keywords, start, end, geo)
    path = CACHE_DIR / f"trends_{key}.csv"
    meta_path = CACHE_DIR / f"trends_{key}.json"
    if use_cache and path.exists() and meta_path.exists():
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["from_cache"] = True
        return df, meta

    timeframe = f"{start:%Y-%m-%d} {end:%Y-%m-%d}"
    df, last = None, None
    for attempt in range(retries):
        try:
            py = TrendReq(hl="ko-KR", tz=540, timeout=(10, 25))
            py.build_payload(keywords, timeframe=timeframe, geo=geo)
            df = py.interest_over_time()
            break
        except Exception as e:
            last = e
            if "429" not in str(e):
                break  # 요청 한도 외 오류는 재시도해도 동일
            if attempt < retries - 1:
                time.sleep(4 * (attempt + 1))
    if df is None:
        stale = _latest_cached(keywords, geo)
        if stale is not None:  # 요청 실패 시 같은 키워드·지역의 마지막 결과로 대체
            return stale
        if "429" in str(last):
            raise TrendsError("Google Trends 요청 한도 초과(429). 1~2분 후 다시 시도하세요. (성공한 조회 결과는 캐시되어 재요청하지 않습니다)")
        raise TrendsError(f"Google Trends 조회 실패: {type(last).__name__}: {last}")
    if df.empty:
        raise TrendsError("해당 키워드·기간·지역에 대한 검색 데이터가 충분하지 않습니다 (검색량이 매우 적은 키워드일 수 있음).")

    partial = bool(df.get("isPartial", pd.Series(dtype=bool)).astype(bool).any())
    df = df.drop(columns=["isPartial"], errors="ignore")
    df.index.name = "date"
    step = (df.index[1] - df.index[0]).days if len(df) > 1 else 1
    meta = {
        "keywords": keywords,
        "geo": geo or "전 세계",
        "timeframe": timeframe,
        "granularity": {1: "일별", 7: "주별"}.get(step, "월별"),
        "partial_last": partial,
        "index_basis": "기간·지역 내 최대 검색량 = 100 기준 상대지수 (절대 검색량 아님, 키워드 간 동일 요청 내에서만 비교 가능)",
        "source": "Google Trends (pytrends)",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "from_cache": False,
    }
    df.to_csv(path)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return df, meta
