"""브랜드 및 소비자 영향 — YouTube 댓글 수집 + 텍스트 분석."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import comments as cm
from core import text_analysis as ta
from core.charts import SLOT_COLORS, style
from core import cached
from views.common import connected_slots, kw_list, slot_name

INDICATORS = [("purchase", "구매 의향"), ("positive", "브랜드 선호 (긍정)"), ("message", "광고 메시지 연상")]


def _lexicon_editor() -> dict:
    with st.expander("분석 사전 (수정 가능)"):
        lex = {}
        for key, label in [("purchase", "구매 의향 표현"), ("positive", "긍정 표현"), ("negative", "부정 표현")]:
            txt = st.text_area(label, ", ".join(ta.DEFAULT_LEXICON[key]), key=f"lex_{key}", height=80)
            lex[key] = kw_list(txt)
        st.caption("댓글에 해당 표현이 포함되면 그 지표로 분류(부분 문자열 일치). '안 좋', '좋지 않' 등 부정 수식은 부정으로 처리.")
    return lex


def render():
    st.markdown("#### 브랜드·소비자 반응 (YouTube 댓글 텍스트 분석)")
    slots = connected_slots()
    yt = [(s, m) for s, m in slots if m["platform"] == "YouTube" and m.get("kind") != "channel"]
    for s, m in slots:
        if m.get("kind") == "channel":
            st.caption(f"ℹ️ {slot_name(s, m)}: 채널 URL로 등록되어 있어 댓글 분석에서 제외됩니다 (영상 URL을 넣으면 분석됩니다).")
    for s, m in slots:
        if m["platform"] != "YouTube":
            st.caption(f"ℹ️ {slot_name(s, m)}: Instagram 댓글 본문은 로그인 없이 수집할 수 없어 분석에서 제외됩니다 (공개 댓글 수 {m.get('comments') or '—'}).")
    if not yt:
        st.info("연동된 YouTube 캠페인이 없습니다 — 데이터 미등록.")
        return

    c1, c2 = st.columns(2)
    limit = c1.slider("슬롯별 최대 수집 댓글 수", 100, 2000, 500, 100, key="cm_limit")
    sort = c2.selectbox("정렬", list(cm.SORTS), key="cm_sort")
    if st.button("댓글 새로 수집", type="primary", key="cm_run"):
        for s, m in yt:
            with st.spinner(f"{slot_name(s, m)} 댓글 수집 중…"):
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

    st.markdown("**이벤트 영향 제외**")
    e1, e2, e3 = st.columns([1, 1, 2])
    excl_owner = e1.checkbox("광고주 본인 댓글 제외", True, key="ex_owner")
    excl_reply = e2.checkbox("답글 제외", False, key="ex_reply")
    use_range = e3.checkbox("특정 이벤트 기간 댓글 제외", False, key="ex_range_on")
    ev_range = None
    if use_range:
        ev_range = e3.date_input("이벤트 기간", (date(2026, 9, 16), date(2026, 10, 18)), key="ex_range")
        if not (isinstance(ev_range, (tuple, list)) and len(ev_range) == 2):
            ev_range = None
    pattern = st.text_input("이벤트 응모 댓글 패턴 제외 (정규식, 선택)", "", key="ex_pattern",
                            placeholder="예: 득[!.]?\\s*$  (댓글 이벤트 응모 문구로 끝나는 댓글)")
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
            "캠페인": slot_name(s, m), "표본 수(분석)": res["n"], "수집 댓글": len(raw),
            "수집 기간(작성일 추정)": f"{raw['date'].min():%Y-%m-%d} ~ {raw['date'].max():%Y-%m-%d}" if len(raw) else "—",
            "수집 방식": f"공개 댓글 {sort} 상위 {limit}개 (자기선택 표본)",
            "이벤트 제외": " / ".join(log) or "미적용",
            "출처": f"YouTube 공개 댓글 ({m['url']})",
            "수집 시각": raw.attrs.get("fetched_at", "—"),
        })
        if res["n"]:
            for key, label in INDICATORS:
                results.append({"key": s["key"], "캠페인": slot_name(s, m), "지표": label, "비율": res[key]["rate"],
                                "lo": res[key]["lo"], "hi": res[key]["hi"], "해당 댓글 수": res[key]["k"], "n": res["n"]})
            results.append({"key": s["key"], "캠페인": slot_name(s, m), "지표": "순선호 (긍정−부정)",
                            "비율": res["net_preference"], "lo": None, "hi": None,
                            "해당 댓글 수": res["negative"]["k"], "n": res["n"]})

    if not metas:
        st.info("데이터 미등록 — [댓글 수집]을 눌러 공개 댓글을 수집하세요. (수집 전에는 어떤 값도 표시하지 않습니다)")
        return
    res_df = pd.DataFrame(results)
    meta_df = pd.DataFrame(metas)
    fig = None
    if res_df.empty:
        st.warning("제외 조건 적용 후 분석할 댓글이 남지 않았습니다 — 데이터 미등록.")
    else:
        bars = res_df[res_df["지표"] != "순선호 (긍정−부정)"]
        fig = go.Figure()
        for key, grp in bars.groupby("key", sort=False):
            fig.add_bar(x=grp["지표"], y=grp["비율"], name=grp["캠페인"].iloc[0],
                        marker=dict(color=SLOT_COLORS[key], cornerradius=4),
                        error_y=dict(type="data", symmetric=False, array=grp["hi"] - grp["비율"],
                                     arrayminus=grp["비율"] - grp["lo"], thickness=1.5, width=4),
                        text=grp["비율"].map(lambda v: f"{v:.1%}"), textposition="outside",
                        customdata=grp[["해당 댓글 수", "n"]],
                        hovertemplate="%{x}: %{y:.1%} (%{customdata[0]}/%{customdata[1]})<extra>%{fullData.name}</extra>")
        fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, hovermode="closest")
        fig.update_yaxes(tickformat=".0%", title="해당 표현 포함 댓글 비율 (95% CI)")
        style(fig, 400)
        st.plotly_chart(fig, use_container_width=True)
        if res_df["key"].nunique() < 2:
            st.caption("경쟁사 YouTube 캠페인 URL을 상단 바에 연동하면 고객사·경쟁사를 같은 그래프에서 비교합니다.")
        pivot = res_df.pivot_table(index="캠페인", columns="지표", values="비율").reset_index()
        st.dataframe(pivot, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="percent") for c in pivot.columns if c != "캠페인"})

    st.markdown("**조사(수집) 정보**")
    st.dataframe(meta_df, hide_index=True, width="stretch")
    st.warning("댓글은 **자발적으로 글을 남긴 시청자의 반응(자기선택 표본)**이며 실제 구매·전환과 다를 수 있습니다. "
               "특히 댓글 이벤트가 진행된 영상은 응모 댓글이 긍정·메시지 연상 비율을 크게 부풀립니다 — 위 '이벤트 영향 제외'로 비교해 보세요. "
               "사전 기반 분류는 반어·맥락을 놓칠 수 있습니다.")

    for key, (s, m, tagged) in tagged_all.items():
        if tagged.empty:
            continue
        with st.expander(f"대표 댓글 · 상위 키워드 — {slot_name(s, m)}"):
            tabs = st.tabs([label for _, label in INDICATORS] + ["부정", "상위 키워드"])
            for tab, (col, _) in zip(tabs, INDICATORS + [("negative", "")]):
                ex = tagged[tagged[col]].sort_values("votes", ascending=False).head(5)
                with tab:
                    if ex.empty:
                        st.caption("해당 댓글 없음")
                    for r in ex.itertuples():
                        st.markdown(f"> {r.text[:200]}  \n<span style='color:gray;font-size:12px'>👍 {r.votes} · 매칭: {r.matched}</span>",
                                    unsafe_allow_html=True)
            with tabs[-1]:
                st.dataframe(ta.top_terms(tagged["text"]), hide_index=True)
