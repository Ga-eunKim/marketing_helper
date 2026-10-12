"""검색 관심도: Google Trends 시계열 + 채널 업로드 영상 점."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import causal, channel, i18n
from core import trends as tr
from core.charts import SERIES, SLOT_COLORS, style
from core.config import category_baseline, name_en, promo_event
from core.i18n import t
from views.common import connected_slots, slot_name

GEO_EN = {"대한민국": "South Korea", "전 세계": "Worldwide", "미국": "United States", "일본": "Japan"}
GRAN_EN = {"일별": "Daily", "주별": "Weekly", "월별": "Monthly"}


def build_figure(df: pd.DataFrame, uploads: list[tuple[dict, dict, str | None, list[dict]]],
                 brand_kws: tuple[str, str] = ("", ""), event_kws: list[str] | None = None) -> go.Figure:
    """검색 관심도 선(고객사·경쟁사 실선, 이벤트 키워드 점선) + 채널 업로드 영상 점."""
    fig = go.Figure()
    interest = t("관심도", "Interest")
    event_kws = event_kws or []
    for col in df.columns:  # 캐시된 결과의 열 순서와 무관하게 역할별 고정 색
        if col == brand_kws[0]:
            line = dict(width=2, color=SERIES[0])
        elif col == brand_kws[1]:
            line = dict(width=2, color=SERIES[1])
        else:
            i = event_kws.index(col) if col in event_kws else 0
            line = dict(width=1.5, color=SERIES[(3 + i) % len(SERIES)], dash="dot")
        fig.add_scatter(x=df.index, y=df[col], name=col, mode="lines", line=line,
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


def _josa(word: str) -> str:
    """이/가 — 마지막 글자 받침 유무."""
    ch = word.strip()[-1:] if word.strip() else ""
    if "가" <= ch <= "힣":
        return "이" if (ord(ch) - 0xAC00) % 28 else "가"
    return "이(가)"


def _counterfactual(start, end, geo: str, uploads: list[tuple[dict, dict, list[dict]]]):
    """경쟁사(또는 고객사) 프로모션 이벤트가 없었다면 고객사 검색 관심도는? — BSTS 방식 반사실 분석."""
    ss = st.session_state
    found = promo_event(ss.client, ss.competitor)
    if not found:
        return
    company, ev = found
    client = ss.client
    event_name, client_label = t(ev["name"], ev.get("name_en", ev["name"])), t(client, name_en(client))
    label_ko = ev.get("label_ko") or f"{company}의 {ev['name']}"
    st.markdown("#### " + t(f"{label_ko}{_josa(label_ko)} 없었을 경우 추정되는 {client}의 가상 검색 트렌드(Baseline)와 실제 트렌드 비교",
                            f"[{name_en(client)}] Counterfactual Search Interest: Assuming No {event_name}"))
    baseline = category_baseline(client)
    if not baseline:
        st.caption(t("⚠️ clients.json에 이 고객사의 category_baseline(통제 변수)이 없어 반사실 분석을 할 수 없습니다.",
                     "⚠️ No category_baseline (control variables) set for this client in clients.json."))
        return
    try:
        model_df, _ = tr.interest_over_time([client] + baseline, start, end, geo, retries=2)
        promo_df, _ = tr.interest_over_time(ev["keywords"], start, end, geo, retries=2)
    except tr.TrendsError as e:
        st.caption(f"⚠️ {e}")
        return
    window = causal.detect_window(promo_df.sum(axis=1), min_days=ev.get("min_window_days", 7))
    if window is None:
        st.info(t(f"분석 기간 안에 [{event_name}] 관련 검색이 없어 이벤트 기간을 찾지 못했습니다.",
                  f"No [{event_name}] searches in the date range, so no event window was found."))
        return
    try:
        r = causal.run(model_df[client], model_df[[c for c in baseline if c in model_df.columns]], window)
    except causal.CausalError as e:
        st.info(str(e))
        return

    w0, w1 = r["window"]
    fig = go.Figure()
    fig.add_vrect(x0=w0, x1=w1, fillcolor="rgba(235,104,52,0.08)", line_width=0,
                  annotation_text=t(f"{event_name} 기간", f"{event_name} window"), annotation_position="top left",
                  annotation_font=dict(size=11, color="#9a3412"))
    fig.add_scatter(x=list(r["hi"].index) + list(r["lo"].index[::-1]), y=list(r["hi"]) + list(r["lo"][::-1]),
                    fill="toself", fillcolor="rgba(120,120,120,0.18)", line=dict(width=0), hoverinfo="skip",
                    name=t("가상 트렌드 95% 구간", "Counterfactual 95% interval"))
    fig.add_scatter(x=r["actual"].index, y=r["actual"], mode="lines", line=dict(width=2, color=SERIES[0]),
                    name=t(f"{client} 실제 트렌드", f"{client_label} actual"),
                    hovertemplate="%{x|%Y-%m-%d} · %{y:.0f}<extra></extra>")
    fig.add_scatter(x=r["pred"].index, y=r["pred"], mode="lines", line=dict(width=2, color="#6b7280", dash="dash"),
                    name=t("가상 검색 트렌드 (Baseline)", "Without the event (counterfactual)"),
                    hovertemplate="%{x|%Y-%m-%d} · %{y:.1f}<extra></extra>")
    actual = r["actual"]
    for sl, m, vids in uploads:  # 업로드 영상 점 — 메인 그래프와 같은 방식, 실제 검색 관심도 선 위에 찍음
        vids = [v for v in vids if actual.index.min() <= pd.Timestamp(v["published"]) <= actual.index.max()]
        if not vids:
            continue
        xs = [pd.Timestamp(v["published"]) for v in vids]
        ys = [float(actual.iloc[actual.index.get_indexer([x], method="nearest")[0]]) for x in xs]
        fig.add_scatter(x=xs, y=ys, mode="markers",
                        name=t(f"● {slot_name(sl, m)} 업로드 ({len(vids)})", f"● {slot_name(sl, m)} uploads ({len(vids)})"),
                        marker=dict(size=8, color=SLOT_COLORS[sl["key"]], line=dict(color="white", width=1.5)),
                        customdata=[[v["title"], i18n.rel_time(v.get("rel")) or v["published"]] for v in vids],
                        hovertemplate="<b>%{customdata[0]}</b><br>" + t("%{customdata[1]} 업로드", "Uploaded %{customdata[1]}")
                                      + "<extra>" + m.get("account", "") + "</extra>")
    fig.update_yaxes(title=t("검색 관심도 (0–100)", "Search interest (0–100)"), rangemode="tozero")
    style(fig, 360)
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, use_container_width=True)

    sig = r["p"] < 0.05
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("실제 평균 (이벤트 기간)", "Actual avg. (event window)"), f"{r['avg_actual']:.1f}")
    c2.metric(t("예상 반응값 평균 (반사실)", "Counterfactual avg."), f"{r['avg_pred']:.1f}")
    c3.metric(t("순수 효과 (평균)", "Causal impact (avg.)"), f"{r['abs_effect']:+.1f}", f"{r['rel_effect']:+.1%}",
              delta_color="off")
    c4.metric(t("유의성 (p값)", "Significance (p-value)"), f"{r['p']:.3f}",
              t("유의함 (p<0.05)", "Significant (p<0.05)") if sig else t("유의하지 않음", "Not significant"),
              delta_color="normal" if sig else "off")
    st.caption(t(f"이벤트 기간 {w0:%Y-%m-%d} ~ {w1:%Y-%m-%d} ({r['post_days']}일) · 학습 구간 {r['pre_days']}일 · "
                 f"누적 효과 {r['cum_effect']:+.0f} (95% 구간 {r['cum_lo']:+.0f} ~ {r['cum_hi']:+.0f})",
                 f"Event window {w0:%Y-%m-%d} – {w1:%Y-%m-%d} ({r['post_days']} days) · training period {r['pre_days']} days · "
                 f"cumulative impact {r['cum_effect']:+.0f} (95% interval {r['cum_lo']:+.0f} to {r['cum_hi']:+.0f})"))

    with st.expander(t("분석 방법 · 해석 (BSTS · CausalImpact)", "Methodology & interpretation (BSTS · CausalImpact)")):
        base = ", ".join(baseline)
        kws = ", ".join(ev["keywords"])
        min_days = ev.get("min_window_days", 7)
        st.markdown(t(
            f"""- **예상 반응값(Counterfactual)**: 업종 카테고리 전체 트렌드({base} 검색량)를 통제 변수로 활용하여 이벤트 미발생 시의 {client} 검색량을 사후 예측함
- **순수 효과(Causal Impact)**: [실제 관측값] − [모델 예측값]
- **검증**: Posterior Tail-Area Probability (p < 0.05 기준)
- **이벤트 기간**: '{kws}' 검색량(7일 이동평균)이 최고점의 25% 이상인 연속 구간을 자동 탐지 (하루짜리 급등이면 최소 {min_days}일). 이 키워드는 기간을 찾는 데만 쓰고 통제 변수에는 넣지 않음 (넣으면 효과를 모델이 흡수함)
- **모델**: 로컬 레벨 + 주간 계절성 + 공변량 회귀의 구조 시계열(BSTS 구성)을 이벤트 이전 구간으로 학습. statsmodels 최대우도 추정과 시뮬레이션으로 구간·p값을 계산 (TensorFlow 기반 CausalImpact 패키지 대신 경량 구현)
- **주의**: 같은 시기의 다른 이벤트(신제품 출시, 뉴스, 다른 프로모션)도 효과에 섞일 수 있으며, 검색 관심도는 매출·전환과 같은 지표가 아님""",
            f"""- **Counterfactual**: uses the overall category trend ({base} searches) as control variables to predict what {client} search interest would have been without the event
- **Causal impact**: [observed] − [model prediction]
- **Validation**: posterior tail-area probability (p < 0.05)
- **Event window**: auto-detected as the continuous period where '{kws}' searches (7-day average) stay above 25% of their peak (at least {min_days} days for one-day spikes). These terms only define the window and are not used as controls (as controls they would absorb the effect)
- **Model**: structural time series with local level + weekly seasonality + covariate regression (the BSTS setup), trained on the pre-event period. Intervals and p-value come from statsmodels maximum-likelihood estimation and simulation (a lightweight alternative to the TensorFlow-based CausalImpact package)
- **Caveats**: other concurrent events (product launches, news, other promotions) can mix into the effect, and search interest is not the same as sales or conversions"""))
    st.divider()


def render():
    cf_area = st.container()  # '이벤트가 없었다면' 반사실 분석 (해당 회사가 고객사/경쟁사일 때만, 맨 위)
    st.markdown(t("#### Google Trends 검색 관심도 × 캠페인 집행 시점", "#### Search Interest (Google Trends) × Content Uploads"))
    chart_area = st.container()  # 그래프를 먼저 배치하고, 키워드 입력은 그래프 아래에

    client, rival = st.session_state.client, st.session_state.competitor
    found = promo_event(client, rival)
    default_ev = ", ".join(found[1]["keywords"]) if found else ""
    c1, c2, c3, c4, c5 = st.columns([2, 2, 3, 2, 2])
    kw_own = c1.text_input(t("고객사 검색 키워드", "Client search term"), client, key=f"trend_kw_own_{client}")
    kw_rival = c2.text_input(t("경쟁사 검색 키워드", "Competitor search term"), rival, key=f"trend_kw_rival_{rival}")
    ev_text = c3.text_input(t("이벤트 키워드 (쉼표 구분, 최대 3개)", "Event keywords (comma-separated, max 3)"), default_ev,
                            key=f"trend_kw_event_{client}_{rival}",
                            help=t("예: 삼성전자에서 세일 이벤트로 쓴 키워드. 고객사·경쟁사 검색량과 같은 기준으로 점선 표시",
                                   "e.g. keywords Samsung used for its sale event — shown as dotted lines on the same scale"))
    geo_name = c4.selectbox(t("지역", "Region"), list(tr.GEOS), key=f"trend_geo_{i18n.lang()}",
                            format_func=lambda g, en=i18n.lang() == "EN": GEO_EN.get(g, g) if en else g)
    start, end = st.session_state.period
    c5.markdown(f"**{t('분석 기간', 'Date range')}**  \n{start} ~ {end}")
    brand = [k.strip() for k in (kw_own, kw_rival) if k.strip()]
    event_kws = [k for k in dict.fromkeys(x.strip() for x in ev_text.split(",")) if k and k not in brand]
    if len(brand) + len(event_kws) > 5:  # Google Trends 요청당 5개 제한
        st.caption(t(f"⚠️ 키워드는 최대 5개까지라 이벤트 키워드는 앞의 {5 - len(brand)}개만 사용합니다.",
                     f"⚠️ Google Trends allows 5 terms, so only the first {5 - len(brand)} event keywords are used."))
        event_kws = event_kws[:5 - len(brand)]
    keywords = brand + event_kws

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

    uploads_raw = []  # 채널 업로드 영상 (반사실 그래프·메인 그래프 공용)
    for sl, m in connected_slots("YouTube"):
        if not m.get("channel_id"):
            continue
        with st.spinner(t(f"{m.get('account')} 채널 업로드 영상 확인 중… (첫 조회만 느림)",
                          f"Loading {m.get('account')} channel uploads… (slow only the first time)")):
            try:
                uploads_raw.append((sl, m, channel.uploads(m["channel_id"], start)))
            except Exception as e:
                st.caption(t(f"⚠️ {m.get('account')} 채널 업로드 목록을 가져오지 못했습니다: {e}",
                             f"⚠️ Couldn't load {m.get('account')} channel uploads: {e}"))

    with cf_area:
        _counterfactual(start, end, tr.GEOS[geo_name], uploads_raw)

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
        kw_of = {"고객사": kw_own.strip(), "경쟁사": kw_rival.strip()}
        uploads = [(sl, m, kw_of.get(sl["side"]), vids) for sl, m, vids in uploads_raw]
        ev_cols = [c for c in event_kws if c in df.columns]
        plot_df, ev_label = df, None
        if ev_cols:  # 이벤트 키워드는 합쳐서 한 줄로 (같은 요청 안의 지수라 합산 가능)
            ev_label = " + ".join(ev_cols)
            plot_df = df.drop(columns=ev_cols).assign(**{ev_label: df[ev_cols].sum(axis=1)})
        fig = build_figure(plot_df, uploads, (kw_own.strip(), kw_rival.strip()), [ev_label] if ev_label else [])
        st.plotly_chart(fig, use_container_width=True)
        st.caption(t("● 점 = 해당 채널의 YouTube 동영상 업로드 (Shorts 제외) · 점에 마우스를 올리면 영상 제목이 표시됩니다 · 점선 = 이벤트 키워드 합계. "
                     "업로드일은 채널 목록의 '○일/주/개월 전' 표기로 추정한 날짜라 주·개월 단위는 오차가 있습니다.",
                     "● Dots = YouTube video uploads from each brand's channel (Shorts excluded) · hover a dot to see the title · dotted line = event keywords combined. "
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
