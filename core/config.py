"""앱 전역 설정: 고객사, 사용자/권한, URL 슬롯 기본값."""

CLIENTS = ["LG전자", "삼성전자", "코웨이"]
DEFAULT_CLIENT = "LG전자"  # 고객사 미선택 시 자동 선택

# 간이 권한 모델 (실제 인증 없음): role=관리자는 모든 고객사·노트 편집 가능
USERS = {
    "Kate": {"role": "관리자", "clients": CLIENTS},
    "analyst_lg": {"role": "분석가", "clients": ["LG전자"]},
    "analyst_sec": {"role": "분석가", "clients": ["삼성전자"]},
}

# 상단 바 고정 URL 슬롯 3개
SLOTS = [
    {"key": "main", "label": "분석 캠페인 (고객사)", "role": "고객사"},
    {"key": "competitor", "label": "경쟁사 캠페인", "role": "경쟁사"},
    {"key": "other", "label": "동일 소재 타 매체", "role": "타 매체"},
]

DEFAULT_URLS = {
    "main": "https://youtu.be/8_4Qo4At8GQ?si=rGfc6Wu9oUYY6qdf",
    "competitor": "",
    "other": "https://www.instagram.com/p/DdVHbwXz9mB/",
}

# 통화 → KRW 환산 기준 (화면에서 수정 가능)
FX_TO_KRW = {"KRW": 1.0, "USD": 1380.0, "EUR": 1500.0, "JPY": 9.3}
