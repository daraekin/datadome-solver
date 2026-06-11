#!/usr/bin/env python3
"""
Generic DataDome bypass — works on any DataDome-protected website.

Based on reverse-engineered DataDome internals (gravilk/datadome-documented).
Posts realistic Chrome browser fingerprints to api-js.datadome.co/js/
and returns valid datadome cookies — no browser needed.

Usage:
    from solver import DataDomeSolver
    solver = DataDomeSolver(proxy="http://user:pass@host:port")
    cookie = solver.solve("https://target-site.com/page")

Requirements: pip install curl_cffi
"""

import json
import math
import random
import time
import os
import re
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse

from curl_cffi import requests as cffi_requests

DD_API = "https://api-js.datadome.co/js/"
DD_TAGS = "https://js.datadome.co/tags.js"

PROXY_URL = os.environ.get(
    "PROXY",
    "http://f449f4fbe7363deaf4eb:932a7acd4c6e38b8@gw.dataimpulse.com:823"
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
IMPERSONATE = "chrome124"
TZ_OFFSET = 240  # UTC-4 Eastern
TZ_NAME = "America/New_York"


def _random_float():
    return float(f"{random.randint(5, 30)}.{random.randint(1000000000000, 9999999999999)}")


def extract_ddk_from_url(target_url: str, proxy: str = None, timeout: int = 10) -> Optional[str]:
    """
    Extract the DataDome site key (ddk) from a protected website.
    
    Steps:
    1. Visit the target page, extract dd={} JSON from 403 response
    2. If no 403, look for <script src="js.datadome.co/tags.js"> in HTML
    3. Fall back to POSTing to tags.js endpoint
    
    Returns the ddk hex string or None.
    """
    px = proxy or PROXY_URL
    proxies = {"http": px, "https": px}

    try:
        r = cffi_requests.get(
            target_url,
            headers={"User-Agent": UA, "Accept": "text/html,*/*"},
            proxies=proxies,
            timeout=timeout,
            impersonate=IMPERSONATE,
            allow_redirects=True,
        )

        # Method 1: Extract from 403 dd={} body
        if r.status_code == 403:
            dd = _parse_dd_from_body(r.text)
            if dd and dd.get("hsh"):
                return dd["hsh"]

        # Method 2: Find tags.js URL in page source
        m = re.search(r'//js\.datadome\.co/tags\.js\?id=([A-Fa-f0-9]+)', r.text)
        if m:
            return m.group(1)

        # Method 3: Fetch tags.js and extract ddk from it
        tags_r = cffi_requests.get(
            DD_TAGS,
            headers={"User-Agent": UA, "Referer": target_url},
            proxies=proxies,
            timeout=timeout,
            impersonate=IMPERSONATE,
        )
        m = re.search(r'["\']?ddk["\']?\s*[:=]\s*["\']([A-Fa-f0-9]{30,})["\']', tags_r.text)
        if m:
            return m.group(1)

        # Method 4: Search for any hex hash that looks like a DDK
        m = re.search(r'id=([A-Fa-f0-9]{30,})', tags_r.text)
        if m:
            return m.group(1)

    except Exception:
        pass

    return None


def _parse_dd_from_body(body: str) -> Optional[dict]:
    """Extract DataDome dd={} JSON from 403 response HTML."""
    m = re.search(r"var dd=(\{[^}]+\})", body)
    if not m:
        return None
    dd_str = m.group(1)
    dd_str = re.sub(r"'", '"', dd_str)
    try:
        return json.loads(dd_str)
    except json.JSONDecodeError:
        return None


class DataDomeSolver:
    """
    Generic DataDome cookie generator.
    
    Args:
        target_url: The protected website URL (e.g. "https://secure.qgiv.com/for/campaign")
        ddk: DataDome site key (auto-detected if not provided)
        proxy: HTTP proxy URL
        ddv: DataDome version (default "5.7.0", auto-detected in future)
        impersonate: curl_cffi TLS impersonation target
    """

    def __init__(
        self,
        target_url: str = None,
        ddk: str = None,
        proxy: str = None,
        ddv: str = "5.7.0",
        impersonate: str = IMPERSONATE,
    ):
        self.target_url = target_url
        self._proxy = proxy or PROXY_URL
        self._ddv = ddv
        self._impersonate = impersonate
        self._ddk = ddk

        if target_url and not self._ddk:
            self._ddk = extract_ddk_from_url(target_url, self._proxy)

    @property
    def ddk(self):
        return self._ddk

    @property
    def site_origin(self) -> str:
        """Extract origin from target_url."""
        if not self.target_url:
            return ""
        p = urlparse(self.target_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def site_domain(self) -> str:
        """Extract cookie domain from target_url."""
        if not self.target_url:
            return ""
        p = urlparse(self.target_url)
        return f".{p.netloc.split(':')[0]}"

    @property
    def request_path(self) -> str:
        """Extract path from target_url for DataDome request param."""
        if not self.target_url:
            return "/"
        p = urlparse(self.target_url)
        return p.path or "/"

    def _build_js_data(self, screen_w=1920, screen_h=1080, avail_w=1920, avail_h=1040,
                       outer_w=1920, outer_h=1080, device_memory=8, hw_concurrency=16):
        return {
            "opts": "ajaxListenerPath,endpoint",
            "ttst": _random_float(),
            "ifov": False,
            "tagpu": _random_float(),
            "glvd": "Google Inc. (Intel)",
            "glrd": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "hc": hw_concurrency, "br_oh": outer_h, "br_ow": outer_w,
            "ua": UA,
            "wbd": False, "wdif": False, "wdifrm": False, "npmtm": False,
            "br_h": screen_h, "br_w": screen_w,
            "nddc": 1, "rs_h": screen_h, "rs_w": screen_w, "rs_cd": 24,
            "phe": False, "nm": False, "jsf": False,
            "lg": "en-US", "pr": 1, "ars_h": avail_h, "ars_w": avail_w,
            "tz": TZ_OFFSET, "str_ss": True, "str_ls": True, "str_idb": True, "str_odb": False,
            "plgod": False, "plg": random.randint(5, 14),
            "plgne": True, "plgre": True, "plgof": False, "plggt": False, "pltod": False,
            "hcovdr": False, "hcovdr2": False, "plovdr": False, "plovdr2": False,
            "ftsovdr": False, "ftsovdr2": False,
            "lb": False, "eva": 33, "lo": False,
            "ts_mtp": 0, "ts_tec": False, "ts_tsa": False,
            "vnd": "Google Inc.", "bid": "NA",
            "mmt": "application/pdf,text/pdf",
            "plu": "PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer,Microsoft Edge PDF Viewer,WebKit built-in PDF",
            "hdn": False, "awe": False, "geb": False, "dat": False,
            "med": "defined",
            "aco": "probably", "acots": False,
            "acmp": "probably", "acmpts": True,
            "acw": "probably", "acwts": False,
            "acma": "maybe", "acmats": False,
            "acaa": "probably", "acaats": True,
            "ac3": "", "ac3ts": False,
            "acf": "probably", "acfts": False,
            "acmp4": "maybe", "acmp4ts": False,
            "acmp3": "probably", "acmp3ts": False,
            "acwm": "maybe", "acwmts": False,
            "ocpt": False,
            "vco": "", "vcots": False,
            "vch": "probably", "vchts": True,
            "vcw": "probably", "vcwts": True,
            "vc3": "maybe", "vc3ts": False,
            "vcmp": "", "vcmpts": False,
            "vcq": "", "vcqts": False,
            "vc1": "probably", "vc1ts": True,
            "dvm": device_memory,
            "sqt": False, "so": "landscape-primary", "wdw": True,
            "cokys": "bG9hZFRpbWVzY3NpYXBwL=",
            "ecpc": False,
            "lgs": True, "lgsod": False, "psn": True,
            "edp": True, "addt": True, "wsdc": True, "ccsr": True, "nuad": True,
            "bcda": True, "idn": True, "capi": False, "svde": False, "vpbq": True,
            "ucdv": False, "spwn": False, "emt": False, "bfr": False, "dbov": False,
            "prm": True, "tzp": TZ_NAME, "cvs": True, "usb": "defined",
            "jset": math.floor(time.time()),
        }

    def _build_le_js_data(self, screen_w=1920, screen_h=1080, avail_w=1920, avail_h=1040,
                          outer_w=1920, outer_h=1080, device_memory=8, hw_concurrency=16):
        num_moves = random.randint(80, 600)
        m_c_c = random.randint(0, 10)
        m_s_c = random.randint(0, 600)
        base = self._build_js_data(screen_w, screen_h, avail_w, avail_h,
                                   outer_w, outer_h, device_memory, hw_concurrency)
        base.update({
            "dcok": self.site_domain,
            "mp_cx": random.randint(200, 800), "mp_cy": random.randint(200, 600),
            "mp_tr": True, "mp_mx": random.randint(0, 50), "mp_my": random.randint(0, 50),
            "mp_sx": random.randint(200, 800), "mp_sy": random.randint(300, 700),
            "mm_md": random.randint(50, 300),
            "es_sigmdn": round(random.uniform(0.01, 0.15), 6),
            "es_mumdn": round(random.uniform(30, 200), 6),
            "es_distmdn": round(random.uniform(100, 600), 6),
            "es_angsmdn": round(random.uniform(0, 3.14), 6),
            "es_angemdn": round(random.uniform(0, 3.14), 6),
            "m_s_c": m_s_c, "m_m_c": num_moves, "m_c_c": m_c_c,
            "m_cm_r": round(m_c_c / num_moves if num_moves > 0 else 0, 6),
            "m_ms_r": round(num_moves / m_s_c if m_s_c > 0 else 0, 6),
        })
        event_counters = {
            "mousemove": num_moves, "pointermove": num_moves,
            "click": m_c_c, "scroll": m_s_c,
            "touchstart": 0, "touchend": 0, "touchmove": 0,
            "keydown": 0, "keyup": 0,
        }
        return base, event_counters

    def _post(self, payload: dict, headers: dict, timeout: int = 15) -> Optional[dict]:
        body = urlencode(payload)
        try:
            r = cffi_requests.post(
                DD_API, data=body, headers=headers,
                proxies={"http": self._proxy, "https": self._proxy},
                timeout=timeout, impersonate=self._impersonate,
            )
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    @staticmethod
    def _parse_cookie(cookie_str: str, fallback_domain: str = ".qgiv.com") -> Optional[Dict[str, Any]]:
        parts = cookie_str.split("; ")
        c = {}
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                c[k.lower()] = v
        dd = c.get("datadome")
        if not dd:
            return None
        return {
            "name": "datadome",
            "value": dd,
            "domain": c.get("domain", fallback_domain),
            "path": c.get("path", "/"),
            "expires": int(c.get("expires", -1)),
            "httpOnly": c.get("httponly", "false").lower() == "true",
            "secure": c.get("secure", "true").lower() == "true",
            "sameSite": c.get("samesite", "None"),
        }

    def solve_ch(self, cid: str = "null") -> Optional[Dict[str, Any]]:
        js_data = self._build_js_data()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "api-js.datadome.co",
            "Origin": self.site_origin,
            "Referer": self.target_url,
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="148", "Not/A)Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": UA,
        }
        payload = {
            "ddv": self._ddv,
            "eventCounters": [],
            "jsType": "ch",
            "ddk": self._ddk,
            "request": self.request_path,
            "responsePage": "origin",
            "cid": cid,
            "Referer": self.target_url,
            "jsData": json.dumps(js_data),
        }
        resp = self._post(payload, headers)
        if not resp:
            return None
        return self._parse_cookie(resp.get("cookie", ""), self.site_domain)

    def solve_le(self, cid: str) -> Optional[Dict[str, Any]]:
        js_data, event_counters = self._build_le_js_data()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "api-js.datadome.co",
            "Origin": self.site_origin,
            "Referer": self.target_url,
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="148", "Not/A)Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": UA,
        }
        payload = {
            "ddv": self._ddv,
            "eventCounters": json.dumps(event_counters),
            "jsType": "le",
            "ddk": self._ddk,
            "request": self.request_path,
            "responsePage": "origin",
            "cid": cid,
            "Referer": self.target_url,
            "jsData": json.dumps(js_data),
        }
        resp = self._post(payload, headers)
        if not resp:
            return None
        return self._parse_cookie(resp.get("cookie", ""), self.site_domain)

    def solve(self, response_body: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Full DataDome solve: CH cookie + LE cookie.
        
        Args:
            response_body: Optional 403 response HTML for challenge extraction.
        
        Returns:
            Cookie dict with {name, value, domain, path, expires, secure, sameSite}
        """
        if not self._ddk:
            return None

        ch = self.solve_ch()
        if not ch:
            return None

        time.sleep(random.uniform(0.3, 0.8))

        le = self.solve_le(ch["value"][:40])
        return le if le else ch


def solve(target_url: str, ddk: str = None, proxy: str = None) -> Optional[Dict[str, Any]]:
    """Quick one-shot: solve DataDome for a target URL."""
    solver = DataDomeSolver(target_url=target_url, ddk=ddk, proxy=proxy)
    return solver.solve()


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign"
    ddk = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"DataDome Solver (Generic)")
    print(f"  Target: {url}")
    if ddk:
        print(f"  DDK: {ddk} (manual)")
    print(f"  TLS: {IMPERSONATE}")
    print()

    if ddk:
        solver = DataDomeSolver(target_url=url, ddk=ddk, proxy=PROXY_URL)
    else:
        print("  Detecting DDK...")
        solver = DataDomeSolver(target_url=url, proxy=PROXY_URL)

    if not solver.ddk:
        print("  FAILED: Could not detect DataDome key (ddk)")
        print("  Provide manually: python solver.py <URL> <DDK>")
        sys.exit(1)

    print(f"  DDK: {solver.ddk}")
    print()

    result = solver.solve()
    if result:
        print(f"  OK datadome={result['value'][:50]}...")
        print(f"  Domain: {result['domain']}")
        print(f"  Secure: {result['secure']}")
    else:
        print(f"  FAILED")
        sys.exit(1)
