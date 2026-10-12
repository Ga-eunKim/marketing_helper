"""구글 광고 캠페인 효과 측정 및 비교 분석 대시보드.

실행: streamlit run app.py
"""
from datetime import datetime

import streamlit as st

from core import store
from core.config import DEFAULT_CLIENT, SLOTS, USERS
from core.report import NOTE_FIELDS
from views import brand_tab, dslasso_tab, overview, platform_tab, report_tab, trends_tab
from views.common import connect_all, init_state

st.set_page_config(page_title="캠페인 효과 대시보드", page_icon="📊", layout="wide")

st.markdown("""
<style>
.st-key-topbar {position: sticky; top: 3.75rem; z-index: 990; background: #ffffff;
  border-bottom: 1px solid rgba(128,128,128,.25); padding: .4rem 0 .6rem 0;}
.st-key-topbar [data-testid="stVerticalBlock"] {gap: .35rem;}
.st-key-katesnote {background: #fff4a8; color: #2b2b2b; border-radius: 4px; padding: 14px 14px 6px 14px;
  box-shadow: 0 3px 8px rgba(0,0,0,.15); position: sticky; top: 13rem;}
.st-key-katesnote p, .st-key-katesnote li, .st-key-katesnote label, .st-key-katesnote span {color: #2b2b2b !important;}
.st-key-katesnote h3 {margin-top: 0; color: #2b2b2b;}
.slot-chip {font-size: 12px; padding: 2px 8px; border-radius: 10px; margin-right: 6px; display: inline-block;}
</style>
""", unsafe_allow_html=True)

# ── 공유 링크(읽기 전용) 모드 ─────────────────────────────────────────────
share = st.query_params.get("share")
if share:
    report_tab.render_shared(share)
    st.stop()

init_state()
ss = st.session_state


# ── 상단 바 (고정) ────────────────────────────────────────────────────────
def top_bar():
    with st.container(key="topbar"):
        c0, c1, c2, c3 = st.columns([3, 1.2, 1.6, 2.2])
        c0.markdown("#### 📊 구글 광고 캠페인 효과 측정·비교")
        ss.user = c1.selectbox("사용자", list(USERS), key="user_sel")
        ss.role = USERS[ss.user]["role"]
        allowed = USERS[ss.user]["clients"]
        picked = c2.selectbox("고객사", allowed, index=None, placeholder="고객사 선택", key="client_sel")
        if picked is None:
            ss.client = DEFAULT_CLIENT if DEFAULT_CLIENT in allowed else allowed[0]
            c2.caption(f"미선택 → 기본 고객사 **{ss.client}** 자동 선택")
        else:
            ss.client = picked
        period = c3.date_input("분석 기간", ss.period, key="period_sel")
        if isinstance(period, (tuple, list)) and len(period) == 2:
            ss.period = tuple(period)

        u = st.columns([4, 4, 4, 1])
        for col, s in zip(u[:3], SLOTS):
            ss.urls[s["key"]] = col.text_input(s["label"], ss.urls.get(s["key"], ""), key=f"url_{s['key']}",
                                               placeholder="YouTube 또는 Instagram URL")
        u[3].markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
        clicked = u[3].button("연동", type="primary", width="stretch")
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


# ── Kate's note (왼쪽 2열) ─────────────────────────────────────────────────
def kates_note() -> dict:
    notes = store.load("notes", default={})
    note = notes.get(ss.client, {})
    author = note.get("_author")
    can_edit = ss.role == "관리자" or author in (None, ss.user)
    with st.container(key="katesnote"):
        st.markdown("### 📝 Kate's note")
        for f in NOTE_FIELDS:
            st.markdown(f"**{f}**  \n{note.get(f) or '—'}")
        st.caption(f"작성자 {author or '—'} · 수정 {note.get('_updated_at', '—')}")
    with st.expander("노트 수정", expanded=False):
        if not can_edit:
            st.info(f"노트 수정 권한 없음 (작성자 {author} 또는 관리자만 수정 가능)")
        else:
            with st.form("note_form"):
                vals = {f: st.text_area(f, note.get(f, ""), height=80) for f in NOTE_FIELDS}
                if st.form_submit_button("저장"):
                    notes[ss.client] = {**vals, "_author": author or ss.user,
                                        "_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
                    store.save("notes", notes)
                    st.rerun()
    return note


top_bar()
left, right = st.columns([2, 10], gap="medium")
with left:
    note = kates_note()
with right:
    tabs = st.tabs(["① 캠페인 개요", "② 검색 관심도", "③ DS-LASSO 증분 효과", "④ 플랫폼·어트리뷰션", "⑤ 브랜드·소비자", "⑥ 리포트"])
    with tabs[0]:
        overview.render()
    with tabs[1]:
        trends_tab.render()
    with tabs[2]:
        dslasso_tab.render()
    with tabs[3]:
        platform_tab.render()
    with tabs[4]:
        brand_tab.render()
    with tabs[5]:
        report_tab.render(note)
