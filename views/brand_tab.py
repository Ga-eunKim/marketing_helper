"""브랜드 및 소비자 영향 — YouTube 댓글 수집 + 텍스트 분석."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import cache, cached
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
    """분석 설정 안에 그대로 표시 (expander 안에 expander를 둘 수 없음)."""
    st.markdown(t("**분류 사전**", "**Classification lexicon**"))
    lex = {}
    cols = st.columns(3)
    for col, (key, ko, en) in zip(cols, [("purchase", "구매 의향 표현", "Purchase-intent terms"),
                                         ("positive", "긍정 표현", "Positive terms"), ("negative", "부정 표현", "Negative terms")]):
        txt = col.text_area(t(ko, en), ", ".join(ta.DEFAULT_LEXICON[key]), key=f"lex_{key}", height=110)
        lex[key] = kw_list(txt)
    st.caption(t("댓글에 이 표현이 들어 있으면 해당 지표로 셉니다. '안 좋'처럼 부정어가 붙은 칭찬은 부정으로 봅니다.",
                 "A comment counts toward a metric if it contains any of these terms. Negated praise (e.g. 'not good') counts as negative."))
    return lex


def render():
    st.markdown(t("#### 댓글로 본 브랜드 반응", "#### What Viewers Are Saying"))
    st.caption(t("유튜브 공개 댓글에서 구매 의향, 긍정 반응, 광고 메시지 언급이 얼마나 나오는지 고객사와 경쟁사를 비교했습니다.",
                 "How often public YouTube comments show purchase intent, positive sentiment and recall of the ad message — client vs. competitor."))
    indicators = _indicators()
    net_label = t("순선호 (긍정−부정)", "Net sentiment (positive − negative)")
    slots = connected_slots()
    yt = [(s, m) for s, m in slots if m["platform"] == "YouTube" and m.get("kind") != "channel"]
    notes = []
    for s, m in slots:
        if m.get("kind") == "channel":
            notes.append(t(f"{slot_name(s, m)}는 채널 URL이라 제외했습니다. 영상 URL을 넣으면 함께 분석됩니다.",
                           f"{slot_name(s, m)} is a channel URL, so it's left out. Add a video URL to include it."))
        elif m["platform"] != "YouTube":
            notes.append(t(f"{slot_name(s, m)} 댓글은 로그인 없이 볼 수 없어 제외했습니다 (공개 댓글 수 {m.get('comments') or '—'}개).",
                           f"{slot_name(s, m)} comments need a login, so they're left out ({m.get('comments') or '—'} public comments)."))
    if not yt:
        st.info(t("연동된 YouTube 영상이 없습니다.", "No YouTube video connected."))
        return
    results_area = st.container()  # 결과를 위에, 설정은 아래 접힌 패널에

    with st.expander(t("분석 설정 · 댓글 수집", "Settings & comment collection")):
        c1, c2, c3 = st.columns([2, 1, 1])
        # 슬라이더는 라벨이 바뀌면 새 위젯이 되므로 언어별 키 + 직전 값 유지
        limit = c1.slider(t("영상별 최대 댓글 수", "Max comments per video"), 100, 2000,
                          st.session_state.get("cm_limit_val", 500), 100, key=f"cm_limit_{lang()}")
        st.session_state.cm_limit_val = limit
        sort = c2.selectbox(t("정렬", "Sort"), list(cm.SORTS), key=f"cm_sort_{lang()}",
                            format_func=lambda x, en=lang() == "EN": SORT_EN.get(x, x) if en else x)
        c3.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
        if c3.button(t("댓글 새로 수집", "Re-collect comments"), key="cm_run"):
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
                    hit = cached.comments_any(m["id"], limit, sort)
                    if hit is not None:
                        st.session_state.comment_data[s["key"]] = hit
        missing = [(s, m) for s, m in yt if st.session_state.comment_data.get(s["key"]) is None]
        if missing:  # YouTube가 수집을 막을 때: 외부 도구로 받은 댓글 CSV로 대체
            st.caption(t("YouTube가 수집을 막으면 TheYouTubeTool 등에서 받은 댓글 CSV를 올려도 됩니다.",
                         "If YouTube blocks collection, upload a comments CSV from a tool like TheYouTubeTool."))
            for s, m in missing:
                up = st.file_uploader(f"{slot_name(s, m)} · {(m.get('title') or '')[:50]}", type=["csv"], key=f"cm_csv_{s['key']}")
                if up is not None:
                    try:
                        df = cm.from_csv(up, m["id"])
                        cache.put("comments", (m["id"], limit, sort), df)
                        st.session_state.comment_data[s["key"]] = df
                        st.success(t(f"댓글 {len(df):,}개를 불러왔습니다.", f"Loaded {len(df):,} comments."))
                    except Exception as e:
                        st.error(str(e))

        st.markdown(t("**제외할 댓글**", "**Comments to exclude**"))
        e1, e2, e3 = st.columns([1, 1, 2])
        excl_owner = e1.checkbox(t("광고주 본인 댓글", "Advertiser's own comments"), True, key="ex_owner")
        excl_reply = e2.checkbox(t("답글", "Replies"), False, key="ex_reply")
        use_range = e3.checkbox(t("특정 기간에 달린 댓글", "Comments from a specific period"), False, key="ex_range_on")
        ev_range = None
        if use_range:
            ev_range = e3.date_input(t("제외할 기간", "Period to exclude"), (date(2026, 9, 16), date(2026, 10, 18)), key="ex_range")
            if not (isinstance(ev_range, (tuple, list)) and len(ev_range) == 2):
                ev_range = None
        pattern = st.text_input(t("이벤트 응모 문구 (정규식, 선택)", "Contest-entry phrase (regex, optional)"), "", key="ex_pattern",
                                placeholder=t("예: 득[!.]?\\s*$", "e.g. 득[!.]?\\s*$"))
        lex = _lexicon_editor()

    results, metas, tagged_all = [], [], {}
    for s, m in yt:
        raw = st.session_state.comment_data.get(s["key"])
        if raw is None:
            continue
        df, log = ta.apply_exclusions(raw, m.get("channel_id"), excl_owner, excl_reply, ev_range, pattern.strip() or None)
        res, tagged = ta.analyze(df, lex, kw_list(m.get("msg_kw")))
        tagged_all[s["key"]] = (s, m, tagged)
        metas.append({
            t("영상", "Video"): slot_name(s, m),
            t("분석 댓글", "Analyzed"): res["n"],
            t("수집 댓글", "Collected"): len(raw),
            t("작성 기간", "Posted"): f"{raw['date'].min():%Y-%m-%d} ~ {raw['date'].max():%Y-%m-%d}" if len(raw) else "—",
            t("제외", "Excluded"): " / ".join(log) or t("없음", "None"),
            t("수집 시각", "Collected at"): raw.attrs.get("fetched_at", "—"),
            t("출처", "Source"): m["url"],
        })
        if res["n"]:
            for key, label in indicators:
                results.append({"key": s["key"], "campaign": slot_name(s, m), "metric": label, "rate": res[key]["rate"],
                                "lo": res[key]["lo"], "hi": res[key]["hi"], "k": res[key]["k"], "n": res["n"]})
            results.append({"key": s["key"], "campaign": slot_name(s, m), "metric": net_label,
                            "rate": res["net_preference"], "lo": None, "hi": None,
                            "k": res["negative"]["k"], "n": res["n"]})

    with results_area:
        if not metas:
            st.info(t("아직 댓글이 없습니다. 아래 '분석 설정 · 댓글 수집'에서 댓글을 수집하거나 CSV를 올려 주세요.",
                      "No comments yet. Collect them or upload a CSV under 'Settings & comment collection' below."))
            return
        res_df = pd.DataFrame(results)
        if res_df.empty:
            st.warning(t("제외 조건을 적용하고 나니 남은 댓글이 없습니다.", "No comments are left after the exclusions."))
        else:
            bars = res_df[res_df["metric"] != net_label]
            fig = go.Figure()
            for key, grp in bars.groupby("key", sort=False):
                fig.add_bar(x=grp["metric"], y=grp["rate"], name=f"{grp['campaign'].iloc[0]} (n={grp['n'].iloc[0]:,})",
                            marker=dict(color=SLOT_COLORS[key], cornerradius=4),
                            error_y=dict(type="data", symmetric=False, array=grp["hi"] - grp["rate"],
                                         arrayminus=grp["rate"] - grp["lo"], thickness=1.5, width=4),
                            text=grp["rate"].map(lambda v: f"{v:.1%}"), textposition="outside",
                            customdata=grp[["k", "n"]],
                            hovertemplate="%{x}: %{y:.1%} (%{customdata[0]}/%{customdata[1]})<extra>%{fullData.name}</extra>")
            fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, hovermode="closest")
            fig.update_yaxes(tickformat=".0%", title=t("해당 댓글 비율", "Share of comments"))
            style(fig, 380)
            st.plotly_chart(fig, use_container_width=True)
            campaign_col = t("영상", "Video")
            pivot = res_df.pivot_table(index="campaign", columns="metric", values="rate", sort=False).reset_index()
            pivot = pivot.rename(columns={"campaign": campaign_col})
            pivot.columns.name = None
            st.dataframe(pivot, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="percent") for c in pivot.columns if c != campaign_col})
            small = [m for m in metas if m[t("분석 댓글", "Analyzed")] < 100]
            st.caption(t("댓글을 직접 남긴 시청자 기준이라 실제 구매와는 다를 수 있습니다. 막대 위 선은 95% 신뢰구간입니다."
                         + (" 댓글이 100개 미만인 영상은 차이를 방향 정도로만 보세요." if small else ""),
                         "Based on viewers who chose to comment, so it may not match actual purchases. Lines on the bars show 95% intervals."
                         + (" Treat differences for videos with under 100 comments as directional only." if small else "")))

        with st.expander(t("대표 댓글 보기", "Sample comments")):
            vids = [(s, m, tg) for s, m, tg in tagged_all.values() if not tg.empty]
            vtabs = st.tabs([slot_name(s, m) for s, m, _ in vids]) if vids else []
            for vtab, (s, m, tagged) in zip(vtabs, vids):
                with vtab:
                    tabs = st.tabs([label for _, label in indicators] + [t("부정", "Negative"), t("자주 나온 단어", "Top words")])
                    for tab, (col, _) in zip(tabs, indicators + [("negative", "")]):
                        ex = tagged[tagged[col]].sort_values("votes", ascending=False).head(5)
                        with tab:
                            if ex.empty:
                                st.caption(t("해당 댓글이 없습니다.", "No matching comments."))
                            for r in ex.itertuples():
                                st.markdown(f"> {r.text[:200]}  \n<span style='color:gray;font-size:12px'>👍 {r.votes}</span>",
                                            unsafe_allow_html=True)
                    with tabs[-1]:
                        st.dataframe(ta.top_terms(tagged["text"]), hide_index=True)

        with st.expander(t("수집 정보", "Data details")):
            st.dataframe(pd.DataFrame(metas), hide_index=True, width="stretch")
            for n in notes:
                st.caption(n)
