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
    c1.metric(t("이벤트 기간 실제 검색량", "Actual during the event"), f"{r['avg_actual']:.1f}")
    c2.metric(t("이벤트가 없었다면", "Without the event"), f"{r['avg_pred']:.1f}")
    c3.metric(t("차이", "Difference"), f"{r['abs_effect']:+.1f}", f"{r['rel_effect']:+.1%}",
              delta_color="off")
    c4.metric(t("p값", "p-value"), f"{r['p']:.3f}" if r["p"] >= 0.001 else "< 0.001",
              t("의미 있는 차이", "Meaningful difference") if sig else t("우연일 수 있음", "Could be chance"),
              delta_color="normal" if sig else "off")
    lower = r["rel_effect"] < 0
    st.caption(t(f"{w0:%Y.%m.%d}부터 {w1:%m.%d}까지 {r['post_days']}일 동안 {client} 검색량은 이벤트가 없었을 때의 예상보다 "
                 f"{abs(r['rel_effect']):.0%} {'낮았습니다' if lower else '높았습니다'}. "
                 + ("통계적으로도 의미 있는 차이입니다." if sig else "다만 우연히 생길 수 있는 범위 안이라 단정하기는 어렵습니다."),
                 f"From {w0:%b %d} to {w1:%b %d, %Y} ({r['post_days']} days), {client_label} search interest was "
                 f"{abs(r['rel_effect']):.0%} {'lower' if lower else 'higher'} than expected without the event. "
                 + ("The difference is statistically meaningful." if sig else "That's within the range chance alone could produce, though.")))

    with st.expander(t("어떻게 계산했나요?", "How was this calculated?")):
        base = ", ".join(baseline)
        kws = ", ".join(ev["keywords"])
        min_days = ev.get("min_window_days", 7)
        st.markdown(t(
            f"""이벤트가 없었을 때의 검색량은 같은 업종 전체의 검색 흐름({base})을 기준으로 예측했습니다. 이벤트 전 {r['pre_days']}일 동안 {client} 검색량이 업종 흐름과 어떻게 같이 움직였는지 학습한 뒤, 이벤트 기간에도 그 관계가 그대로 이어졌다고 가정한 값입니다. 실제 검색량에서 이 예상치를 뺀 것이 이벤트의 영향입니다.

이벤트 기간은 '{kws}' 검색량이 최고점의 25% 이상으로 올라가 있던 구간으로 잡았습니다(하루짜리 급등이면 최소 {min_days}일). 이 키워드는 기간을 찾는 데만 쓰고 예측에는 넣지 않았습니다. 넣으면 이벤트 효과까지 모델이 설명해 버려서 차이가 사라지기 때문입니다.

모델은 CausalImpact와 같은 구조(추세·요일 패턴·업종 흐름)이고, p값은 예측의 불확실성을 1,000번 시뮬레이션해서 구했습니다. 같은 시기에 신제품 출시나 뉴스가 있었다면 그 영향도 섞여 있을 수 있고, 검색량이 곧 매출을 뜻하지는 않습니다.""",
            f"""The no-event baseline is predicted from the overall category's search trend ({base}). The model learns how {client_label} searches moved with the category during the {r['pre_days']} days before the event, then assumes that relationship held during the event. Actual searches minus this baseline is the event's effect.

The event window is the stretch where '{kws}' searches stayed above 25% of their peak (at least {min_days} days for one-day spikes). Those terms only define the window — they're kept out of the prediction, because including them would let the model explain away the effect.

The model has the same structure as CausalImpact (trend, day-of-week pattern, category trend), and the p-value comes from 1,000 simulations of the prediction's uncertainty. Product launches or news in the same period can also show up in the difference, and search interest isn't the same as sales."""))
    st.divider()


def render():
    cf_area = st.container()  # '이벤트가 없었다면' 반사실 분석 (해당 회사가 고객사/경쟁사일 때만, 맨 위)
    st.markdown(t("#### 검색량 흐름과 유튜브 업로드", "#### Search Interest & YouTube Uploads"))
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
            st.info(t("아래에서 키워드를 확인하고 [Trends 조회]를 눌러 주세요.",
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
        st.caption(t("Google Trends 검색량(기간 내 최고치 = 100)입니다. 점은 각 브랜드 채널에 올라온 유튜브 영상(Shorts 제외)이고, 마우스를 올리면 제목이 보입니다. "
                     "점선은 이벤트 키워드를 합친 검색량입니다. 업로드일은 채널 목록의 '3주 전' 같은 표기로 추정해서 몇 주 단위로는 어긋날 수 있습니다.",
                     "Google Trends search interest (peak in the period = 100). Dots are YouTube videos (excluding Shorts) posted on each brand's channel — hover to see the title. "
                     "The dotted line is the event keywords combined. Upload dates come from labels like '3 weeks ago', so they can be off by a few weeks."))

    st.caption(t("검색량은 관심이 얼마나 늘고 줄었는지를 보여줄 뿐, 그만큼 팔렸다는 뜻은 아닙니다. 뉴스나 계절 영향도 함께 섞여 있어요.",
                 "Search interest shows how attention rose and fell — not how much was sold. News and seasonality are mixed in too."))
    geo = meta["geo"]
    meta_df = pd.DataFrame({t("값", "Value"): {
        t("지역", "Region"): t(geo, GEO_EN.get(geo, geo)),
        t("기간", "Period"): meta["timeframe"],
        t("키워드", "Search terms"): ", ".join(meta["keywords"]),
        t("단위", "Granularity"): t(meta["granularity"], GRAN_EN.get(meta["granularity"], meta["granularity"])),
        t("지수 기준", "Index basis"): t("기간·지역 안에서 가장 많이 검색된 날을 100으로 놓은 상대값 (실제 검색 횟수 아님)",
                                       "Relative value where the busiest day in the period and region = 100 (not raw search counts)"),
        t("출처", "Source"): meta["source"],
        t("수집 시각", "Fetched at"): meta["fetched_at"] + (t(" (캐시)", " (cached)") if meta.get("from_cache") else ""),
    }})
    with st.expander(t("데이터 기준", "Data details")):
        st.dataframe(meta_df, width="stretch")
    if meta.get("partial_last"):
        st.caption(t("⚠️ 마지막 구간은 집계가 완료되지 않은 부분 데이터(isPartial)입니다.",
                     "⚠️ The last data point is partial (isPartial) and may still change."))
