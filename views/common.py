"""탭 간 공유 상태 헬퍼."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import comments as cm
from core import url_connector as uc
from core.config import DEFAULT_URLS, FX_TO_KRW, SLOTS


def init_state():
    ss = st.session_state
    ss.setdefault("urls", dict(DEFAULT_URLS))
    ss.setdefault("slots", {})          # key -> meta dict | {"error":..., "fix":...}
    ss.setdefault("ads", {})            # key -> 표준화된 Google Ads DataFrame
    ss.setdefault("ads_log", {})        # key -> 업로드 경고/출처
    ss.setdefault("comment_data", {})   # key -> 수집 댓글 DataFrame
    ss.setdefault("trends", None)       # (df, meta)
    ss.setdefault("dsl", None)
    ss.setdefault("report_parts", {})   # section_key -> {title, figs, tables, text}
    ss.setdefault("fx", dict(FX_TO_KRW))
    ss.setdefault("period", (date.today() - timedelta(days=180), date.today()))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_cached(url: str) -> dict:
    return uc.fetch(url)


@st.cache_data(ttl=3600, show_spinner=False)
def comments_cached(video_id: str, limit: int, sort: str) -> pd.DataFrame:
    return cm.fetch_youtube_comments(video_id, limit=limit, sort=sort)


def connect_all(force: bool = False):
    if force:
        fetch_cached.clear()
    ss = st.session_state
    main_brand, main_msg = None, None
    for s in SLOTS:
        url = (ss.urls.get(s["key"]) or "").strip()
        prev = ss.slots.get(s["key"]) or {}
        if not url:
            ss.slots[s["key"]] = None
            continue
        try:
            meta = dict(fetch_cached(url))
        except uc.ConnectorError as e:
            ss.slots[s["key"]] = {"error": e.cause, "fix": e.fix, "url": url}
            continue
        except Exception as e:  # 예상 못 한 네트워크/파싱 오류
            ss.slots[s["key"]] = {"error": f"{type(e).__name__}: {e}", "fix": "잠시 후 [연동]을 다시 눌러 재시도하세요.", "url": url}
            continue
        same = prev.get("id") == meta["id"]
        meta["campaign_name"] = prev.get("campaign_name") if same else (meta.get("title") or "")[:40]
        meta["start_date"] = prev.get("start_date") if same else meta.get("published")
        brand = uc.default_brand_keyword(meta)
        if meta["platform"] == "Instagram" and main_brand:
            brand = main_brand  # 동일 소재 타 매체: 고객사 브랜드 키워드 재사용
        msg = ", ".join(uc.default_message_keywords(meta))
        if s["key"] == "other" and main_msg:
            msg = main_msg  # 동일 소재 → 같은 핵심 메시지
        if s["key"] == "main":
            main_brand, main_msg = brand, msg
        meta["brand_kw"] = prev.get("brand_kw") if same else brand
        meta["msg_kw"] = prev.get("msg_kw") if same else msg
        ss.slots[s["key"]] = meta
    ss.connected = True


def connected_slots(platform: str | None = None) -> list[tuple[dict, dict]]:
    """[(slot_def, meta)] — 연동 성공한 슬롯만."""
    out = []
    for s in SLOTS:
        m = st.session_state.slots.get(s["key"])
        if m and "error" not in m and (platform is None or m["platform"] == platform):
            out.append((s, m))
    return out


def slot_name(s: dict, m: dict) -> str:
    return f"{s['role']} · {m.get('campaign_name') or m.get('title')}"


def put_report(key: str, title: str, figs=None, tables=None, text: str = ""):
    st.session_state.report_parts[key] = {"title": title, "figs": figs or [], "tables": tables or [], "text": text}


def kw_list(s: str) -> list[str]:
    return [k.strip() for k in (s or "").replace("\n", ",").split(",") if k.strip()]
