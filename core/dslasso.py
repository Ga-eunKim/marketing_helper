"""Double-Selection LASSO (Belloni, Chernozhukov & Hansen, 2014).

후보 지표 d 각각에 대해:
  1) LASSO y ~ W   (W = 통제변수 + 다른 후보 지표) 로 y 예측에 필요한 변수 선택
  2) LASSO d ~ W   로 d와 상관된 교란 변수 선택
  3) OLS  y ~ d + (1∪2 선택 변수), HC3 강건 표준오차 → d의 증분 효과·p값·95% CI
"""
from __future__ import annotations

import hashlib
from datetime import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LassoCV
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.outliers_influence import variance_inflation_factor

MIN_OBS = 20


def precheck(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str]) -> tuple[list[str], list[str]]:
    """(errors, warnings). errors가 있으면 실행 불가."""
    errors, warns = [], []
    if not target:
        errors.append("타깃 변수를 선택하세요.")
    if not candidates:
        errors.append("후보 지표(캠페인 지표)를 1개 이상 선택하세요.")
    overlap = set(candidates) & (set(controls) | {target})
    if overlap:
        errors.append(f"같은 변수가 여러 역할에 지정됨: {sorted(overlap)}")
    if errors:
        return errors, warns
    cols = [target] + controls + candidates
    miss = df[cols].isna().sum()
    miss = miss[miss > 0]
    if len(miss):
        warns.append("결측 포함 행은 제외됩니다: " + ", ".join(f"{k} {v}건" for k, v in miss.items()))
    n = len(df[cols].dropna())
    p = len(controls) + len(candidates)
    if n < MIN_OBS:
        errors.append(f"관측치 부족: 결측 제외 {n}개 < 최소 {MIN_OBS}개")
    elif n < 3 * p:
        warns.append(f"관측치({n})가 변수 수({p})의 3배 미만 — 추정이 불안정할 수 있습니다.")
    const = [c for c in cols if df[c].nunique(dropna=True) <= 1]
    if const:
        errors.append(f"값이 일정한 변수(분산 0): {const}")
    return errors, warns


def _lasso_select(X: pd.DataFrame, y: pd.Series, seed: int) -> list[str]:
    if X.shape[1] == 0:
        return []
    Xs = StandardScaler().fit_transform(X)
    ys = (y - y.mean()) / (y.std() or 1)
    cv = KFold(n_splits=min(5, max(3, len(y) // 10)), shuffle=True, random_state=seed)
    m = LassoCV(cv=cv, random_state=seed, max_iter=20000).fit(Xs, ys)
    return [c for c, b in zip(X.columns, m.coef_) if abs(b) > 1e-8]


def vif_table(X: pd.DataFrame) -> pd.DataFrame:
    if X.shape[1] < 2:
        return pd.DataFrame(columns=["변수", "VIF"])
    Xc = sm.add_constant(X.astype(float))
    return pd.DataFrame({
        "변수": X.columns,
        "VIF": [variance_inflation_factor(Xc.values, i + 1) for i in range(X.shape[1])],
    })


def input_hash(df: pd.DataFrame, target, controls, candidates) -> str:
    h = hashlib.sha1()
    h.update(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    h.update(repr((target, controls, candidates)).encode())
    return h.hexdigest()[:12]


def run(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str], seed: int = 42) -> dict:
    data = df[[target] + controls + candidates].dropna().astype(float)
    y = data[target]
    rows, selected_union = [], set()
    for d in candidates:
        W = data[controls + [c for c in candidates if c != d]]
        s_y = _lasso_select(W, y, seed)
        s_d = _lasso_select(W, data[d], seed)
        sel = sorted(set(s_y) | set(s_d))
        selected_union |= set(sel)
        X = sm.add_constant(data[[d] + sel])
        fit = sm.OLS(y, X).fit(cov_type="HC3")
        lo, hi = fit.conf_int().loc[d]
        rows.append({
            "변수": d, "역할": "후보 지표 (캠페인)", "영향 방향": "+" if fit.params[d] > 0 else "−",
            "효과 추정치": fit.params[d], "표준오차": fit.bse[d], "p값": fit.pvalues[d],
            "95% CI 하한": lo, "95% CI 상한": hi,
            "유의성": "유의 (p<0.05)" if fit.pvalues[d] < 0.05 else ("약한 근거 (p<0.1)" if fit.pvalues[d] < 0.1 else "유의하지 않음"),
            "선택된 통제변수": ", ".join(sel) or "(없음)",
        })

    # 참고용: 선택된 통제변수 계수 (교란 보정 목적이므로 인과 해석 대상 아님)
    final_vars = candidates + sorted(selected_union - set(candidates))
    full = sm.OLS(y, sm.add_constant(data[final_vars])).fit(cov_type="HC3")
    for c in sorted(selected_union - set(candidates)):
        lo, hi = full.conf_int().loc[c]
        rows.append({
            "변수": c, "역할": "통제변수 (선택됨)", "영향 방향": "+" if full.params[c] > 0 else "−",
            "효과 추정치": full.params[c], "표준오차": full.bse[c], "p값": full.pvalues[c],
            "95% CI 하한": lo, "95% CI 상한": hi,
            "유의성": "참고용 (보정 변수)", "선택된 통제변수": "",
        })
    for c in controls:
        if c not in selected_union:
            rows.append({"변수": c, "역할": "통제변수 (미선택)", "영향 방향": "", "효과 추정치": np.nan,
                         "표준오차": np.nan, "p값": np.nan, "95% CI 하한": np.nan, "95% CI 상한": np.nan,
                         "유의성": "LASSO에서 제외", "선택된 통제변수": ""})

    vif = vif_table(data[final_vars])
    warns = []
    high = vif[vif["VIF"] > 10]
    if len(high):
        warns.append("다중공선성 주의 (VIF>10): " + ", ".join(f"{r.변수}({r.VIF:.1f})" for r in high.itertuples()))
    if len(data) < 50:
        warns.append(f"표본 수 {len(data)}개 — 신뢰구간이 넓고 결과 변동성이 큽니다.")
    dw = sm.stats.durbin_watson(full.resid)
    if dw < 1.5 or dw > 2.5:
        warns.append(f"잔차 자기상관 의심 (Durbin-Watson={dw:.2f}) — 시계열 데이터라면 표준오차가 과소추정될 수 있습니다.")

    return {
        "table": pd.DataFrame(rows),
        "vif": vif,
        "warnings": warns,
        "n": len(data),
        "r2": full.rsquared,
        "period": f"{data.index.min()} ~ {data.index.max()}" if not isinstance(data.index, pd.RangeIndex) else "",
        "version": input_hash(df[[target] + controls + candidates], target, controls, candidates),
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


ASSUMPTIONS = """- **분석 가정**: 선형·가법 관계, 선택된 통제변수 외 관측되지 않은 교란이 없음(조건부 독립), 변수 측정 오차가 작음.
- **해석 한계**: 본 결과는 관측 데이터 기반 **연관성(조건부 증분) 추정**이며 인과관계를 확정하지 않습니다. 실험(지역 홀드아웃·지오 실험 등)으로 검증을 권장합니다.
- **DS-LASSO 특성**: 변수 선택은 교차검증 정규화 강도에 따라 달라질 수 있으며, 표본이 작을수록 선택 결과가 불안정합니다.
- **시계열 주의**: 주 단위 데이터의 계절성·추세·이월 효과(애드스톡)는 별도 변수로 넣지 않으면 반영되지 않습니다."""
