"""clients.json의 모든 고객사 기본값 기준으로 데이터를 한 번 받아 디스크 캐시(data/cache/)에 저장.

python scripts/warm_cache.py      (프로젝트 루트에서 실행)
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from core import cached, channel, dslasso, trends  # noqa: E402
from core import comments as cm  # noqa: E402
from core.config import clients, preset  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_weekly_model.csv"
SAMPLE_ROLES = {
    "target": "판매량",
    "controls": ["기온", "습도", "이사철지수", "경쟁사_예산", "경쟁사_할인율", "시장_전체매출"],
    "candidates": ["자사_캠페인노출", "자사몰_클릭수"],
}
COMMENT_LIMIT, COMMENT_SORT = 500, list(cm.SORTS)[0]  # 앱 기본값과 동일해야 캐시가 맞음


def step(name, fn):
    t = time.time()
    try:
        out = fn()
        print(f"✓ {name} ({time.time() - t:.1f}s)")
        return out
    except Exception as e:
        print(f"✕ {name}: {type(e).__name__}: {e}")


def warm_client(client: str):
    p = preset(client)
    print(f"\n=== {client} (경쟁사 {p['competitor']}) ===")
    since = date.today() - timedelta(days=180)
    for key, url in p["urls"].items():
        if not url:
            continue
        meta = step(f"링크 [{key}] {url}", lambda: cached.link(url, refresh=True))
        if not meta:
            continue
        if meta.get("thumbnail"):
            step(f"썸네일 [{key}]", lambda: cached.image(meta["thumbnail"]))
        if meta["platform"] == "YouTube" and meta.get("channel_id"):
            vids = step(f"채널 업로드 목록 [{key}] {meta.get('account')}",
                        lambda: channel.uploads(meta["channel_id"], since, refresh=True))
            if vids is not None:
                print(f"    → {len(vids)}개")
        if meta["platform"] == "YouTube" and meta.get("kind") != "channel":
            df = step(f"댓글 [{key}] {COMMENT_SORT} {COMMENT_LIMIT}개",
                      lambda: cached.comments(meta["id"], COMMENT_LIMIT, COMMENT_SORT, refresh=True))
            if df is not None:
                print(f"    → {len(df)}개 수집")
        if meta["platform"] == "Instagram" and meta.get("followers") is None:
            print("    ⚠️ Instagram 팔로워 수 수집 실패 (요청 제한) — 나중에 앱에서 [연동]으로 재시도")

    kws = [client, p["competitor"]]
    for attempt in range(4):
        r = step(f"Google Trends {kws} (시도 {attempt + 1})",
                 lambda: trends.interest_over_time(kws, since, date.today(), "KR", retries=2))
        if r:
            break
        time.sleep(30)


def main():
    for client in clients():
        warm_client(client)

    df = dslasso.prepare(pd.read_csv(SAMPLE))
    step("DS-LASSO 샘플", lambda: cached.dsl_run(df, SAMPLE_ROLES["target"], SAMPLE_ROLES["controls"],
                                                SAMPLE_ROLES["candidates"], refresh=True))


if __name__ == "__main__":
    main()
