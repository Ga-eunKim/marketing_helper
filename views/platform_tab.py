"""④ 타 플랫폼 성과 및 어트리뷰션 비교."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import normalize as nz
from core.charts import SLOT_COLORS, style
from views.common import connected_slots, put_report, slot_name

INSIGHT_TITLE = "겹치는 타겟을 제외하고 진짜 지갑을 열게 만든 채널은 어디인가?"

ATTRIBUTION_DEFAULT = pd.DataFrame([
    {"매체": "YouTube (Google Ads)", "전환 정의": "Google Ads 전환 액션 (구매·구독 신청 등)",
     "조회 기준": "광고: 30초 이상(짧으면 끝까지) 시청 또는 상호작용 / 공개 조회수: 오가닉 포함 누적",
     "클릭 기준": "광고 클릭", "기여 기간": "클릭 30일 · 참여 조회 3일 (기본값)", "어트리뷰션 모델": "데이터 기반 (DDA)"},
    {"매체": "Instagram (Meta)", "전환 정의": "Meta 픽셀/전환 API 이벤트",
     "조회 기준": "릴스 재생 수 (비로그인 수집 불가)", "클릭 기준": "링크 클릭",
     "기여 기간": "클릭 7일 · 조회 1일 (기본값)", "어트리뷰션 모델": "Meta 기본 (전환 시점 기준 보고)"},
])

COMPARABILITY = pd.DataFrame([
    ("조회수", "⚠️ 비교 제한", "YouTube 공개 조회수(오가닉 포함)와 Instagram 재생 수는 집계 기준이 다르며, Instagram은 비로그인 수집 불가"),
    ("좋아요", "△ 참고용", "두 매체 모두 공개 수치이나 노출 규모·알고리즘이 달라 절대값 비교는 제한적"),
    ("댓글 수", "⚠️ 비교 제한", "이벤트(댓글 응모) 여부에 크게 좌우됨. YouTube는 수집 표본 수"),
    ("참여율", "⚠️ 비교 제한", "Instagram 조회수 부재로 산출 불가"),
    ("클릭·비용·전환·CVR·CPA", "⚠️ 비교 제한", "YouTube는 Google Ads CSV 업로드 시에만 제공, Instagram은 링크로 수집 불가. 기여 기간·모델이 달라 직접 비교 시 주의"),
], columns=["지표", "비교 가능성", "사유"])


def _channel_rows() -> list[dict]:
    rows = []
    for s, m in connected_slots():
        r = nz.link_metrics_row(slot_name(s, m), m)
        r["_key"] = s["key"]
        r["_role"] = s["role"]
        ads = st.session_state.ads.get(s["key"])
        agg = nz.ads_summary(ads) if ads is not None and not ads.empty else {}
        for k, label in [("impressions", "노출"), ("reach", "도달"), ("clicks", "클릭"), ("cost", "비용(KRW)"),
                         ("conversions", "전환"), ("cvr", "CVR"), ("cpa", "CPA")]:
            r[label] = agg.get(k)
        rows.append(r)
    return rows


def render():
    st.subheader("타 플랫폼 성과 비교")
    rows = _channel_rows()
    if not rows:
        st.info("연동된 캠페인이 없습니다.")
        return
    df = pd.DataFrame(rows)
    show = df.drop(columns=["_key", "_role", "데이터 출처", "수집 시각"])
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={"참여율": st.column_config.NumberColumn(format="percent"),
                                "CVR": st.column_config.NumberColumn(format="percent")})
    st.caption("‘—’ = 링크로 수집 불가(또는 Google Ads CSV 미업로드). 값을 임의로 채우지 않습니다.")

    figs = []
    cols = st.columns(2)
    for col, metric in zip(cols, ["좋아요", "조회수"]):
        sub = df[df[metric].notna()]
        if sub.empty:
            col.caption(f"{metric}: 비교 가능한 데이터 없음")
            continue
        fig = go.Figure(go.Bar(x=sub["슬롯"], y=sub[metric],
                               marker=dict(color=[SLOT_COLORS[k] for k in sub["_key"]], cornerradius=4),
                               text=sub[metric].map(lambda v: f"{v:,.0f}"), textposition="outside",
                               hovertemplate="%{x}<br>" + metric + " %{y:,.0f}<extra></extra>"))
        fig.update_layout(hovermode="closest", bargap=0.5)
        style(fig, 300, metric)
        col.plotly_chart(fig, use_container_width=True)
        figs.append(fig)

    st.subheader("비교 제한 안내")
    st.dataframe(COMPARABILITY, hide_index=True, width="stretch")

    st.subheader("플랫폼별 전환·어트리뷰션 기준")
    st.session_state.setdefault("attr_df", ATTRIBUTION_DEFAULT.copy())
    attr = st.data_editor(st.session_state.attr_df, hide_index=True, width="stretch", key="attr_editor")

    st.subheader("중복 타깃(중복 도달) 반영")
    c1, c2 = st.columns([1, 3])
    overlap = c1.number_input("중복 도달 비율 (%)", 0.0, 100.0, 0.0, 1.0, key="overlap_pct",
                              help="두 매체 모두에 도달한 사용자 비율 추정치 (작은 쪽 기준)")
    basis = c2.text_input("산정 기준", "", key="overlap_basis",
                          placeholder="예: Google Ads 도달 플래너 + Meta 오디언스 겹침 추정, 브랜드 리프트 조사 등")

    _insight(df, overlap, basis, figs, show, attr)


def _insight(df: pd.DataFrame, overlap: float, basis: str, figs, show, attr):
    st.markdown(f"### 💡 {INSIGHT_TITLE}")
    own = df[df["_role"].isin(["고객사", "타 매체"])].copy()
    if len(own) < 2:
        st.info("고객사 캠페인과 동일 소재 타 매체가 모두 연동되어야 채널 기여를 비교할 수 있습니다.")
        put_report("platform", "타 플랫폼 성과 비교", figs=figs, tables=[show, attr])
        return

    conv_ok = own["전환"].notna().sum() >= 2
    if conv_ok:
        metric, label = "전환", "전환수"
    else:
        own["참여(좋아요+댓글)"] = own["좋아요"].fillna(0) + own["댓글 수"].fillna(0)
        metric, label = "참여(좋아요+댓글)", "참여수 (대리지표)"
        missing = own.loc[own["전환"].isna(), "매체"].tolist()
        st.warning(f"전환 데이터 미보유 매체: {', '.join(missing)} → 전환 대신 **공개 참여수(좋아요+댓글)**를 대리지표로 사용합니다. "
                   "참여는 구매와 같지 않으므로 '지갑을 연' 근거로는 약합니다.")

    shared = overlap / 100 * own[metric].min()
    own["중복 추정"] = shared
    own["중복 제외 기여"] = own[metric] - shared
    if overlap == 0:
        st.caption("중복 도달 비율 미입력 → 중복 제외 미적용 (원 수치 그대로 비교)")
    elif not basis:
        st.warning("중복 도달 비율의 산정 기준을 입력하세요 — 리포트에 근거로 함께 표시됩니다.")
    cost_ok = own["비용(KRW)"].notna().all()
    if cost_ok:
        own["중복 제외 기여당 비용"] = own["비용(KRW)"] / own["중복 제외 기여"]
    winner = own.sort_values("중복 제외 기여", ascending=False).iloc[0]
    evidence = own[["슬롯", "매체", metric, "중복 추정", "중복 제외 기여"] + (["비용(KRW)", "중복 제외 기여당 비용"] if cost_ok else [])]
    second = own.sort_values("중복 제외 기여", ascending=False).iloc[1]
    gap = winner["중복 제외 기여"] / second["중복 제외 기여"] if second["중복 제외 기여"] else None
    dedup_txt = f"중복 도달 {overlap:.0f}%({basis or '산정 기준 미입력'})를 제외한" if overlap else "중복 제외 미적용 상태의"
    summary = (f"{dedup_txt} {label} 기준, **{winner['매체']}**({winner['캠페인명']})가 "
               f"{winner['중복 제외 기여']:,.0f}로 가장 많이 기여했습니다"
               + (f" (2위 대비 {gap:.1f}배)." if gap else "."))
    with st.container(border=True):
        st.markdown(summary)
        st.dataframe(evidence, hide_index=True, width="stretch")
        st.caption(f"산정 방식: 중복 추정 = 중복 도달 비율 × min({label}) · 중복 제외 기여 = {label} − 중복 추정. "
                   "매체별 어트리뷰션 기준(위 표)이 다르므로 수치는 방향성 참고용입니다.")
    put_report("platform", "타 플랫폼 성과 및 어트리뷰션 비교", figs=figs, tables=[show, attr, evidence],
               text=f"{INSIGHT_TITLE}\n{summary.replace('**', '')}")
