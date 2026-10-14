"""게임 캠페인 전용 페이지 (예: 데브시스터즈 · 쿠키런: 킹덤 4주년 메가 크리에이터 캠페인).

스토어 리뷰 시계열(다운로드 프록시) + 유튜브 댓글 테마 점수 + Share of Search를 결합해 캠페인 증분을 추정하는
3단 경영진 대시보드. Tier 1 요약(게이지·KPI) → Tier 2 반사실 시계열 → Tier 3 댓글 트리맵·SOS 시차.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import cache, cached, causal, game, playstore
from core import comments as cm
from core import trends as tr
from core.charts import SERIES, style
from core.config import game_config
from core.i18n import t
from views.common import connected_slots, image_bytes, slot_name

GREEN, GREEN_2, GRAY, RED, BLUE = "#008300", "#1baf7a", "#9ca3af", "#e34948", SERIES[0]
THEME_COLOR = {"lore": GREEN, "intent": GREEN_2, "general": GRAY, "negative": RED}
ZONE = {"low": ("단순 지표 상승 (허수 클릭)", "Vanity lift (low-quality clicks)"),
        "moderate": ("브랜드 인식 제고 (검색량 상승)", "Brand awareness (search lift)"),
        "high": ("High Lore & High Conversion (진성 유저 유입)", "High Lore & High Conversion (quality user inflow)")}
IROAS = {"high": ("HIGH (우수)", "HIGH"), "moderate": ("MODERATE (보통)", "MODERATE"), "low": ("LOW (미흡)", "LOW")}


def _load(cfg: dict, start, end):
    """스토어 리뷰·검색 관심도·댓글 (모두 디스크 캐시 우선)."""
    errors = []
    try:
        if cfg.get("store_scope") == "global":  # 10개 언어 리뷰 합산
            rv, failed = playstore.daily_reviews_global(cfg["app_id"], start)
            if failed:
                errors.append(t(f"일부 언어 리뷰 수집 실패: {', '.join(failed)}", f"Some languages failed: {', '.join(failed)}"))
        else:
            rv = playstore.daily_reviews(cfg["app_id"], start, cfg.get("store_lang", "ko"), cfg.get("store_country", "kr"))
        rv = rv.loc[str(start):str(end)]
    except Exception as e:
        rv = None
        errors.append(t(f"스토어 리뷰 수집 실패: {e}", f"Store review collection failed: {e}"))
    terms = [cfg["search_term"]] + cfg.get("rival_terms", []) + ([cfg["market_term"]] if cfg.get("market_term") else [])
    try:
        td, tmeta = tr.interest_over_time(terms[:5], start, end, cfg.get("geo", "KR"), retries=2)
    except tr.TrendsError as e:
        td, tmeta = None, None
        errors.append(str(e))
    return rv, td, tmeta, errors


def _comments(cfg: dict, video_id: str | None):
    if not video_id:
        return None
    limit = cfg.get("comment_limit", 3000)
    hit = cached.comments_if_cached(video_id, limit, "최신순")
    if hit is None:
        c1, c2 = st.columns([1, 2])
        if c1.button(t("트레일러 댓글 수집", "Collect trailer comments"), key="game_cm_run"):
            with st.spinner(t("댓글 수집 중… (수천 개는 1~2분)", "Collecting comments… (1–2 min for thousands)")):
                try:
                    hit = cached.comments(video_id, limit, "최신순", refresh=True)
                except Exception as e:
                    st.error(str(e))
        # YouTube가 수집을 막을 때: 외부 도구로 내려받은 댓글 CSV를 올리면 같은 캐시에 저장
        up = c2.file_uploader(t("또는 댓글 CSV 업로드 (TheYouTubeTool 등)", "Or upload a comments CSV (e.g. TheYouTubeTool)"),
                              type=["csv"], key="game_cm_csv")
        if up is not None:
            try:
                hit = cm.from_csv(up, video_id)
                cache.put("comments", (video_id, limit, "최신순"), hit)
            except Exception as e:
                st.error(str(e))
    return hit if hit is not None and len(hit) else None


def _gauge(score: float) -> go.Figure:
    z = game.zone(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, number=dict(suffix=" / 100", font=dict(size=28)),
        gauge=dict(
            axis=dict(range=[0, 100], tickvals=[0, 30, 70, 100]),
            bar=dict(color={"low": RED, "moderate": "#eda100", "high": GREEN}[z], thickness=0.3),
            steps=[dict(range=[0, 30], color="rgba(227,73,72,0.15)"),
                   dict(range=[30, 70], color="rgba(237,161,0,0.15)"),
                   dict(range=[70, 100], color="rgba(0,131,0,0.15)")],
        ),
        title=dict(text=t("캠페인 건강도 지수", "Campaign Health Index"), font=dict(size=14)),
    ))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=50, b=10), paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _causal_chart(r: dict, title_actual: str) -> go.Figure:
    w0, w1 = r["window"]
    actual, pred = r["actual"], r["pred"]
    fig = go.Figure()
    fig.add_vrect(x0=w0, x1=w1, fillcolor="rgba(42,120,214,0.06)", line_width=0,
                  annotation_text=t("캠페인 기간", "Campaign window"), annotation_position="top left",
                  annotation_font=dict(size=11, color="#1c5cab"))
    fig.add_scatter(x=list(r["hi"].index) + list(r["lo"].index[::-1]), y=list(r["hi"]) + list(r["lo"][::-1]),
                    fill="toself", fillcolor="rgba(120,120,120,0.15)", line=dict(width=0), hoverinfo="skip",
                    name=t("가상 시나리오 95% 구간", "Counterfactual 95% interval"))
    fig.add_scatter(x=actual.index, y=actual, mode="lines", line=dict(width=1.5, color=BLUE),
                    name=title_actual, hovertemplate="%{x|%Y-%m-%d} · %{y:.0f}<extra></extra>")
    # 순수 증분(Lift) 음영: 반사실 선 → 실제 선 사이를 채움
    post_actual = actual.loc[w0:w1]
    fig.add_scatter(x=pred.index, y=pred, mode="lines", line=dict(width=2, color="#6b7280", dash="dash"),
                    name=t("마케팅 미집행 가상 시나리오", "Counterfactual (no campaign)"),
                    hovertemplate="%{x|%Y-%m-%d} · %{y:.1f}<extra></extra>")
    fig.add_scatter(x=post_actual.index, y=post_actual, mode="lines", line=dict(width=0), fill="tonexty",
                    fillcolor="rgba(42,120,214,0.30)", name=t("순수 증분 (Proxy Lift)", "Incremental lift (proxy)"),
                    hoverinfo="skip")
    fig.update_yaxes(title=t("일별 신규 스토어 리뷰 수", "Daily new store reviews"), rangemode="tozero")
    style(fig, 400)
    return fig


def _treemap(counts: pd.DataFrame) -> go.Figure:
    c = counts[counts["count"] > 0]
    ids, labels, parents, values, colors = [], [], [], [], []
    for theme, grp in c.groupby("theme", sort=False):
        name = t(*game.THEME_LABEL[theme])
        ids.append(theme), labels.append(name), parents.append(""), values.append(int(grp["count"].sum()))
        colors.append(THEME_COLOR[theme])
        for row in grp.itertuples():
            ids.append(f"{theme}/{row.keyword}"), labels.append(row.keyword), parents.append(theme)
            values.append(int(row.count)), colors.append(THEME_COLOR[theme])
    fig = go.Figure(go.Treemap(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                               marker=dict(colors=colors, line=dict(color="white", width=2)),
                               texttemplate="%{label}<br>%{value}", hovertemplate="%{label}: %{value}<extra></extra>"))
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=30, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      title=dict(text=t("유튜브 댓글 테마·키워드 (면적 = 언급 수)", "YouTube comment themes & keywords (area = mentions)"),
                                 font=dict(size=13)))
    return fig


def render():
    ss = st.session_state
    cfg = game_config(ss.client)
    app_name = t(cfg["app_name"], cfg.get("app_name_en", cfg["app_name"]))
    camp = t(cfg["campaign_name"], cfg.get("campaign_name_en", cfg["campaign_name"]))
    w0, w1 = pd.Timestamp(cfg["campaign_start"]), pd.Timestamp(cfg["campaign_end"])
    start, end = (w0 - timedelta(days=cfg.get("pre_days", 120))).date(), (w1 + timedelta(days=cfg.get("post_days", 30))).date()
    st.markdown(f"#### {app_name} {camp}")
    if cfg.get("store_scope") == "global":
        region = t("글로벌 (스토어 리뷰 10개 언어 합산 · 검색량 전 세계)", "Global (store reviews in 10 languages · worldwide search)")
    else:
        region = t(f"{cfg.get('geo') or '전 세계'} (스토어 리뷰 {cfg.get('store_lang', 'ko')})",
                   f"{cfg.get('geo') or 'Worldwide'} (store reviews in {cfg.get('store_lang', 'ko')})")
    st.caption(t(f"캠페인 {w0:%Y.%m.%d} – {w1:%m.%d} · 비교 기간 {start:%Y.%m.%d} – {end:%Y.%m.%d} · 지역 {region}",
                 f"Campaign {w0:%b %d} – {w1:%b %d, %Y} · compared against {start:%b %d, %Y} – {end:%b %d, %Y} · Region: {region}"))

    with st.spinner(t("스토어 리뷰와 검색 데이터를 불러오는 중…", "Loading store reviews and search data…")):
        rv, td, tmeta, errors = _load(cfg, start, end)
    for e in errors:
        st.warning(e)

    slots = {s["key"]: (s, m) for s, m in connected_slots()}
    yt = slots.get("main")
    yt_meta = yt[1] if yt and yt[1]["platform"] == "YouTube" and yt[1].get("kind") != "channel" else None

    # ── 분석 ──────────────────────────────────────────────────────────────
    impact = None
    if rv is not None and td is not None:
        controls = td[[c for c in td.columns if c != cfg["search_term"]]]
        try:
            impact = causal.run(rv["reviews"], controls, (w0, w1))
        except causal.CausalError as e:
            st.warning(str(e))
    cm = _comments(cfg, yt_meta["id"] if yt_meta else None)
    counts, scores = (game.classify(cm) if cm is not None else (None, None))
    er, hook = game.hook_score(*(yt_meta.get(k) for k in ("views", "likes", "comments"))) if yt_meta else (None, None)

    # ── Tier 1: 요약 ──────────────────────────────────────────────────────
    st.markdown(t("##### 한눈에 보기", "##### At a glance"))
    c0, c1, c2, c3 = st.columns([1.4, 1, 1, 1])
    if scores:
        health = game.health_index(scores["lore"], scores["intent"], hook)
        c0.plotly_chart(_gauge(health), use_container_width=True)
        c0.caption(t(f"구간: {ZONE[game.zone(health)][0]}", f"Zone: {ZONE[game.zone(health)][1]}"))
    else:
        c0.info(t("댓글 데이터가 없어 건강도 지수를 계산하지 못했습니다.", "No comment data yet — health index unavailable."))
    if impact:
        c1.metric(t("스토어 유입 증분", "Incremental store lift"), f"{impact['rel_effect']:+.1%}",
                  t(f"p = {impact['p']:.3f}", f"p = {impact['p']:.3f}"), delta_color="off")
        rating = game.iroas_rating(impact["rel_effect"], impact["p"])
        c3.metric(t("프록시 iROAS 평가", "Proxy iROAS rating"), t(*IROAS[rating]),
                  t("집행비 대신 증분 크기와 유의성으로 판단", "Graded on lift and significance (no spend data)"),
                  delta_color="off")
    else:
        c1.metric(t("스토어 유입 증분", "Incremental store lift"), "—")
        c3.metric(t("프록시 iROAS 평가", "Proxy iROAS rating"), "—")
    c2.metric(t("세계관 몰입도 (Lore Score)", "Lore Score"), f"{scores['lore']:.0f} / 100" if scores else "—",
              t(f"구매·복귀 의도 {scores['intent']:.1f}%", f"Purchase/return intent {scores['intent']:.1f}%") if scores else None,
              delta_color="off")
    with st.expander(t("지표는 이렇게 계산했어요", "How these numbers are calculated")):
        st.markdown(t(
            """**캠페인 건강도 지수**는 세 가지를 섞어 0–100으로 만든 값입니다. 세계관 몰입도 40%, 구매·복귀 의도 30%(5배로 환산, 최대 100), Hook 점수 30%입니다. 30 이하는 클릭만 늘어난 상태, 31–70은 브랜드 인지가 오른 상태, 71 이상은 세계관에 빠진 유저가 실제로 들어오는 상태로 봅니다.

**세계관 몰입도**는 주제가 잡힌 댓글 가운데 쉐도우밀크, 비스트, 스토리, 4주년 같은 세계관 이야기를 하는 댓글의 비율입니다. **구매·복귀 의도**는 전체 댓글 중 "복귀했다", "현질", "came back", "pull" 같은 표현이 들어간 비율입니다.

**Hook 점수**는 (좋아요+댓글)/조회수를 업계 평균 수준인 4%와 비교한 값입니다. 진짜 Hook Rate(초반 시청 유지율)는 채널 운영자만 볼 수 있어서 공개 참여율로 대신했습니다.

**스토어 유입 증분**은 캠페인 기간 실제 리뷰 수를 '캠페인이 없었다면'의 예상치와 비교한 값이고(아래 그래프), **iROAS 평가**는 집행비를 몰라 금액 대신 증분 크기와 통계적 유의성으로 매겼습니다. 증분 20% 이상이면서 p < 0.05면 HIGH, 증분이 있으면서 p < 0.1이거나 10% 이상이면 MODERATE, 그 외는 LOW입니다.

댓글 분류는 한국어·영어 키워드 사전으로 합니다.""",
            """The **Campaign Health Index** blends three signals into a 0–100 score: Lore Score (40%), purchase/return intent (30%, scaled ×5 and capped at 100) and Hook score (30%). Up to 30 means clicks without much substance, 31–70 means brand awareness is rising, and above 70 means engaged fans are actually coming in.

**Lore Score** is the share of on-topic comments that talk about the game's world — Shadow Milk, the Beasts, the story, the 4th anniversary. **Purchase/return intent** is the share of all comments with phrases like "came back", "pull" or "복귀".

**Hook score** compares (likes + comments) / views with a 4% industry benchmark. True Hook Rate (early retention) is only visible to the channel owner, so public engagement stands in for it.

**Incremental store lift** compares actual reviews during the campaign with the no-campaign baseline (chart below). Without spend data, the **iROAS rating** is based on lift and significance instead of money: HIGH for 20%+ lift with p < 0.05, MODERATE for positive lift with p < 0.1 or 10%+ lift, LOW otherwise.

Comments are classified with a Korean/English keyword list."""))

    # ── Tier 2: 반사실 시계열 ─────────────────────────────────────────────
    st.markdown(t("##### 캠페인이 없었다면 리뷰는 얼마나 달렸을까", "##### Store reviews vs. a no-campaign baseline"))
    st.caption(t("원래 보고 싶었던 건 다운로드(설치) 수지만, 공개된 데이터로는 알 수 없어서 스토어에 새로 달린 리뷰 수를 대신 썼습니다.",
                 "What we really want is downloads (installs), but they aren't publicly available, so new store reviews stand in for them."))
    if impact:
        st.plotly_chart(_causal_chart(impact, t("실제 일별 스토어 리뷰", "Actual daily store reviews")), use_container_width=True)
        st.caption(t(f"캠페인 기간에는 하루 평균 {impact['avg_actual']:.0f}건의 리뷰가 달렸습니다. 캠페인이 없었다면 {impact['avg_pred']:.0f}건 정도였을 것으로 보여, "
                     f"기간 전체로 약 {impact['cum_effect']:,.0f}건이 더 달린 셈입니다 (95% 구간 {impact['cum_lo']:,.0f}–{impact['cum_hi']:,.0f}건, p = {impact['p']:.3f}).",
                     f"The store averaged {impact['avg_actual']:.0f} reviews a day during the campaign, versus about {impact['avg_pred']:.0f} expected without it — "
                     f"roughly {impact['cum_effect']:,.0f} extra reviews over the period (95% interval {impact['cum_lo']:,.0f}–{impact['cum_hi']:,.0f}, p = {impact['p']:.3f})."))
        with st.expander(t("어떻게 계산했나요?", "How was this calculated?")):
            ctrl = ", ".join(c for c in td.columns if c != cfg["search_term"])
            glob = cfg.get("store_scope") == "global"
            langs = ", ".join(lang for lang, _ in playstore.GLOBAL_LOCALES)
            scope_ko = f"글로벌 Play 스토어 리뷰 (10개 언어 합산: {langs})" if glob else "한국 Play 스토어"
            scope_en = f"the global Play Store (10 languages combined: {langs})" if glob else "the Korean Play Store"
            geo_ko, geo_en = ("전 세계", "worldwide") if not cfg.get("geo", "KR") else (cfg.get("geo"), cfg.get("geo"))
            ctrl_reason_ko = ("경쟁작의 글로벌 리뷰는 하루 수천 건이라 기간 전체 수집이 비현실적이어서 검색량으로 대체" if glob
                              else "한국 스토어의 경쟁작 리뷰는 하루 1건 미만이라 검색량으로 대체")
            ctrl_reason_en = ("competitors get thousands of global reviews per day, so collecting the full period isn't practical — search interest is used instead"
                              if glob else "competitor reviews in the Korean store are under 1/day, so search interest is used instead")
            st.markdown(t(
                f"""- **다운로드 프록시**: google-play-scraper로 모은 {app_name} {scope_ko}의 일별 신규 리뷰 수 (리뷰 수 ≈ α × 다운로드)
- **통제군 (Synthetic Control)**: 같은 기간 경쟁작·시장 검색 관심도({ctrl}, {geo_ko}) — {ctrl_reason_ko}
- **모델**: 로컬 레벨 + 주간 계절성 + 통제군 회귀의 구조 시계열(BSTS/CausalImpact 구성)을 캠페인 이전 구간으로 학습해 캠페인 기간의 가상 리뷰 수를 예측
- **주의**: 4주년 업데이트·인게임 이벤트가 같은 시기에 있어 순수 크리에이터 효과와 분리되지 않음. 리뷰 수는 다운로드의 근사치""",
                f"""- **Download proxy**: daily new {app_name} reviews from {scope_en} via google-play-scraper (reviews ≈ α × downloads)
- **Synthetic control**: competitor and market search interest over the same period ({ctrl}, {geo_en}) — {ctrl_reason_en}
- **Model**: structural time series (local level + weekly seasonality + control regression, the BSTS/CausalImpact setup) trained on the pre-campaign period to predict counterfactual reviews in the campaign window
- **Caveats**: the 4th-anniversary update and in-game events overlap the campaign, so the creator effect isn't isolated from them. Review counts only approximate downloads"""))
    elif rv is not None:
        st.line_chart(rv["reviews_ma7"])

    # ── Tier 3: 오디언스 반응 & 경쟁 분석 ─────────────────────────────────
    st.markdown(t("##### 유저 반응과 경쟁 구도", "##### Audience reaction & competition"))
    left, right = st.columns(2)
    with left:
        if counts is not None:
            st.plotly_chart(_treemap(counts), use_container_width=True)
            st.caption(t(f"트레일러 댓글 {scores['n']:,}개 기준입니다. 초록은 세계관·구매/복귀 반응, 회색은 일반 반응, 빨강은 부정 반응이에요.",
                         f"Based on {scores['n']:,} trailer comments. Green is lore and purchase/return talk, gray is general, red is negative."))
        else:
            st.info(t("트레일러 댓글이 아직 없습니다. 위에서 수집하거나 CSV를 올려 주세요.",
                      "No trailer comments yet. Collect them or upload a CSV above."))
    with right:
        if rv is not None and td is not None:
            s = game.sos(td, cfg["search_term"], cfg.get("rival_terms", []))
            lc = game.lag_corr(s, rv["reviews"])
            best = int(lc.loc[lc["corr"].idxmax(), "lag"]) if not lc.empty else 0
            pair = pd.concat([s.shift(best).rename("sos"), rv["reviews"]], axis=1).dropna()
            in_camp = (pair.index >= w0) & (pair.index <= w1)
            fig = go.Figure()
            for mask, name, color in [(~in_camp, t("평시", "Baseline days"), GRAY), (in_camp, t("캠페인 기간", "Campaign window"), BLUE)]:
                sub = pair[mask]
                fig.add_scatter(x=sub["sos"], y=sub["reviews"], mode="markers", name=name,
                                marker=dict(size=7, color=color, opacity=0.75, line=dict(color="white", width=1)),
                                customdata=sub.index.strftime("%Y-%m-%d"),
                                hovertemplate="%{customdata}<br>SOS %{x:.0%} → " + t("리뷰", "reviews") + " %{y}<extra></extra>")
            fig.update_xaxes(title=t(f"Share of Search ({best}일 전)", f"Share of Search ({best} days earlier)"), tickformat=".0%")
            fig.update_yaxes(title=t("일별 신규 리뷰", "Daily new reviews"))
            fig.update_layout(hovermode="closest")
            style(fig, 380, t(f"검색 점유율이 오르면 리뷰도 늘었을까 (시차 {best}일, r = {lc['corr'].max():.2f})",
                              f"Does share of search lead store reviews? (lag {best} days, r = {lc['corr'].max():.2f})"))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(t(f"검색 점유율은 '{cfg['search_term']}' 검색량을 경쟁작까지 합친 검색량으로 나눈 값입니다. 0–21일 시차 중 리뷰와 가장 잘 맞는 시차를 골랐습니다.",
                         f"Share of search is '{cfg['search_term']}' searches divided by searches for it plus competitors. "
                         "The lag (0–21 days) that best matches reviews is shown."))

    # ── 캠페인 소재 ───────────────────────────────────────────────────────
    st.markdown(t("##### 캠페인 소재", "##### Creatives"))
    shown = [k for k in ("main", "competitor", "other") if k in slots]
    cols = st.columns(len(shown) or 1)
    for col, key in zip(cols, shown):
        s, m = slots[key]
        slot_er = game.hook_score(m.get("views"), m.get("likes"), m.get("comments"))[0]
        with col:
            img = image_bytes(m["thumbnail"]) if m.get("thumbnail") else None
            if img:
                st.image(img, width="stretch")
            fmt = lambda v: f"{v:,.0f}" if v is not None else "—"  # noqa: E731
            st.markdown(f"**{slot_name(s, m)}** · {m.get('published') or '—'}  \n"
                        + t(f"조회수 {fmt(m.get('views'))} · 좋아요 {fmt(m.get('likes'))} · 댓글 {fmt(m.get('comments'))}",
                            f"Views {fmt(m.get('views'))} · Likes {fmt(m.get('likes'))} · Comments {fmt(m.get('comments'))}")
                        + (t(f" · 참여율 {slot_er:.2%}", f" · Engagement {slot_er:.2%}") if slot_er else ""))
            st.caption(m.get("title") or "")
    if tmeta:
        st.caption(t(f"데이터: Google Play 리뷰, Google Trends ({tmeta['fetched_at']} 기준), YouTube·Instagram 공개 지표",
                     f"Data: Google Play reviews, Google Trends (as of {tmeta['fetched_at']}), YouTube and Instagram public metrics"))
