"""
Keep-alive ping for the Render free-tier backend.

Render free web services go to sleep after 15 minutes without any inbound
traffic, and wake up (cold start ~1 min) on the next request. A Render cron
service runs this script every 5 minutes, which hits the /health endpoint —
that counts as inbound traffic, so the backend stays well inside the 15-minute
idle cutoff and feels always-on (no cold-start wait for students).

Set HEALTH_URL in the Render dashboard to your backend's real URL if it differs
from the default below (e.g. https://your-app-name.onrender.com/health).
"""
import os
import time
import urllib.request

HEALTH_URL = (os.environ.get("HEALTH_URL") or "").strip()
FALLBACK = "https://detomsite-backend.onrender.com/health"
TIMEOUT = 25  # generous: allows for a cold-start wake (~1 min max, 3 attempts)
RETRIES = 3


def ping(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return response.status < 400
    except Exception as exc:  # noqa: BLE001 - any network error just means retry
        print(f"keep-alive: ping error -> {exc}")
        return False


def main() -> int:
    url = HEALTH_URL or FALLBACK
    print(f"keep-alive: pinging {url}")
    for attempt in range(1, RETRIES + 1):
        if ping(url):
            print("keep-alive: backend is awake")
            return 0
        print(f"keep-alive: attempt {attempt}/{RETRIES} failed, waiting 10s...")
        time.sleep(10)
    print("keep-alive: backend unreachable after all attempts")
    return 1


if __name__ == "__main__": 
    raise SystemExit(main())
