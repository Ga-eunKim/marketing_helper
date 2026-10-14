"""구글 광고 캠페인 효과 측정 및 비교 분석 대시보드.

실행: streamlit run app.py
"""
import streamlit as st

from core import i18n
from core.config import SLOTS, clients, companies, page_type
from core.i18n import t
from views import brand_tab, dslasso_tab, game_page, overview, platform_tab, trends_tab
from views.common import apply_preset, connect_all, init_state

st.set_page_config(page_title="Campaign Performance Dashboard", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
.st-key-topbar {position: sticky; top: 3.75rem; z-index: 990; background: #ffffff;
  border-bottom: 1px solid rgba(128,128,128,.25); padding: .4rem 0 .6rem 0;}
.st-key-topbar [data-testid="stVerticalBlock"] {gap: .35rem;}
.slot-chip {font-size: 12px; padding: 2px 8px; border-radius: 10px; margin: 0 6px 6px 0; display: inline-block;}
</style>
""", unsafe_allow_html=True)

ss = st.session_state
# 언어: 상단 토글 값 (기본 ENG). 위젯보다 먼저 정해야 사이드바부터 같은 언어로 그려짐
ss.lang = {"KOR": "KO", "ENG": "EN"}.get(ss.get("lang_sel") or ss.get("lang_last") or "ENG", "EN")
init_state()


# ── 왼쪽 사이드바: 고객사 + 캠페인 URL 3개 ─────────────────────────────────
def sidebar():
    with st.sidebar:
        st.markdown(t("### 캠페인 설정", "### Campaign setup"))
        ss.client = st.selectbox(t("고객사", "Client"), clients(), key="client_sel",
                                 on_change=lambda: apply_preset(ss.client_sel))  # 고객사별 경쟁사·URL 자동 매핑
        ss.competitor = st.selectbox(t("경쟁사", "Competitor"), [c for c in companies() if c != ss.client],
                                     key="competitor_sel")
        st.caption(t("분석할 URL을 입력하세요", "Enter the URLs to analyze"))
        for s in SLOTS:
            ss.urls[s["key"]] = st.text_input(i18n.slot_label(s["key"]), key=f"url_{s['key']}",
                                              placeholder=t("YouTube 또는 Instagram URL", "YouTube or Instagram URL"))
        clicked = st.button(t("연동", "Connect"), type="primary", width="stretch")
        if clicked or not ss.get("connected"):
            with st.spinner(t("링크 연동 중…", "Connecting links…")):
                connect_all(force=clicked)
        chips = []
        for s in SLOTS:
            m, r = ss.slots.get(s["key"]), i18n.role(s["role"])
            if m is None:
                chips.append(f"<span class='slot-chip' style='background:#eee;color:#555'>{r}: {t('미등록', 'not set')}</span>")
            elif "error" in m:
                chips.append(f"<span class='slot-chip' style='background:#fde2e1;color:#8a1c1b'>✕ {r}: {t('연동 실패', 'failed')}</span>")
            else:
                chips.append(f"<span class='slot-chip' style='background:#dff3e8;color:#14532d'>✓ {r}: {m['platform']}</span>")
        st.markdown("".join(chips), unsafe_allow_html=True)


# ── 상단 바 (고정): 타이틀 + 분석 기간 + 언어 ──────────────────────────────
def top_bar():
    with st.container(key="topbar"):
        c0, c1, c2 = st.columns([5, 2, 1])
        c0.markdown(t("### 📊 구글 광고 캠페인 효과 측정·비교", "### 📊 Google Ads Campaign Effectiveness & Benchmarking"))
        if page_type(ss.client) != "game":  # 게임 페이지는 캠페인 기준 분석 기간을 자체로 사용
            period = c1.date_input(t("분석 기간", "Date range"), ss.period, key="period_sel")
            if isinstance(period, (tuple, list)) and len(period) == 2:
                ss.period = tuple(period)
        # 라벨이 언어에 따라 바뀌면 Streamlit이 새 위젯으로 보고 기본값(ENG)으로 되돌리므로 라벨은 고정
        choice = c2.segmented_control("Language / 언어", ["ENG", "KOR"], default="ENG", key="lang_sel")
        if choice:
            ss.lang_last = choice  # 선택된 버튼을 다시 눌러 해제돼도 언어 유지


sidebar()
top_bar()
# 탭 대신 위에서 아래로 이어지는 섹션
if page_type(ss.client) == "game":  # 게임 캠페인 전용 페이지 (clients.json의 page: "game") + 채널 비교·댓글 분석
    sections = [game_page, brand_tab]
    if (ss.urls.get("other") or "").strip():
        sections.insert(1, platform_tab)
else:
    sections = [trends_tab, overview, brand_tab, dslasso_tab]
    if (ss.urls.get("other") or "").strip():  # 타 매체 URL이 없는 고객사는 타 플랫폼 비교를 숨김
        sections.insert(2, platform_tab)
for i, section in enumerate(sections):
    if i:
        st.divider()
    section.render()
