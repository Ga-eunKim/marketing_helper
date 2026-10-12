"""② 검색 관심도: Google Trends 시계열 + 캠페인 시작일 이벤트 마커 + 전후 비교."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import trends as tr
from core.charts import SERIES, SLOT_COLORS, style
from views.common import connected_slots, kw_list, put_report, slot_name


def _default_keywords() -> str:
    kws = []
    for _, m in connected_slots():
        k = (m.get("brand_kw") or "").strip()
        if k and k not in kws:
            kws.append(k)
    return ", ".join(kws[:5])


def build_figure(df: pd.DataFrame, markers: list[tuple[dict, dict]]) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(df.columns):
        fig.add_scatter(x=df.index, y=df[col], name=col, mode="lines",
                        line=dict(width=2, color=SERIES[i % len(SERIES)]),
                        hovertemplate="%{y}<extra>" + col + "</extra>")
    top = df.max(axis=1)
    for s, m in markers:
        sd = pd.Timestamp(m["start_date"])
        if sd < df.index.min() or sd > df.index.max():
            continue
        idx = df.index[df.index.get_indexer([sd], method="nearest")[0]]
        y = float(top.loc[idx])
        label = f"{m.get('campaign_name') or m.get('title')} 집행 시작"
        fig.add_vline(x=sd, line=dict(color=SLOT_COLORS[s["key"]], width=1, dash="dot"))
        fig.add_scatter(x=[sd], y=[y], mode="markers", name=f"● {s['role']} 시작",
                        marker=dict(size=14, color=SLOT_COLORS[s["key"]], line=dict(color="white", width=2)),
                        hovertemplate=f"{label}<br>{sd:%Y-%m-%d}<extra></extra>", showlegend=True)
        fig.add_annotation(x=sd, y=y, text=label, showarrow=True, arrowhead=0, ay=-36,
                           font=dict(size=11), bgcolor="rgba(255,255,255,0.85)", bordercolor=SLOT_COLORS[s["key"]])
    fig.update_yaxes(title="검색 관심도 (0–100)", range=[0, 110])
    return style(fig, 440)


def pre_post(df: pd.DataFrame, markers, window_days: int = 28) -> pd.DataFrame:
    rows = []
    for s, m in markers:
        sd = pd.Timestamp(m["start_date"])
        pre = df[(df.index >= sd - pd.Timedelta(days=window_days)) & (df.index < sd)]
        post = df[(df.index >= sd) & (df.index < sd + pd.Timedelta(days=window_days))]
        for kw in df.columns:
            a, b = pre[kw].mean(), post[kw].mean()
            rows.append({"캠페인": slot_name(s, m), "시작일": sd.date(), "키워드": kw,
                         f"시작 전 {window_days}일 평균": a, f"시작 후 {window_days}일 평균": b,
                         "변화": (b - a) if pd.notna(a) and pd.notna(b) else None,
                         "변화율": ((b - a) / a) if a and pd.notna(a) and pd.notna(b) else None})
    return pd.DataFrame(rows)


def render():
    st.subheader("Google Trends 검색 관심도 × 캠페인 집행 시점")
    slots = [(s, m) for s, m in connected_slots() if m.get("start_date")]
    c1, c2, c3 = st.columns([5, 2, 2])
    kw_text = c1.text_input("검색 키워드 (쉼표 구분, 최대 5개)", _default_keywords(), key="trend_kw",
                            help="기본값 = 각 슬롯의 브랜드 검색 키워드. 예: LG전자 구독, 삼성 구독")
    geo_name = c2.selectbox("지역", list(tr.GEOS), key="trend_geo")
    start, end = st.session_state.period
    c3.markdown(f"**분석 기간**  \n{start} ~ {end}")
    chosen = st.multiselect("이벤트 마커로 표시할 캠페인 (고객사·경쟁사 비교)", [slot_name(s, m) for s, m in slots],
                            default=[slot_name(s, m) for s, m in slots], key="trend_markers")
    markers = [(s, m) for s, m in slots if slot_name(s, m) in chosen]

    b1, b2 = st.columns([1, 5])
    run = b1.button("Trends 조회", type="primary", key="trend_run")
    refresh = b2.checkbox("캐시 무시하고 새로 조회", key="trend_refresh")
    if run:
        with st.spinner("Google Trends 조회 중… (요청 제한 시 자동 재시도)"):
            try:
                st.session_state.trends = tr.interest_over_time(kw_list(kw_text), start, end, tr.GEOS[geo_name],
                                                                use_cache=not refresh)
            except tr.TrendsError as e:
                st.error(str(e))

    if not st.session_state.trends:
        st.info("키워드와 기간을 확인한 뒤 [Trends 조회]를 누르세요.")
        return
    df, meta = st.session_state.trends
    fig = build_figure(df, markers)
    st.plotly_chart(fig, use_container_width=True)
    out = [m for _, m in markers if not (df.index.min() <= pd.Timestamp(m["start_date"]) <= df.index.max())]
    for m in out:
        st.caption(f"ℹ️ '{m.get('campaign_name')}' 시작일 {m['start_date']}이 조회 기간 밖이라 마커를 표시하지 않았습니다.")

    meta_df = pd.DataFrame([{
        "지역": meta["geo"], "기간": meta["timeframe"], "키워드": ", ".join(meta["keywords"]),
        "단위": meta["granularity"], "지수 기준": meta["index_basis"],
        "출처": meta["source"], "수집 시각": meta["fetched_at"] + (" (캐시)" if meta.get("from_cache") else ""),
    }])
    st.dataframe(meta_df.T.rename(columns={0: "값"}), width="stretch")
    if meta.get("partial_last"):
        st.caption("⚠️ 마지막 구간은 집계가 완료되지 않은 부분 데이터(isPartial)입니다.")
    st.warning("검색 관심도는 **관심의 상대적 변화**를 나타낼 뿐이며 매출·전환과 동일한 의미가 아닙니다. "
               "검색 증가가 곧 구매 증가를 뜻하지 않으며, 다른 이벤트(뉴스·프로모션·계절성)의 영향이 함께 섞여 있습니다.")

    pp = pre_post(df, markers)
    if not pp.empty:
        st.markdown("**캠페인 시작 전후 검색 관심도 비교**")
        st.dataframe(pp, hide_index=True, width="stretch",
                     column_config={"변화율": st.column_config.NumberColumn(format="percent")})
    put_report("trends", "검색 관심도 (Google Trends) × 캠페인 시작일", figs=[fig],
               tables=[meta_df, pp] if not pp.empty else [meta_df],
               text="검색 관심도는 상대지수(0–100)이며 매출·전환과 동일한 의미가 아닙니다.")
