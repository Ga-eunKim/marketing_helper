"""① 캠페인 개요: 링크 연동 결과, 공통 지표 표준화, (YouTube 한정) Google Ads CSV."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import normalize as nz
from core.charts import SLOT_COLORS, style
from core.config import SLOTS
from views.common import connected_slots, put_report, slot_name

SAMPLE_ADS = Path(__file__).resolve().parent.parent / "sample_data" / "sample_google_ads.csv"


def _fmt(v, pct=False):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.2%}" if pct else f"{v:,.0f}"


def _slot_card(s: dict, m: dict | None):
    st.markdown(f"**{s['label']}**")
    if m is None:
        st.info("URL 미등록 — 상단 바에 링크를 입력하고 [연동]을 누르세요.")
        return
    if "error" in m:
        st.error(f"연동 실패: {m['error']}")
        st.caption(f"🔧 수정 방법: {m['fix']}")
        return
    k = s["key"]
    if m.get("thumbnail"):
        st.image(m["thumbnail"], width="stretch")
    st.markdown(f"`{m['platform']}` · {m.get('account') or '—'}  \n[{(m.get('title') or '')[:60]}]({m['url']})")
    c1, c2, c3 = st.columns(3)
    c1.metric("조회수", _fmt(m.get("views")))
    c2.metric("좋아요", _fmt(m.get("likes")))
    c3.metric("댓글 수", _fmt(m.get("comments")))
    m["campaign_name"] = st.text_input("캠페인명 *", m.get("campaign_name") or "", key=f"cn_{k}_{m['id']}")
    sd = pd.to_datetime(m.get("start_date")).date() if m.get("start_date") else None
    new_sd = st.date_input("캠페인 시작일 *", sd, key=f"sd_{k}_{m['id']}", help="기본값 = 게시일. 실제 광고 집행 시작일로 수정하세요.")
    m["start_date"] = new_sd.isoformat() if isinstance(new_sd, date) else None
    m["brand_kw"] = st.text_input("브랜드 검색 키워드 (Trends)", m.get("brand_kw") or "", key=f"bk_{k}_{m['id']}")
    m["msg_kw"] = st.text_input("핵심 광고 메시지 키워드 (쉼표 구분)", m.get("msg_kw") or "", key=f"mk_{k}_{m['id']}",
                                help="댓글 '광고 메시지 연상' 분석에 사용")
    if not m["campaign_name"] or not m["start_date"]:
        st.warning("필수 항목(캠페인명, 시작일)을 입력하세요.")
    st.caption(f"출처: {m['source']} · 수집 {m['fetched_at']}")
    for n in m.get("notes", []):
        st.caption(f"⚠️ {n}")


def _ads_section():
    st.subheader("Google Ads 성과 데이터 (YouTube 슬롯, 선택)")
    st.caption("노출·클릭·비용·전환은 광고주 계정 비공개 데이터라 링크로 수집할 수 없습니다. "
               "Google Ads 보고서(일별) CSV를 올리면 표준 지표로 변환됩니다. Instagram은 링크 수집 지표만 사용합니다.")
    yt = connected_slots("YouTube")
    if not yt:
        st.info("연동된 YouTube 슬롯이 없습니다.")
        return
    with st.expander("통화 환산 기준 (→ KRW)"):
        fx_df = pd.DataFrame({"통화": list(st.session_state.fx), "KRW 환산율": list(st.session_state.fx.values())})
        fx_df = st.data_editor(fx_df, num_rows="dynamic", key="fx_editor", hide_index=True)
        st.session_state.fx = {str(c).upper().strip(): float(v) for c, v in zip(fx_df["통화"], fx_df["KRW 환산율"])
                               if pd.notna(c) and pd.notna(v)}
    cols = st.columns(len(yt))
    for col, (s, m) in zip(cols, yt):
        k = s["key"]
        with col:
            st.markdown(f"**{slot_name(s, m)}**")
            up = st.file_uploader("Google Ads CSV", type=["csv"], key=f"ads_up_{k}")
            use_sample = st.button("샘플 데이터 사용 (가상)", key=f"ads_sample_{k}")
            raw, src = None, None
            if up is not None and st.session_state.ads_log.get(k, {}).get("file") != up.name + str(up.size):
                try:
                    raw = pd.read_csv(up, thousands=",")
                    src = f"업로드: {up.name}"
                except Exception as e:
                    st.error(f"CSV를 읽을 수 없습니다: {e}")
                    st.caption("🔧 UTF-8(또는 UTF-8 BOM) 인코딩, 쉼표 구분 CSV로 저장해 다시 올리세요.")
            if use_sample:
                raw, src = pd.read_csv(SAMPLE_ADS), "샘플 (가상 데이터)"
            if raw is not None:
                try:
                    new, warns = nz.normalize_ads_csv(raw, "YouTube", m.get("campaign_name"), st.session_state.fx)
                    before = len(st.session_state.ads.get(k, pd.DataFrame()))
                    merged = nz.merge_dedupe(st.session_state.ads.get(k), new)
                    st.session_state.ads[k] = merged
                    dup = before + len(new) - len(merged)
                    if dup:
                        warns.append(f"중복 {dup}행(같은 날짜·캠페인) → 최신 값으로 대체, 중복 집계 없음")
                    st.session_state.ads_log[k] = {"warnings": warns, "source": src,
                                                    "file": (up.name + str(up.size)) if up else "sample",
                                                    "at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}
                except ValueError as e:
                    st.error(str(e))
            df = st.session_state.ads.get(k)
            if df is not None and not df.empty:
                log = st.session_state.ads_log.get(k, {})
                for w in log.get("warnings", []):
                    st.caption(f"⚠️ {w}")
                agg = nz.ads_summary(df)
                a, b, c = st.columns(3)
                a.metric("노출", _fmt(agg["impressions"]))
                b.metric("클릭", _fmt(agg["clicks"]))
                c.metric("전환", _fmt(agg["conversions"]))
                a.metric("비용(KRW)", _fmt(agg["cost"]))
                b.metric("CVR", _fmt(agg["cvr"], pct=True))
                c.metric("CPA", _fmt(agg["cpa"]))
                st.caption(f"기간 {agg['period']} · 출처 {log.get('source')} · 반영 {log.get('at')} · 통화 KRW 환산")
                if st.button("이 슬롯 데이터 삭제", key=f"ads_clear_{k}"):
                    st.session_state.ads.pop(k, None)
                    st.session_state.ads_log.pop(k, None)
                    st.rerun()


def render():
    st.subheader("캠페인 링크 연동 결과")
    cols = st.columns(3)
    for col, s in zip(cols, SLOTS):
        with col, st.container(border=True):
            _slot_card(s, st.session_state.slots.get(s["key"]))

    rows = [nz.link_metrics_row(s["role"], m) for s, m in connected_slots()]
    st.subheader("공통 지표 (링크 수집 기준)")
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"참여율": st.column_config.NumberColumn(format="percent"),
                                    "조회수": st.column_config.NumberColumn(format="localized"),
                                    "좋아요": st.column_config.NumberColumn(format="localized")})
        st.caption("‘—’ = 해당 매체가 비로그인 공개 정보로 제공하지 않는 지표 (임의 값으로 채우지 않음)")
        put_report("overview", "캠페인 개요 (링크 수집 지표)", tables=[df])
    else:
        st.info("연동된 캠페인이 없습니다.")

    _ads_section()
    for k, df in st.session_state.ads.items():
        if df is None or df.empty:
            continue
        figs = []
        metrics = [(c, n) for c, n in [("views", "일별 조회 (Google Ads)"), ("conversions", "일별 전환")] if df[c].notna().any()]
        cols = st.columns(len(metrics) or 1)
        for col, (c, name) in zip(cols, metrics):  # 척도가 다른 지표는 축을 공유하지 않고 나눠 그림
            fig = go.Figure(go.Scatter(x=df["date"], y=df[c], mode="lines", line=dict(width=2, color=SLOT_COLORS[k]),
                                       hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f}<extra></extra>"))
            style(fig, 260, name)
            col.plotly_chart(fig, use_container_width=True)
            figs.append(fig)
        put_report(f"ads_{k}", f"Google Ads 일별 성과 ({k})", figs=figs,
                   tables=[pd.DataFrame([nz.ads_summary(df)])])

    with st.expander("📖 지표 정의 및 데이터 출처"):
        st.dataframe(nz.METRIC_DEFINITIONS, hide_index=True, width="stretch")
