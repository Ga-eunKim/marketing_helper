# marketing_helper — 구글 광고 캠페인 효과 측정·비교 대시보드

기능명세서(`구글 광고 캠페인 효과 측정 및 비교 분석 대시보드_기능명세서_2026-10-12.md`) 기반 Streamlit 대시보드.

## 실행
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```
캐시를 미리 채우려면: `.venv/bin/python scripts/warm_cache.py`

## 화면 구성
| 위치 | 내용 |
|---|---|
| 왼쪽 사이드바 | 고객사·경쟁사 선택, URL 3개 (분석 캠페인 / 경쟁사 캠페인 / 동일 소재 타 매체), [연동] |
| 상단 | 타이틀, 분석 기간, 언어 전환 (ENG 기본 / KOR) |
| Google Trends 검색 관심도 | 고객사·경쟁사 키워드 시계열 + 각 채널 YouTube 업로드 영상 점 (마우스를 올리면 제목) |
| 캠페인 링크 연동 결과 | 썸네일, 고객사·경쟁사 영상 지표 비교표 |
| 타 플랫폼 성과 비교 | 고객사 YouTube vs Instagram (좋아요·댓글·총 참여·일평균·댓글/좋아요·팔로워 대비 참여율). 타 매체 URL이 없으면 숨김 |
| 브랜드·소비자 반응 | YouTube 댓글 텍스트 분석 (구매 의향 / 긍정 선호 / 메시지 연상), 이벤트 댓글 제외 |
| DS-LASSO 증분 효과 | 샘플(가상) 또는 업로드 CSV로 타깃·통제·후보 지표 지정 → 증분 효과·95% CI·주의사항 |

## 고객사 추가
`clients.json`에 고객사를 추가하면 사이드바에서 선택할 때 경쟁사와 URL이 자동으로 채워집니다. 첫 번째 고객사가 기본값입니다.
```json
"고객사명": {"competitor": "경쟁사명", "urls": {"main": "영상 URL", "competitor": "영상 또는 채널 URL", "other": "Instagram URL 또는 빈칸"}}
```

## 데이터 수집 범위 (API 키 불필요)
- **YouTube 영상**: oEmbed + 공개 페이지 (제목, 채널, 게시일, 조회수, 좋아요, 댓글 수, 구독자 수), 댓글 본문(`youtube-comment-downloader`).
- **YouTube 채널**(`@핸들`): 채널 정보 + 동영상 탭 목록. 업로드일은 목록의 '○일/주/개월 전' 표기로 추정 (영상별 페이지는 요청하지 않음 — 대량 요청 시 YouTube가 일시 차단).
- **Instagram**: `instaloader` 비로그인 → 좋아요·댓글 수·캡션·게시일. 조회수·댓글 본문은 로그인 필요로 수집 불가, 팔로워 수는 요청 제한으로 실패할 수 있음.
- **Google Trends**: pytrends (429 요청 제한 시 재시도).

## 캐시
`data/cache/`에 디스크 캐시 (서버 재시작 후에도 유지, git 제외): 링크 24시간, 댓글 24시간, 채널 업로드 목록 24시간, 썸네일 7일, Trends·DS-LASSO는 입력이 같으면 계속 사용. 새로 받기에 실패하면 이전 값을 유지하고, 빈 결과는 저장하지 않습니다.
