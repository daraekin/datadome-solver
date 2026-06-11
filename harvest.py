#!/usr/bin/env python3
"""
Session harvester using the generic DataDome solver.
Generates valid datadome cookies for any target site via HTTP,
then pairs them with a fresh session from the target.
Saves sessions in engine-compatible storage-state.json format.
"""

import os
import sys
import json
import time
import threading
from datetime import datetime

from curl_cffi import requests as cffi_requests
from solver import DataDomeSolver, UA, IMPERSONATE

PROXY_URL = os.environ.get(
    "PROXY",
    "http://f449f4fbe7363deaf4eb:932a7acd4c6e38b8@gw.dataimpulse.com:823"
)

TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign"
)
DDK = os.environ.get("DDK", None)  # Optional: provide manually

HARVEST_COUNT = int(os.environ.get("HARVEST_COUNT", "10"))
CONCURRENT = int(os.environ.get("CONCURRENT", "2"))

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(DIR, "sessions")

ACCEPT = "text/html,*/*"

print_lock = threading.Lock()


def log(*args):
    with print_lock:
        print(*args)


def fetch_session_cookies(datadome_cookie: str, target_url: str, domain: str) -> dict:
    """Visit target site to get session cookies paired with the datadome cookie."""
    session = cffi_requests.Session(impersonate=IMPERSONATE)
    session.proxies = {"http": PROXY_URL, "https": PROXY_URL}
    session.cookies.set("datadome", datadome_cookie, domain=domain)

    headers = {
        "User-Agent": UA,
        "Accept": ACCEPT,
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    try:
        r = session.get(target_url, headers=headers, timeout=30, allow_redirects=True)
        if r.status_code not in (200, 301, 302):
            log(f"  Target returned {r.status_code}")
            return None

        cookies_list = []
        for cookie in session.cookies:
            cookies_list.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain or domain,
                "path": cookie.path or "/",
                "expires": cookie.expires or -1,
                "httpOnly": hasattr(cookie, "_rest") and cookie._rest.get("HttpOnly", False),
                "secure": getattr(cookie, "secure", True),
                "sameSite": "None",
            })

        return {"cookies": cookies_list, "origins": []}

    except Exception as e:
        log(f"  Request error: {e}")
        return None
    finally:
        session.close()


def harvest_one(solver: DataDomeSolver, index: int) -> str:
    result = solver.solve()
    if not result:
        log(f"[{index:03d}] Solve FAILED")
        return None

    dd_value = result["value"]
    log(f"[{index:03d}] Cookie: {dd_value[:30]}...")

    state = fetch_session_cookies(dd_value, solver.target_url, solver.site_domain)
    if not state:
        log(f"[{index:03d}] Session fetch FAILED")
        return None

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filename = f"dd_{index:03d}_{ts}.json"
    filepath = os.path.join(SESSIONS_DIR, filename)
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)

    log(f"[{index:03d}] Saved -> {filename}")
    return filepath


def main():
    print(f"DataDome Session Harvester (Generic)")
    print(f"  Target: {TARGET_URL}")
    print(f"  Sessions: {HARVEST_COUNT} | Workers: {CONCURRENT}")
    print(f"  Proxy: {PROXY_URL}")
    print()

    solver = DataDomeSolver(target_url=TARGET_URL, ddk=DDK, proxy=PROXY_URL)
    if not solver.ddk:
        print("FAILED: Could not detect DataDome key. Set DDK env var manually.")
        sys.exit(1)

    print(f"  DDK: {solver.ddk}")
    print()

    os.makedirs(SESSIONS_DIR, exist_ok=True)

    harvested = 0
    idx = 0
    lock = threading.Lock()
    sem = threading.Semaphore(CONCURRENT)

    def worker():
        nonlocal harvested, idx
        while True:
            with lock:
                if harvested >= HARVEST_COUNT:
                    return
                my_idx = idx
                idx += 1

            with sem:
                result = harvest_one(solver, my_idx)
                if result:
                    with lock:
                        harvested += 1
                        log(f"  Progress: {harvested}/{HARVEST_COUNT}")

            time.sleep(2)

    threads = []
    for _ in range(CONCURRENT):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=300)

    print(f"\nDone! {harvested} sessions in {SESSIONS_DIR}")
    return harvested


if __name__ == "__main__":
    main()
