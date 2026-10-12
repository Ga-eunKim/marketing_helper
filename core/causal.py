"""BSTS 방식(CausalImpact) 반사실 분석 — 경쟁사 프로모션이 없었다면 고객사 검색 관심도는?

구조 시계열(로컬 레벨 + 주간 계절성 + 공변량 회귀, CausalImpact 기본 구성)을 개입 전 구간으로 학습하고, 개입 구간의
반사실(counterfactual)을 예측해 실제값과의 차이를 효과로 본다. 모델은 statsmodels UnobservedComponents
(최대우도 추정)로 구현했다 — CausalImpact(BSTS)와 같은 구조지만 사후분포 대신 상태·관측 노이즈 시뮬레이션으로
구간과 tail-area 확률을 구한다 (TensorFlow 의존성 없이 클라우드에서 가볍게 실행).

공변량에는 개입의 영향을 받지 않는 시장 카테고리 검색량만 넣는다. 프로모션 키워드 검색량은 개입 기간을
찾는 데만 쓴다 (공변량으로 넣으면 효과를 모델이 흡수해 버림).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.structural import UnobservedComponents

from .i18n import t

MIN_PRE = 28  # 개입 전 학습 구간 최소 관측치


class CausalError(Exception):
    pass


def detect_window(promo: pd.Series, frac: float = 0.25, min_days: int = 7) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """이벤트 키워드 검색량(7일 이동평균)이 최고점의 frac 이상인 연속 구간 중 최고점을 포함하는 구간.

    하루짜리 급등(사고·뉴스성 이벤트)은 여파가 이어지므로 시작일부터 최소 min_days일로 넓힌다.
    """
    s = promo.rolling(7, center=True, min_periods=1).mean()
    if s.max() <= 0:
        return None
    above = s >= frac * s.max()
    peak = s.idxmax()
    i = s.index.get_loc(peak)
    lo = hi = i
    while lo > 0 and above.iloc[lo - 1]:
        lo -= 1
    while hi < len(s) - 1 and above.iloc[hi + 1]:
        hi += 1
    raw = promo.iloc[lo:hi + 1]
    active = raw[raw > 0]  # 이동평균 때문에 넓어진 양 끝을 실제 검색이 있는 날로 맞춤
    w0, w1 = (active.index[0], active.index[-1]) if not active.empty else (s.index[lo], s.index[hi])
    w1 = min(max(w1, w0 + pd.Timedelta(days=min_days - 1)), s.index[-1])
    return w0, w1


def run(y: pd.Series, X: pd.DataFrame, window: tuple[pd.Timestamp, pd.Timestamp], sims: int = 1000,
        seed: int = 7) -> dict:
    """y: 결과 시계열, X: 공변량, window: (개입 시작, 끝). 개입 이후 구간은 분석에서 제외."""
    start, end = window
    data = pd.concat([y.rename("y"), X], axis=1).loc[:end].astype(float).dropna()
    pre, post = data.loc[: start - pd.Timedelta(days=1)], data.loc[start:end]
    if len(pre) < MIN_PRE:
        raise CausalError(t(f"개입 전 학습 구간이 {len(pre)}일로 너무 짧습니다 (최소 {MIN_PRE}일). 분석 기간을 앞으로 늘리세요.",
                            f"Pre-period is only {len(pre)} days (minimum {MIN_PRE}). Extend the date range earlier."))
    if len(post) < 3:
        raise CausalError(t("개입 기간이 너무 짧습니다.", "The intervention window is too short."))
    xcols = list(X.columns)
    daily = (data.index[1] - data.index[0]).days == 1 if len(data) > 1 else False
    model = UnobservedComponents(pre["y"], level="local level", exog=pre[xcols],
                                 freq_seasonal=[{"period": 7, "harmonics": 2}] if daily else None)
    # CausalImpact 기본 사전분포처럼 레벨 변동을 작게 고정 (σ_level = 0.01 × sd(y)) — 개입 직전의
    # 일시적 급등·급락을 레벨이 따라가 반사실이 튀는 것을 막는다
    level_var = (0.01 * float(pre["y"].std() or 1.0)) ** 2
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with model.fix_params({"sigma2.level": level_var}):
            fit = model.fit(disp=False, maxiter=500)
    fc = fit.get_forecast(steps=len(post), exog=post[xcols])
    pred = pd.Series(np.asarray(fc.predicted_mean), index=post.index)
    ci = np.asarray(fc.conf_int(alpha=0.05))
    lo, hi = pd.Series(ci[:, 0], index=post.index), pd.Series(ci[:, 1], index=post.index)

    # 반사실 경로 시뮬레이션 → 누적 효과의 tail-area 확률
    rng = np.random.default_rng(seed)
    sim = fit.simulate(len(post), repetitions=sims, anchor="end", exog=post[xcols],
                       random_state=rng)
    sim_sums = np.asarray(sim).reshape(len(post), -1).sum(axis=0)
    actual_sum, pred_sum = float(post["y"].sum()), float(pred.sum())
    if actual_sum >= pred_sum:
        p = float((sim_sums >= actual_sum).mean())
    else:
        p = float((sim_sums <= actual_sum).mean())
    p = max(p, 1 / sims)  # 시뮬레이션 횟수 기준 하한

    eff = post["y"] - pred
    return {
        "actual": data["y"], "pred": pred, "lo": lo, "hi": hi, "window": (start, end),
        "pre_days": len(pre), "post_days": len(post),
        "avg_actual": float(post["y"].mean()), "avg_pred": float(pred.mean()),
        "abs_effect": float(eff.mean()), "cum_effect": float(eff.sum()),
        "rel_effect": actual_sum / pred_sum - 1 if pred_sum else np.nan,
        "cum_lo": float(post["y"].sum() - np.percentile(sim_sums, 97.5)),
        "cum_hi": float(post["y"].sum() - np.percentile(sim_sums, 2.5)),
        "p": p, "covariates": xcols,
    }
