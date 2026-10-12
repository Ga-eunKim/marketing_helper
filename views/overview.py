"""캠페인 링크 연동 결과: YouTube 캠페인 썸네일 + 고객사·경쟁사 지표 비교표."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import normalize as nz
from core.config import SLOTS
from views.common import connected_slots, image_bytes, slot_name

ROWS = ["매체", "계정", "시작일", "조회수", "좋아요", "댓글 수", "참여율"]


def _is_instagram(s: dict, m: dict | None) -> bool:
    if m and m.get("platform"):
        return m["platform"] == "Instagram"
    url = (st.session_state.urls.get(s["key"]) or "").lower()
    return "instagram.com" in url or "imginn.com" in url


def _thumb(s: dict, m: dict | None):
    if m is None:
        st.info(f"{s['label']}: URL 미등록")
        return
    if "error" in m:
        st.error(f"{s['label']} 연동 실패: {m['error']}")
        st.caption(f"🔧 수정 방법: {m['fix']}")
        return
    img = image_bytes(m["thumbnail"]) if m.get("thumbnail") else None
    if img:
        st.image(img, caption=slot_name(s, m), width="stretch")
    else:
        st.caption(f"{slot_name(s, m)} — 썸네일 없음")


def _fmt(metric: str, v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if metric == "참여율":
        return f"{v:.4%}"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}"
    return str(v)


def render():
    st.markdown("#### 캠페인 링크 연동 결과")
    shown = [(s, st.session_state.slots.get(s["key"])) for s in SLOTS]
    shown = [(s, m) for s, m in shown if not _is_instagram(s, m)]
    cols = st.columns(len(shown) or 1)
    for col, (s, m) in zip(cols, shown):
        with col:
            _thumb(s, m)

    yt = [(s, m) for s, m in connected_slots("YouTube") if m.get("kind") != "channel"]
    for s, m in connected_slots("YouTube"):
        if m.get("kind") == "channel":
            st.caption(f"ℹ️ {slot_name(s, m)}: 채널 URL이라 영상 단위 지표는 표에서 제외했습니다.")
    if yt:
        rows = {slot_name(s, m): nz.link_metrics_row(slot_name(s, m), m) for s, m in yt}
        df = pd.DataFrame({name: [_fmt(k, row[k]) for k in ROWS] for name, row in rows.items()}, index=ROWS)
        df.index.name = "지표"
        st.dataframe(df, width="stretch")
