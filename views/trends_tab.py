"""검색 관심도: Google Trends 시계열 + 채널 업로드 영상 점."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import channel, i18n
from core import trends as tr
from core.charts import SERIES, SLOT_COLORS, style
from core.i18n import t
from views.common import connected_slots, slot_name

GEO_EN = {"대한민국": "South Korea", "전 세계": "Worldwide", "미국": "United States", "일본": "Japan"}
GRAN_EN = {"일별": "Daily", "주별": "Weekly", "월별": "Monthly"}


def build_figure(df: pd.DataFrame, uploads: list[tuple[dict, dict, str | None, list[dict]]]) -> go.Figure:
    """검색 관심도 선 + 채널 업로드 영상 점 (점에 마우스를 올리면 영상 제목)."""
    fig = go.Figure()
    interest = t("관심도", "Interest")
    for i, col in enumerate(df.columns):
        fig.add_scatter(x=df.index, y=df[col], name=col, mode="lines",
                        line=dict(width=2, color=SERIES[i % len(SERIES)]),
                        hovertemplate="%{x|%Y-%m-%d} · " + interest + " %{y}<extra>" + col + "</extra>")
    for s, m, kw, vids in uploads:
        vids = [v for v in vids if df.index.min() <= pd.Timestamp(v["published"]) <= df.index.max()]
        if not vids:
            continue
        line = df[kw] if kw in df.columns else df.max(axis=1)  # 해당 채널 키워드 선 위에 점을 찍음
        xs = [pd.Timestamp(v["published"]) for v in vids]
        ys = [float(line.iloc[line.index.get_indexer([x], method="nearest")[0]]) for x in xs]
        fig.add_scatter(x=xs, y=ys, mode="markers",
                        name=t(f"● {slot_name(s, m)} 업로드 ({len(vids)})", f"● {slot_name(s, m)} uploads ({len(vids)})"),
                        marker=dict(size=9, color=SLOT_COLORS[s["key"]], line=dict(color="white", width=1.5)),
                        customdata=[[v["title"], i18n.rel_time(v.get("rel")) or v["published"]] for v in vids],
                        hovertemplate="<b>%{customdata[0]}</b><br>" + t("%{customdata[1]} 업로드", "Uploaded %{customdata[1]}")
                                      + "<extra>" + m.get("account", "") + "</extra>")
    fig.update_yaxes(title=t("검색 관심도 (0–100)", "Search interest (0–100)"), range=[0, 110])
    style(fig, 440)
    fig.update_layout(hovermode="closest")  # 점 하나하나의 제목을 보여주기 위해
    return fig


def _fetch(keywords, start, end, geo, use_cache=True, retries=3):
    try:
        st.session_state.trends = tr.interest_over_time(keywords, start, end, geo, use_cache=use_cache, retries=retries)
        st.session_state.trends_err = None
    except tr.TrendsError as e:
        st.session_state.trends_err = str(e)


def render():
    st.markdown(t("#### Google Trends 검색 관심도 × 캠페인 집행 시점", "#### Search Interest (Google Trends) × Content Uploads"))
    chart_area = st.container()  # 그래프를 먼저 배치하고, 키워드 입력은 그래프 아래에

    client, rival = st.session_state.client, st.session_state.competitor
    c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
    kw_own = c1.text_input(t("고객사 검색 키워드", "Client search term"), client, key=f"trend_kw_own_{client}")
    kw_rival = c2.text_input(t("경쟁사 검색 키워드", "Competitor search term"), rival, key=f"trend_kw_rival_{rival}")
    geo_name = c3.selectbox(t("지역", "Region"), list(tr.GEOS), key=f"trend_geo_{i18n.lang()}",
                            format_func=lambda g, en=i18n.lang() == "EN": GEO_EN.get(g, g) if en else g)
    start, end = st.session_state.period
    c4.markdown(f"**{t('분석 기간', 'Date range')}**  \n{start} ~ {end}")
    keywords = [k.strip() for k in (kw_own, kw_rival) if k.strip()]

    b1, b2 = st.columns([1, 5])
    run = b1.button(t("Trends 조회", "Refresh Trends"), type="primary", key="trend_run")
    refresh = b2.checkbox(t("캐시 무시하고 새로 조회", "Ignore cache"), key="trend_refresh")
    if run:
        with st.spinner(t("Google Trends 조회 중… (요청 제한 시 자동 재시도)", "Querying Google Trends… (auto-retry on rate limit)")):
            _fetch(keywords, start, end, tr.GEOS[geo_name], use_cache=not refresh)
    elif st.session_state.trends is None and not st.session_state.get("trends_auto"):
        st.session_state.trends_auto = True  # 첫 화면 자동 조회 1회 (재시도 없이)
        with st.spinner(t("Google Trends 조회 중…", "Querying Google Trends…")):
            _fetch(keywords, start, end, tr.GEOS[geo_name], retries=1)

    with chart_area:
        if st.session_state.get("trends_err"):
            st.error(st.session_state.trends_err)
        if not st.session_state.trends:
            st.info(t("아래에서 키워드와 기간을 확인한 뒤 [Trends 조회]를 누르세요.",
                      "Check the search terms and date range below, then click [Refresh Trends]."))
            return
        df, meta = st.session_state.trends
        if meta.get("stale"):
            st.caption(t(f"ℹ️ Google Trends 요청이 제한되어 {meta['fetched_at']}에 받아 둔 결과({meta['timeframe']})를 표시합니다.",
                         f"ℹ️ Google Trends is rate-limited — showing the result saved at {meta['fetched_at']} ({meta['timeframe']})."))
        if sorted(meta["keywords"]) != sorted(keywords):
            st.caption(t(f"ℹ️ 그래프는 이전 키워드({', '.join(meta['keywords'])}) 결과입니다. 아래 [Trends 조회]를 눌러 갱신하세요.",
                         f"ℹ️ The chart shows previous terms ({', '.join(meta['keywords'])}). Click [Refresh Trends] below to update."))
        uploads = []
        kw_of = {"고객사": kw_own.strip(), "경쟁사": kw_rival.strip()}
        for sl, m in connected_slots("YouTube"):
            if not m.get("channel_id"):
                continue
            with st.spinner(t(f"{m.get('account')} 채널 업로드 영상 확인 중… (첫 조회만 느림)",
                              f"Loading {m.get('account')} channel uploads… (slow only the first time)")):
                try:
                    vids = channel.uploads(m["channel_id"], start)
                except Exception as e:
                    st.caption(t(f"⚠️ {m.get('account')} 채널 업로드 목록을 가져오지 못했습니다: {e}",
                                 f"⚠️ Couldn't load {m.get('account')} channel uploads: {e}"))
                    continue
            uploads.append((sl, m, kw_of.get(sl["side"]), vids))
        fig = build_figure(df, uploads)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(t("● 점 = 해당 채널의 YouTube 동영상 업로드 (Shorts 제외) · 점에 마우스를 올리면 영상 제목이 표시됩니다. "
                     "업로드일은 채널 목록의 '○일/주/개월 전' 표기로 추정한 날짜라 주·개월 단위는 오차가 있습니다.",
                     "● Dots = YouTube video uploads from each brand's channel (Shorts excluded) · hover a dot to see the title. "
                     "Upload dates are estimated from the channel's 'N days/weeks/months ago' labels, so week/month-level dates are approximate."))

    geo = meta["geo"]
    meta_df = pd.DataFrame({t("값", "Value"): {
        t("지역", "Region"): t(geo, GEO_EN.get(geo, geo)),
        t("기간", "Period"): meta["timeframe"],
        t("키워드", "Search terms"): ", ".join(meta["keywords"]),
        t("단위", "Granularity"): t(meta["granularity"], GRAN_EN.get(meta["granularity"], meta["granularity"])),
        t("지수 기준", "Index basis"): t("기간·지역 내 최대 검색량 = 100 기준 상대지수 (절대 검색량 아님, 키워드 간 동일 요청 내에서만 비교 가능)",
                                       "Relative index where peak search volume in the period/region = 100 (not absolute volume; "
                                       "comparable only across terms in the same request)"),
        t("출처", "Source"): meta["source"],
        t("수집 시각", "Fetched at"): meta["fetched_at"] + (t(" (캐시)", " (cached)") if meta.get("from_cache") else ""),
    }})
    st.dataframe(meta_df, width="stretch")
    if meta.get("partial_last"):
        st.caption(t("⚠️ 마지막 구간은 집계가 완료되지 않은 부분 데이터(isPartial)입니다.",
                     "⚠️ The last data point is partial (isPartial) and may still change."))
    st.warning(t("검색 관심도는 **관심의 상대적 변화**를 나타낼 뿐이며 매출·전환과 동일한 의미가 아닙니다. "
                 "검색 증가가 곧 구매 증가를 뜻하지 않으며, 다른 이벤트(뉴스·프로모션·계절성)의 영향이 함께 섞여 있습니다.",
                 "Search interest reflects **relative changes in consumer interest**, not sales or conversions. "
                 "A rise in searches doesn't necessarily mean more purchases, and it also reflects other factors "
                 "(news, promotions, seasonality)."))
