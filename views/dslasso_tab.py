"""③ DS-LASSO 증분 효과 분석."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dslasso, store
from core.charts import SERIES, style
from views.common import put_report

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_weekly_model.csv"
SAMPLE_ROLES = {
    "target": "판매량",
    "controls": ["기온", "습도", "이사철지수", "경쟁사_예산", "경쟁사_할인율", "시장_전체매출"],
    "candidates": ["자사_캠페인노출", "자사몰_클릭수"],
}


def _load_data() -> tuple[pd.DataFrame | None, str]:
    src = st.radio("분석 데이터", ["CSV 업로드", "샘플 데이터 (가상)"], horizontal=True, key="dsl_src")
    if src == "CSV 업로드":
        up = st.file_uploader("주/일 단위 CSV (날짜 열 + 타깃·통제·후보 지표 열)", type=["csv"], key="dsl_up")
        if up is None:
            st.caption("예: date, 판매량, 기온, 습도, 이사철지수, 경쟁사_예산, 경쟁사_할인율, 시장_전체매출, 자사_캠페인노출, 자사몰_클릭수")
            return None, ""
        try:
            return pd.read_csv(up, thousands=","), f"업로드: {up.name}"
        except Exception as e:
            st.error(f"CSV를 읽을 수 없습니다: {e}")
            st.caption("🔧 UTF-8 인코딩, 쉼표 구분, 첫 행 = 열 이름인지 확인하세요.")
            return None, ""
    st.caption("⚠️ 샘플은 기능 시연용 **가상 데이터**입니다. 실제 분석에는 고객사 판매·통제변수 데이터를 업로드하세요.")
    return pd.read_csv(SAMPLE), "샘플 (가상 데이터)"


def _attach_trends(df: pd.DataFrame) -> pd.DataFrame:
    if not st.session_state.trends:
        return df
    if not st.checkbox("Google Trends 검색 관심도를 후보 변수로 병합", key="dsl_trends"):
        return df
    t, _ = st.session_state.trends
    t = t.rename(columns=lambda c: f"검색관심도_{c}").sort_index()
    merged = pd.merge_asof(df.sort_index(), t, left_index=True, right_index=True, direction="backward")
    st.caption("각 관측 시점 직전의 Trends 값으로 맞춤(as-of 병합). Trends 기간 밖 행은 결측 → 분석에서 제외됩니다.")
    return merged


def forest(table: pd.DataFrame) -> go.Figure:
    t = table[table["역할"].str.startswith("후보")]
    fig = go.Figure()
    fig.add_scatter(
        x=t["효과 추정치"], y=t["변수"], mode="markers",
        marker=dict(size=10, color=SERIES[0]),
        error_x=dict(type="data", symmetric=False, array=t["95% CI 상한"] - t["효과 추정치"],
                     arrayminus=t["효과 추정치"] - t["95% CI 하한"], thickness=2, width=6),
        hovertemplate="%{y}: %{x:.4g}<extra></extra>", showlegend=False,
    )
    fig.add_vline(x=0, line=dict(color="gray", width=1, dash="dash"))
    fig.update_xaxes(title="증분 효과 추정치 (타깃 단위 / 후보 지표 1단위) · 95% CI")
    fig.update_layout(hovermode="closest")
    return style(fig, 120 + 60 * len(t))


def render():
    st.subheader("DS-LASSO 기반 증분 효과 분석")
    raw, src = _load_data()
    if raw is None:
        return
    date_col = next((c for c in raw.columns if c.lower() in ("date", "day", "week", "날짜", "일자", "주")), None)
    if date_col is None:
        st.error("날짜 열을 찾을 수 없습니다. 열 이름을 'date' 또는 '날짜'로 지정하세요.")
        return
    raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
    df = raw.dropna(subset=[date_col]).set_index(date_col).sort_index()
    df.index.name = "date"
    df = _attach_trends(df)
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    is_sample = src.startswith("샘플")
    st.markdown("**1. 변수 역할 확인·수정**")
    c1, c2, c3 = st.columns([2, 4, 3])
    target = c1.selectbox("타깃 변수 (판매량·전환)", num_cols,
                          index=num_cols.index(SAMPLE_ROLES["target"]) if is_sample and SAMPLE_ROLES["target"] in num_cols else 0,
                          key="dsl_target")
    rest = [c for c in num_cols if c != target]
    controls = c2.multiselect("통제변수 (기온·습도·이사철·경쟁사 예산/할인율·시장 매출 등)", rest,
                              default=[c for c in SAMPLE_ROLES["controls"] if c in rest] if is_sample else [],
                              key="dsl_controls")
    candidates = c3.multiselect("후보 지표 (자사 캠페인 노출·자사몰 클릭 등)", [c for c in rest if c not in controls],
                                default=[c for c in SAMPLE_ROLES["candidates"] if c in rest and c not in controls] if is_sample else [],
                                key="dsl_candidates")
    lo, hi = df.index.min().date(), df.index.max().date()
    period = st.slider("분석 기간", min_value=lo, max_value=hi, value=(lo, hi), key="dsl_period")
    sub = df.loc[str(period[0]):str(period[1])]

    st.markdown("**2. 실행 전 데이터 검증**")
    errors, warns = dslasso.precheck(sub, target, controls, candidates)
    for e in errors:
        st.error(e)
    for w in warns:
        st.warning(w)
    if not errors:
        st.success(f"검증 통과 · 관측치 {len(sub[[target] + controls + candidates].dropna())}개 · 기간 {period[0]} ~ {period[1]}")

    if st.button("DS-LASSO 실행", type="primary", disabled=bool(errors), key="dsl_run"):
        with st.spinner("변수 선택 및 추정 중…"):
            res = dslasso.run(sub, target, controls, candidates)
        res.update({"target": target, "controls": controls, "candidates": candidates, "source": src,
                    "period_sel": f"{period[0]} ~ {period[1]}"})
        st.session_state.dsl = res
        prev = [r for r in store.load("runs", default=[]) if r["version"] == res["version"]]
        store.append("runs", {"version": res["version"], "run_at": res["run_at"], "user": st.session_state.user,
                              "client": st.session_state.client, "target": target, "n": res["n"],
                              "candidates": candidates, "source": src, "period": res["period_sel"]})
        if prev:
            st.info(f"동일 입력 데이터(버전 {res['version']})의 {len(prev) + 1}번째 실행입니다 — 실행 시각을 기록했습니다.")

    res = st.session_state.dsl
    if not res:
        return
    st.markdown(f"**3. 결과** · 버전 `{res['version']}` · 실행 {res['run_at']} · n={res['n']} · R²={res['r2']:.3f} · 기간 {res['period_sel']} · 데이터 {res['source']}")
    table = res["table"]
    st.dataframe(table, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.4g")
                                for c in ["효과 추정치", "표준오차", "p값", "95% CI 하한", "95% CI 상한"]})

    st.markdown("**4. 통제변수 반영 후 캠페인 후보 지표의 증분 효과**")
    fig = forest(table)
    st.plotly_chart(fig, use_container_width=True)
    for r in table[table["역할"].str.startswith("후보")].to_dict("records"):
        st.markdown(f"- **{r['변수']}** 1단위 증가 시 {res['target']} **{r['효과 추정치']:+,.3g}** "
                    f"(95% CI {r['95% CI 하한']:,.3g} ~ {r['95% CI 상한']:,.3g}, p={r['p값']:.3g}) → {r['유의성']}")

    st.markdown("**5. 해석 주의사항**")
    for w in res["warnings"] or ["특이 경고 없음 (그래도 아래 가정과 한계를 확인하세요)"]:
        st.warning(w)
    with st.expander("다중공선성 (VIF)"):
        st.dataframe(res["vif"], hide_index=True)
    st.info(dslasso.ASSUMPTIONS)

    with st.expander("실행 이력 (현재 고객사)"):
        runs = [r for r in store.load("runs", default=[]) if r.get("client") == st.session_state.client]
        st.dataframe(pd.DataFrame(runs[::-1]), hide_index=True, width="stretch")

    put_report("dslasso", f"DS-LASSO 증분 효과 (타깃: {res['target']})", figs=[fig], tables=[table],
               text=f"버전 {res['version']} · 실행 {res['run_at']} · n={res['n']} · 기간 {res['period_sel']} · 데이터 {res['source']}\n"
                    + "\n".join(res["warnings"]) + "\n결과는 연관성 추정이며 인과관계를 확정하지 않습니다.")
