"""구글 광고 캠페인 효과 측정 및 비교 분석 대시보드.

실행: streamlit run app.py
"""
import streamlit as st

from core.config import CLIENTS, COMPANIES, SLOTS
from views import brand_tab, dslasso_tab, overview, platform_tab, trends_tab
from views.common import apply_preset, connect_all, init_state

st.set_page_config(page_title="캠페인 효과 대시보드", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.st-key-topbar {position: sticky; top: 3.75rem; z-index: 990; background: #ffffff;
  border-bottom: 1px solid rgba(128,128,128,.25); padding: .4rem 0 .6rem 0;}
.st-key-topbar [data-testid="stVerticalBlock"] {gap: .35rem;}
.slot-chip {font-size: 12px; padding: 2px 8px; border-radius: 10px; margin: 0 6px 6px 0; display: inline-block;}
</style>
""", unsafe_allow_html=True)

init_state()
ss = st.session_state


# ── 왼쪽 사이드바: 고객사 + 캠페인 URL 3개 ─────────────────────────────────
def sidebar():
    with st.sidebar:
        st.markdown("### 캠페인 설정")
        # 기본 고객사가 미리 선택된 상태로 시작
        ss.client = st.selectbox("고객사", CLIENTS, key="client_sel",
                                 on_change=lambda: apply_preset(ss.client_sel))  # 고객사별 경쟁사·URL 자동 매핑
        ss.competitor = st.selectbox("경쟁사", [c for c in COMPANIES if c != ss.client], key="competitor_sel")
        st.caption("분석할 URL을 입력하세요")
        for s in SLOTS:
            ss.urls[s["key"]] = st.text_input(s["label"], key=f"url_{s['key']}",
                                              placeholder="YouTube 또는 Instagram URL")
        clicked = st.button("연동", type="primary", width="stretch")
        if clicked or not ss.get("connected"):
            with st.spinner("링크 연동 중…"):
                connect_all(force=clicked)
        chips = []
        for s in SLOTS:
            m = ss.slots.get(s["key"])
            if m is None:
                chips.append(f"<span class='slot-chip' style='background:#eee;color:#555'>{s['role']}: 미등록</span>")
            elif "error" in m:
                chips.append(f"<span class='slot-chip' style='background:#fde2e1;color:#8a1c1b'>✕ {s['role']}: 연동 실패</span>")
            else:
                chips.append(f"<span class='slot-chip' style='background:#dff3e8;color:#14532d'>✓ {s['role']}: {m['platform']}</span>")
        st.markdown("".join(chips), unsafe_allow_html=True)


# ── 상단 바 (고정): 타이틀 + 분석 기간 ─────────────────────────────────────
def top_bar():
    with st.container(key="topbar"):
        c0, c1 = st.columns([5, 2])
        c0.markdown("### 📊 구글 광고 캠페인 효과 측정·비교")
        period = c1.date_input("분석 기간", ss.period, key="period_sel")
        if isinstance(period, (tuple, list)) and len(period) == 2:
            ss.period = tuple(period)


sidebar()
top_bar()
# 탭 대신 위에서 아래로 이어지는 섹션
sections = [trends_tab, overview, brand_tab, dslasso_tab]
if (ss.urls.get("other") or "").strip():  # 타 매체 URL이 없는 고객사는 타 플랫폼 비교를 숨김
    sections.insert(2, platform_tab)
for i, section in enumerate(sections):
    if i:
        st.divider()
    section.render()
