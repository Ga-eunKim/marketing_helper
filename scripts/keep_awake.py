"""Streamlit Cloud 앱이 잠들지 않도록 접속하고, 잠들어 있으면 깨우기 버튼을 누른다 (GitHub Actions에서 실행).

환경 변수 APP_URL = 배포된 앱 주소 (예: https://xxxx.streamlit.app)
"""
import os
import sys

from playwright.sync_api import sync_playwright

url = os.environ.get("APP_URL", "").strip()
if not url:
    sys.exit("APP_URL이 비어 있습니다.")

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, timeout=120_000)
    page.wait_for_timeout(10_000)
    wake = page.get_by_role("button", name="Yes, get this app back up!")
    if wake.count():
        print("앱이 잠들어 있어 깨웁니다.")
        wake.first.click()
        page.wait_for_timeout(90_000)  # 다시 켜질 때까지 대기
    else:
        print("앱이 깨어 있습니다.")
    # 앱 화면(iframe) 안의 Streamlit이 실제로 그려질 때까지 잠시 머무름 → 접속 기록이 남음
    page.wait_for_timeout(30_000)
    browser.close()
