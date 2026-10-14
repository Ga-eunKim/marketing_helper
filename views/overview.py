"""캠페인 링크 연동 결과: YouTube 캠페인 썸네일 + 고객사·경쟁사 지표 비교표."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import i18n
from core import normalize as nz
from core.config import SLOTS
from core.i18n import t
from views.common import connected_slots, image_bytes, slot_name

# (link_metrics_row 키, KOR 표기, ENG 표기)
ROWS = [
    ("매체", "매체", "Platform"),
    ("계정", "계정", "Channel"),
    ("시작일", "시작일", "Launch date"),
    ("조회수", "조회수", "Views"),
    ("좋아요", "좋아요", "Likes"),
    ("댓글 수", "댓글 수", "Comments"),
    ("참여율", "참여율", "Engagement rate"),
]


def _is_instagram(s: dict, m: dict | None) -> bool:
    if m and m.get("platform"):
        return m["platform"] == "Instagram"
    url = (st.session_state.urls.get(s["key"]) or "").lower()
    return "instagram.com" in url or "imginn.com" in url


def _thumb(s: dict, m: dict | None):
    label = i18n.slot_label(s["key"])
    if m is None:
        st.info(t(f"{label}: URL 미등록", f"{label}: no URL set"))
        return
    if "error" in m:
        st.error(t(f"{label} 연동 실패: {m['error']}", f"{label} failed to connect: {m['error']}"))
        st.caption(t(f"🔧 수정 방법: {m['fix']}", f"🔧 How to fix: {m['fix']}"))
        return
    img = image_bytes(m["thumbnail"]) if m.get("thumbnail") else None
    if img:
        st.image(img, caption=slot_name(s, m), width="stretch")
    else:
        st.caption(t(f"{slot_name(s, m)} — 썸네일 없음", f"{slot_name(s, m)} — no thumbnail"))


def _fmt(metric: str, v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if metric == "참여율":
        return f"{v:.4%}"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}"
    return str(v)


def render():
    st.markdown(t("#### 고객사와 경쟁사 캠페인 영상", "#### Client vs. Competitor Campaign Videos"))
    shown = [(s, st.session_state.slots.get(s["key"])) for s in SLOTS]
    shown = [(s, m) for s, m in shown if not _is_instagram(s, m)]
    cols = st.columns(len(shown) or 1)
    for col, (s, m) in zip(cols, shown):
        with col:
            _thumb(s, m)

    yt = [(s, m) for s, m in connected_slots("YouTube") if m.get("kind") != "channel"]
    for s, m in connected_slots("YouTube"):
        if m.get("kind") == "channel":
            st.caption(t(f"{slot_name(s, m)}는 채널 URL이라 표에서 뺐습니다.",
                         f"{slot_name(s, m)} is a channel URL, so it's left out of the table."))
    if yt:
        rows = {slot_name(s, m): nz.link_metrics_row(slot_name(s, m), m) for s, m in yt}
        df = pd.DataFrame({name: [_fmt(k, row[k]) for k, _, _ in ROWS] for name, row in rows.items()},
                          index=[t(ko, en) for _, ko, en in ROWS])
        df.index.name = t("지표", "Metric")
        st.dataframe(df, width="stretch")
