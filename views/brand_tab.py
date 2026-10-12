"""브랜드 및 소비자 영향 — YouTube 댓글 수집 + 텍스트 분석."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import cached
from core import comments as cm
from core import text_analysis as ta
from core.charts import SLOT_COLORS, style
from core.i18n import lang, t
from views.common import connected_slots, kw_list, slot_name

SORT_EN = {"최신순": "Newest", "인기순": "Top"}


def _indicators() -> list[tuple[str, str]]:
    return [("purchase", t("구매 의향", "Purchase intent")),
            ("positive", t("브랜드 선호 (긍정)", "Brand favorability (positive)")),
            ("message", t("광고 메시지 연상", "Ad message recall"))]


def _lexicon_editor() -> dict:
    with st.expander(t("분석 사전 (수정 가능)", "Classification lexicon (editable · Korean terms)")):
        lex = {}
        for key, ko, en in [("purchase", "구매 의향 표현", "Purchase-intent terms"),
                            ("positive", "긍정 표현", "Positive terms"), ("negative", "부정 표현", "Negative terms")]:
            txt = st.text_area(t(ko, en), ", ".join(ta.DEFAULT_LEXICON[key]), key=f"lex_{key}", height=80)
            lex[key] = kw_list(txt)
        st.caption(t("댓글에 해당 표현이 포함되면 그 지표로 분류(부분 문자열 일치). '안 좋', '좋지 않' 등 부정 수식은 부정으로 처리.",
                     "A comment counts toward a metric if it contains any listed term (substring match). "
                     "Negated positives (e.g. '안 좋', '좋지 않') count as negative."))
    return lex


def render():
    st.markdown(t("#### 브랜드·소비자 반응 (YouTube 댓글 텍스트 분석)", "#### Brand & Consumer Sentiment (YouTube Comment Analysis)"))
    indicators = _indicators()
    net_label = t("순선호 (긍정−부정)", "Net sentiment (positive − negative)")
    slots = connected_slots()
    yt = [(s, m) for s, m in slots if m["platform"] == "YouTube" and m.get("kind") != "channel"]
    for s, m in slots:
        if m.get("kind") == "channel":
            st.caption(t(f"ℹ️ {slot_name(s, m)}: 채널 URL로 등록되어 있어 댓글 분석에서 제외됩니다 (영상 URL을 넣으면 분석됩니다).",
                         f"ℹ️ {slot_name(s, m)}: set as a channel URL, so it's excluded from comment analysis (use a video URL)."))
    for s, m in slots:
        if m["platform"] != "YouTube":
            st.caption(t(f"ℹ️ {slot_name(s, m)}: Instagram 댓글 본문은 로그인 없이 수집할 수 없어 분석에서 제외됩니다 (공개 댓글 수 {m.get('comments') or '—'}).",
                         f"ℹ️ {slot_name(s, m)}: Instagram comment text requires login, so it's excluded (public comment count {m.get('comments') or '—'})."))
    if not yt:
        st.info(t("연동된 YouTube 캠페인이 없습니다 — 데이터 미등록.", "No YouTube campaign connected — no data."))
        return

    c1, c2 = st.columns(2)
    # 슬라이더는 라벨이 바뀌면 새 위젯이 되므로 언어별 키 + 직전 값 유지
    limit = c1.slider(t("슬롯별 최대 수집 댓글 수", "Max comments per campaign"), 100, 2000,
                      st.session_state.get("cm_limit_val", 500), 100, key=f"cm_limit_{lang()}")
    st.session_state.cm_limit_val = limit
    sort = c2.selectbox(t("정렬", "Sort"), list(cm.SORTS), key=f"cm_sort_{lang()}",
                        format_func=lambda x, en=lang() == "EN": SORT_EN.get(x, x) if en else x)
    if st.button(t("댓글 새로 수집", "Re-collect comments"), type="primary", key="cm_run"):
        for s, m in yt:
            with st.spinner(t(f"{slot_name(s, m)} 댓글 수집 중…", f"Collecting {slot_name(s, m)} comments…")):
                try:
                    st.session_state.comment_data[s["key"]] = cached.comments(m["id"], limit, sort, refresh=True)
                except cm.CommentError as e:
                    st.session_state.comment_data[s["key"]] = None
                    st.error(f"{slot_name(s, m)}: {e}")
    else:
        for s, m in yt:  # 저장된 수집 결과가 있으면 바로 표시 (네트워크 요청 없음)
            if st.session_state.comment_data.get(s["key"]) is None:
                hit = cached.comments_if_cached(m["id"], limit, sort)
                if hit is not None:
                    st.session_state.comment_data[s["key"]] = hit

    st.markdown(t("**이벤트 영향 제외**", "**Exclude event effects**"))
    e1, e2, e3 = st.columns([1, 1, 2])
    excl_owner = e1.checkbox(t("광고주 본인 댓글 제외", "Exclude advertiser's own comments"), True, key="ex_owner")
    excl_reply = e2.checkbox(t("답글 제외", "Exclude replies"), False, key="ex_reply")
    use_range = e3.checkbox(t("특정 이벤트 기간 댓글 제외", "Exclude comments posted during an event window"), False, key="ex_range_on")
    ev_range = None
    if use_range:
        ev_range = e3.date_input(t("이벤트 기간", "Event window"), (date(2026, 9, 16), date(2026, 10, 18)), key="ex_range")
        if not (isinstance(ev_range, (tuple, list)) and len(ev_range) == 2):
            ev_range = None
    pattern = st.text_input(t("이벤트 응모 댓글 패턴 제외 (정규식, 선택)", "Exclude contest-entry comments (regex, optional)"), "",
                            key="ex_pattern",
                            placeholder=t("예: 득[!.]?\\s*$  (댓글 이벤트 응모 문구로 끝나는 댓글)",
                                          "e.g. 득[!.]?\\s*$  (comments ending with the contest-entry phrase)"))
    lex = _lexicon_editor()

    results, metas, tagged_all = [], [], {}
    for s, m in yt:
        raw = st.session_state.comment_data.get(s["key"])
        if raw is None:
            continue
        df, log = ta.apply_exclusions(raw, m.get("channel_id"), excl_owner, excl_reply, ev_range, pattern.strip() or None)
        res, tagged = ta.analyze(df, lex, kw_list(m.get("msg_kw")))
        tagged_all[s["key"]] = (s, m, tagged)
        sort_label = t(sort, SORT_EN.get(sort, sort))
        metas.append({
            t("캠페인", "Campaign"): slot_name(s, m),
            t("표본 수(분석)", "Sample size (analyzed)"): res["n"],
            t("수집 댓글", "Comments collected"): len(raw),
            t("수집 기간(작성일 추정)", "Collection window (est. post dates)"):
                f"{raw['date'].min():%Y-%m-%d} ~ {raw['date'].max():%Y-%m-%d}" if len(raw) else "—",
            t("수집 방식", "Method"): t(f"공개 댓글 {sort_label} 상위 {limit}개 (자기선택 표본)",
                                      f"Public comments, {sort_label}, up to {limit} (self-selected sample)"),
            t("이벤트 제외", "Event exclusion"): " / ".join(log) or t("미적용", "None"),
            t("출처", "Source"): t(f"YouTube 공개 댓글 ({m['url']})", f"YouTube public comments ({m['url']})"),
            t("수집 시각", "Collected at"): raw.attrs.get("fetched_at", "—"),
        })
        if res["n"]:
            for key, label in indicators:
                results.append({"key": s["key"], "campaign": slot_name(s, m), "metric": label, "rate": res[key]["rate"],
                                "lo": res[key]["lo"], "hi": res[key]["hi"], "k": res[key]["k"], "n": res["n"]})
            results.append({"key": s["key"], "campaign": slot_name(s, m), "metric": net_label,
                            "rate": res["net_preference"], "lo": None, "hi": None,
                            "k": res["negative"]["k"], "n": res["n"]})

    if not metas:
        st.info(t("데이터 미등록 — [댓글 새로 수집]을 눌러 공개 댓글을 수집하세요. (수집 전에는 어떤 값도 표시하지 않습니다)",
                  "No data yet — click [Re-collect comments] to collect public comments. (Nothing is shown until data is collected.)"))
        return
    res_df = pd.DataFrame(results)
    meta_df = pd.DataFrame(metas)
    if res_df.empty:
        st.warning(t("제외 조건 적용 후 분석할 댓글이 남지 않았습니다 — 데이터 미등록.",
                     "No comments left after applying the exclusions — no data."))
    else:
        bars = res_df[res_df["metric"] != net_label]
        fig = go.Figure()
        for key, grp in bars.groupby("key", sort=False):
            fig.add_bar(x=grp["metric"], y=grp["rate"], name=grp["campaign"].iloc[0],
                        marker=dict(color=SLOT_COLORS[key], cornerradius=4),
                        error_y=dict(type="data", symmetric=False, array=grp["hi"] - grp["rate"],
                                     arrayminus=grp["rate"] - grp["lo"], thickness=1.5, width=4),
                        text=grp["rate"].map(lambda v: f"{v:.1%}"), textposition="outside",
                        customdata=grp[["k", "n"]],
                        hovertemplate="%{x}: %{y:.1%} (%{customdata[0]}/%{customdata[1]})<extra>%{fullData.name}</extra>")
        fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, hovermode="closest")
        fig.update_yaxes(tickformat=".0%", title=t("해당 표현 포함 댓글 비율 (95% CI)", "Share of comments with matching terms (95% CI)"))
        style(fig, 400)
        st.plotly_chart(fig, use_container_width=True)
        if res_df["key"].nunique() < 2:
            st.caption(t("경쟁사 YouTube 캠페인 URL을 연동하면 고객사·경쟁사를 같은 그래프에서 비교합니다.",
                         "Connect a competitor YouTube campaign URL to benchmark client vs. competitor on the same chart."))
        campaign_col = t("캠페인", "Campaign")
        pivot = res_df.pivot_table(index="campaign", columns="metric", values="rate", sort=False).reset_index()
        pivot = pivot.rename(columns={"campaign": campaign_col})
        pivot.columns.name = None
        st.dataframe(pivot, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="percent") for c in pivot.columns if c != campaign_col})

    st.markdown(t("**조사(수집) 정보**", "**Data collection details**"))
    st.dataframe(meta_df, hide_index=True, width="stretch")
    st.warning(t("댓글은 **자발적으로 글을 남긴 시청자의 반응(자기선택 표본)**이며 실제 구매·전환과 다를 수 있습니다. "
                 "특히 댓글 이벤트가 진행된 영상은 응모 댓글이 긍정·메시지 연상 비율을 크게 부풀립니다 — 위 '이벤트 영향 제외'로 비교해 보세요. "
                 "사전 기반 분류는 반어·맥락을 놓칠 수 있습니다.",
                 "Comments come from **viewers who chose to post (a self-selected sample)** and may not reflect actual purchases or conversions. "
                 "Videos that ran comment contests show inflated favorability and message recall from entry comments — compare using "
                 "'Exclude event effects' above. Lexicon-based classification can miss sarcasm and context."))

    for key, (s, m, tagged) in tagged_all.items():
        if tagged.empty:
            continue
        with st.expander(t(f"대표 댓글 · 상위 키워드 — {slot_name(s, m)}", f"Sample comments & top keywords — {slot_name(s, m)}")):
            tabs = st.tabs([label for _, label in indicators] + [t("부정", "Negative"), t("상위 키워드", "Top keywords")])
            for tab, (col, _) in zip(tabs, indicators + [("negative", "")]):
                ex = tagged[tagged[col]].sort_values("votes", ascending=False).head(5)
                with tab:
                    if ex.empty:
                        st.caption(t("해당 댓글 없음", "No matching comments"))
                    for r in ex.itertuples():
                        st.markdown(f"> {r.text[:200]}  \n<span style='color:gray;font-size:12px'>👍 {r.votes} · "
                                    f"{t('매칭', 'matched')}: {r.matched}</span>", unsafe_allow_html=True)
            with tabs[-1]:
                st.dataframe(ta.top_terms(tagged["text"]), hide_index=True)
