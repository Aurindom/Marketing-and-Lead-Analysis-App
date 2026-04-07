import sys

TARGET_URL = "https://example.com"
EXPECTED_TEXT = "Example Domain"
TIMEOUT_MS = 15000


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: playwright package not installed")
        sys.exit(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(TARGET_URL, wait_until="load", timeout=TIMEOUT_MS)
                content = page.content()
                version = browser.version
            finally:
                browser.close()
    except Exception as e:
        print(f"FAIL: Chromium launch or navigation error: {e}")
        sys.exit(1)

    if EXPECTED_TEXT not in content:
        print(f"FAIL: Expected '{EXPECTED_TEXT}' not found in rendered HTML")
        sys.exit(1)

    print(f"PASS: Playwright rendered {TARGET_URL} successfully (Chromium {version})")
    sys.exit(0)


if __name__ == "__main__":
    main()
