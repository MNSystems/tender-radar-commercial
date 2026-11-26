"""Сайты и соцсети компаний (только чтение, только публичные сведения).

Вход: переменная NAMES — gzip+base64 JSON [[idx, "название"], ...]
1) госзакуп /organizations/?q=название -> e-mail организации -> корпоративный домен
2) главная страница сайта -> ссылки Instagram / Facebook / YouTube / Telegram / TikTok / LinkedIn
3) (по желанию) поиск DuckDuckGo по названию
Печатает SO_ROW {"i","site","ig","fb","yt","tg","tt","li","src"} — без e-mail и телефонов.
"""
import base64, gzip, json, os, re, time
from urllib.parse import quote_plus, unquote
import requests
import collector_zakup as z

BASE = "https://zakup.gov.kz/api/core/api/public"
FREE = set("""mail.ru inbox.ru list.ru bk.ru gmail.com yandex.ru yandex.kz ya.ru icloud.com outlook.com hotmail.com
internet.ru rambler.ru mail.kz yahoo.com me.com live.com googlemail.com proton.me protonmail.com nursat.kz
inbox.kz bk.kz box.az ukr.net qip.ru""".split())
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "ru-RU,ru;q=0.9"}
PAT = {
    "ig": re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,40})", re.I),
    "fb": re.compile(r"facebook\.com/((?:profile\.php\?id=\d+)|[A-Za-z0-9_.\-]{3,60})", re.I),
    "yt": re.compile(r"youtube\.com/((?:channel/|c/|user/|@)[A-Za-z0-9_.\-]{2,60})", re.I),
    "tg": re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,40})", re.I),
    "tt": re.compile(r"tiktok\.com/(@[A-Za-z0-9_.]{2,40})", re.I),
    "li": re.compile(r"linkedin\.com/(company/[A-Za-z0-9_.\-]{2,80})", re.I),
}
BAD = {"p", "reel", "explore", "accounts", "sharer", "sharer.php", "share", "plugins", "dialog", "tr", "intent", "watch",
       "embed", "privacy", "legal", "about", "help", "login", "home", "share.php", "joinchat", "iframe_api", "s", "stories"}
URL = {"ig": "https://instagram.com/{}", "fb": "https://facebook.com/{}", "yt": "https://youtube.com/{}",
       "tg": "https://t.me/{}", "tt": "https://tiktok.com/{}", "li": "https://linkedin.com/{}"}


def norm(s):
    s = (s or "").upper().replace("Ё", "Е")
    s = re.sub(r"ТОВАРИЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ|\bТОО\b|\bИП\b|\bАО\b|\bLLP\b|\bТОВАРИЩЕСТВО\b", " ", s)
    return re.sub(r"[^0-9A-ZА-ЯӘҒҚҢӨҰҮҺІ]+", "", s)


def gz(path, params):
    for i in range(2):
        try:
            r = requests.get(BASE + path, params=params, headers=z.HEADERS, timeout=(10, 25))
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except requests.RequestException:
            pass
        print('SO_GZ', getattr(r, 'status_code', '?') if 'r' in dir() else 'exc')
        time.sleep(2)
    return None


def org_email(name):
    q = re.sub(r'ТОО|ИП|АО|["«»]', " ", name).strip()
    q = re.sub(r"\s+", " ", q)[:60]
    d = gz("/organizations/", {"q": q, "limit": 5}) or {}
    rs = d.get("results") or []
    for r in rs[:4]:
        oid = r.get("id")
        if not oid:
            continue
        det = gz(f"/organizations/{oid}/", None) or {}
        if norm(det.get("name_ru") or det.get("name")) == norm(name) or (len(rs) == 1 and norm(name)[:5] in norm(det.get("name_ru") or "")):
            return det.get("email") or ""
    return ""


def socials(html):
    out = {}
    for k, p in PAT.items():
        for m in p.finditer(html):
            v = m.group(1).rstrip("/.")
            if v.split("/")[0].split("?")[0].lower() in BAD:
                continue
            out.setdefault(k, URL[k].format(v))
    return out


def site_socials(domain):
    for url in (f"https://{domain}", f"https://www.{domain}", f"http://{domain}"):
        try:
            r = requests.get(url, headers=UA, timeout=(8, 20), allow_redirects=True)
            if r.status_code < 400 and len(r.text) > 300:
                return r.url, socials(r.text)
        except requests.RequestException:
            continue
    return "", {}


BING_OK = [True]
def bing(name, city):
    if not BING_OK[0]:
        return {}
    q = f'{name} {city} instagram'.strip()
    try:
        r = requests.get("https://www.bing.com/search", params={"q": q, "setlang": "ru", "cc": "KZ"}, headers=UA, timeout=(8, 20))
    except requests.RequestException:
        return {}
    if r.status_code != 200 or "b_algo" not in r.text:
        BING_OK[0] = False
        print("SO_BING_BLOCKED", r.status_code, len(r.text))
        return {}
    blocks = re.findall(r'<li class="b_algo".*?</li>', r.text, re.S)[:8]
    key = norm(name).lower()
    res = {}
    for b in blocks:
        so = socials(b)
        txt = norm(re.sub("<[^>]+>", " ", b)).lower()
        if key and key[:5] not in txt:
            continue
        for k, v in so.items():
            res.setdefault(k, v)
    return res


DDG_OK = [True]
def ddg(name, city):
    if not DDG_OK[0]:
        return {}
    q = f'{name} {city} instagram'.strip()
    try:
        r = requests.post("https://html.duckduckgo.com/html/", data={"q": q}, headers=UA, timeout=(8, 20))
    except requests.RequestException:
        return {}
    if r.status_code != 200 or "result__a" not in r.text:
        DDG_OK[0] = False
        print("SO_DDG_BLOCKED", r.status_code)
        return {}
    links = [unquote(u) for u in re.findall(r'uddg=([^"&]+)', r.text)]
    key = norm(name)[:6].lower()
    res = {}
    for u in links[:10]:
        s = socials(u)
        for k, v in s.items():
            if k == "ig":
                handle = v.rsplit("/", 1)[-1].lower()
                if key and not any(t in handle for t in [key[:4]]):
                    continue
            res.setdefault(k, v)
    return res


def probe(items):
    for it in items[:3]:
        q = f"{it[1]} {it[2]} instagram"
        for nm, url, params in (("bing_rss", "https://www.bing.com/search", {"q": q, "format": "rss"}),
                                ("ddg_lite", "https://lite.duckduckgo.com/lite/", {"q": q}),
                                ("mojeek", "https://www.mojeek.com/search", {"q": q}),
                                ("yandex", "https://yandex.kz/search/", {"text": q}),
                                ("startpage", "https://www.startpage.com/do/search", {"q": q})):
            try:
                r = requests.get(url, params=params, headers=UA, timeout=(8, 20))
                print("SO_SE", nm, r.status_code, len(r.text), json.dumps(socials(r.text), ensure_ascii=False)[:300], r.text.count("instagram.com"))
            except Exception as e:
                print("SO_SE_ERR", nm, e)
    return
    for it in items[:4]:
        nm = it[1]; q = re.sub(r'ТОО|ИП|АО|["«»]', " ", nm).strip()
        for params in ({"q": q}, {"q": nm}, {"search": q}, {"name_ru": nm}, {"name": q}, {"name_ru__icontains": q}):
            p = dict(params, limit=3)
            try:
                r = requests.get(BASE + "/organizations/", params=p, headers=z.HEADERS, timeout=(10, 25))
                d = r.json() if r.status_code == 200 else {}
                print("SO_PROBE", json.dumps({"p": params, "st": r.status_code, "count": d.get("count"), "names": [x.get("name_ru") for x in (d.get("results") or [])[:3]]}, ensure_ascii=False))
            except Exception as e:
                print("SO_PROBE_ERR", params, e)


def webchk():
    """Проверка кандидатов-доменов: заголовок, телефоны на странице, соцсети. Вывод зашифрован."""
    import socket, html as H
    from concurrent.futures import ThreadPoolExecutor
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.fernet import Fernet
    doms = json.loads(gzip.decompress(open("web_dom.json.gz", "rb").read()))
    CH = int(os.environ.get("CHUNK", "0")); NCH = int(os.environ.get("NCHUNK", "1"))
    doms = doms[CH::NCH]
    pub = serialization.load_pem_public_key(base64.b64decode(os.environ["PUBKEY"]))
    k = Fernet.generate_key(); f = Fernet(k)
    print("SO_KEY " + base64.b64encode(pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode())
    PH = re.compile(r"(?:\+?[78])?[\s\-\(\.]*\d{3}[\s\-\)\.]*\d{3}[\s\-\.]*\d{2}[\s\-\.]*\d{2}")
    def one(d):
        try:
            socket.getaddrinfo(d, 443)
        except Exception:
            return
        for url in (f"https://{d}", f"http://{d}"):
            try:
                r = requests.get(url, headers=UA, timeout=(6, 15), allow_redirects=True)
                if r.status_code >= 400 or len(r.text) < 300:
                    continue
                t = r.text[:600000]
                title = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
                title = re.sub(r"\s+", " ", H.unescape(title.group(1))).strip()[:150] if title else ""
                ph = sorted({re.sub(r"\D", "", p)[-10:] for p in PH.findall(t) if len(re.sub(r"\D", "", p)) >= 10})[:40]
                row = {"d": d, "u": r.url[:120], "ti": title, "ph": ph, "alm": ("алматы" in t.lower() or "almaty" in t.lower()), "so": socials(t)}
                print("SO_ENC " + f.encrypt(json.dumps(row, ensure_ascii=False).encode()).decode(), flush=True)
                return
            except Exception:
                continue
    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(one, doms))
    print("SO_DONE", len(doms))


def main():
    if os.environ.get("DDG") == "webchk":
        webchk(); return
    items = json.loads(gzip.decompress(base64.b64decode(os.environ["NAMES"])))
    use_ddg = os.environ.get("DDG", "1") == "1"
    if os.environ.get("DDG", "").startswith("orgfull"):
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.fernet import Fernet
        pub = serialization.load_pem_public_key(base64.b64decode(os.environ["PUBKEY"]))
        k = Fernet.generate_key(); f = Fernet(k)
        print("SO_KEY " + base64.b64encode(pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode())
        from concurrent.futures import ThreadPoolExecutor
        def one(it):
            i, name = it[0], it[1]
            q = re.sub(r'ТОО|ИП|АО|["«»]', " ", name).strip()[:60]
            d = gz("/organizations/", {"q": q, "limit": 5}) or {}
            out = []
            for r in (d.get("results") or [])[:3]:
                det = gz(f"/organizations/{r.get('id')}/", None) or {}
                if det: out.append(det)
            print("SO_ENC " + f.encrypt(json.dumps({"i": i, "name": name, "res": out}, ensure_ascii=False).encode()).decode(), flush=True)
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(one, items))
        return
    if os.environ.get("DDG") == "flagma":
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.fernet import Fernet
        import html as H
        pub = serialization.load_pem_public_key(base64.b64decode(os.environ["PUBKEY"]))
        k = Fernet.generate_key(); f = Fernet(k)
        print("SO_KEY " + base64.b64encode(pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode())
        from concurrent.futures import ThreadPoolExecutor
        def clean(x): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", x))).strip()
        def one(fid):
            s2 = ""
            for _ in range(3):
                try:
                    r = requests.get(f"https://flagma.kz/{fid}/", headers=UA, timeout=(10, 30))
                    if r.status_code == 200 and len(r.text) > 2000: s2 = r.text; break
                except Exception: pass
                time.sleep(2)
            t = H.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"<script.*?</script>|<style.*?</style>", "", s2, flags=re.S)))
            L = [l.strip() for l in t.split("\n") if l.strip()]
            def after(key, n=1):
                for i, l in enumerate(L):
                    if l == key: return L[i + n] if i + n < len(L) else ""
                return ""
            m = re.search(r"<h1[^>]*>(.*?)</h1>", s2, re.S)
            d = dict(id=fid, name=clean(m.group(1)) if m else "", rep=after("Представитель компании"), role=after("Представитель компании", 2),
                     phones=list(dict.fromkeys(re.findall(r"href=['\"]tel:([^'\"]+)['\"]", s2))), city=after("фактический") or after("Адрес"),
                     activity=after("Деятельность компании")[:300], registered=after("Регистрация:"))
            md = re.search(r'<meta name="description" content="([^"]*)"', s2); d["about"] = H.unescape(md.group(1))[:300] if md else ""
            print("SO_ENC " + f.encrypt(json.dumps(d, ensure_ascii=False).encode()).decode(), flush=True)
            time.sleep(0.2)
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(one, items))
        print("SO_DONE")
        return
    if os.environ.get("DDG", "").startswith("mw"):
        MODE = os.environ["DDG"]; CH = int(os.environ.get("CHUNK", "0")); NCH = int(os.environ.get("NCHUNK", "1"))
        import html as H
        from concurrent.futures import ThreadPoolExecutor
        MW = "https://eep.mitwork.kz"
        def g(u):
            for _ in range(3):
                try:
                    r = requests.get(u, headers=UA, timeout=(10, 25))
                    if r.status_code == 200: time.sleep(0.8); return r.text
                    print("SO_MW_ERR", r.status_code, u[-40:], flush=True)
                except Exception as e: print("SO_MW_ERR", str(e)[:60], u[-40:], flush=True)
                time.sleep(6)
            return ""
        def txt(x): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", x))).strip()
        def field(t, key):
            m = re.search(re.escape(key) + r"\s*</t[hd]>\s*<td[^>]*>(.*?)</td>", t, re.S)
            return txt(m.group(1)) if m else ""
        skip = set(str(x) for x in items)
        ids = []
        for p in range(1, 200 if MODE in ("mitwork", "mwlist") else 1):
            t = g(f"{MW}/ru/publics/buys?filter%5Bstatus%5D=active&per-page=50&page={p}")
            new = [i for i in dict.fromkeys(re.findall(r"/ru/publics/buy/(\d+)", t)) if i not in ids]
            if not new: break
            ids += new
        ids = [i for i in ids if i not in skip]
        print("SO_MW_IDS", len(ids), flush=True)
        if MODE == "mwlist":
            print("SO_MW_IDLIST " + json.dumps(ids)); return
        subj = {}
        def buy(i):
            t = g(f"{MW}/ru/publics/buy/{i}")
            if not t: return
            sid = (re.search(r"/ru/publics/subject/(\d+)", t) or [None, ""])[1]
            lots = []
            m = re.search(r"Лоты в объявлении(.*?)</table>", t, re.S)
            if m:
                for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
                    tds = [txt(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                    if len(tds) >= 6: lots.append(tds[:7])
            title = txt((re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S) or [None, ""])[1]) if re.search(r"<h1", t) else ""
            d = {"id": i, "title": title or field(t, "Наименование на русском языке"), "name_ru": field(t, "Наименование на русском языке"),
                 "start": field(t, "Дата начала приема заявок"), "end": field(t, "Дата окончания приема заявок"),
                 "org": field(t, "Организатор"), "method": field(t, "Способ закупки"), "type": field(t, "Тип закупки"), "sid": sid, "lots": lots}
            print("SO_MW_BUY " + json.dumps(d, ensure_ascii=False), flush=True)
            if sid: subj[sid] = 1
        def subject(sid):
            if True:
                u = g(f"{MW}/ru/publics/subject/{sid}")
                c = re.search(r"Контакты(.*?)</table>", u, re.S)
                rows = []
                if c:
                    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", c.group(1), re.S):
                        tds = [txt(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                        if tds: rows.append(tds)
                sd = {"sid": sid, "name": txt((re.search(r"<h1[^>]*>(.*?)</h1>", u, re.S) or [None, ""])[1]), "bin": field(u, "БИН"),
                      "size": field(u, "Размерность предприятия"), "contacts": rows}
                if sd["bin"]:
                    dd = gz("/organizations/", {"q": sd["bin"], "limit": 2}) or {}
                    for r in (dd.get("results") or [])[:1]:
                        det = gz(f"/organizations/{r.get('id')}/", None) or {}
                        sd["email"] = det.get("email") or ""; sd["website"] = det.get("website") or ""
                        sd["gz_phone"] = det.get("phone") or ""
                        sd["director"] = ", ".join(x.get("full_name") or "" for x in det.get("directors") or [])
                dom = ""
                if sd.get("website"): dom = re.sub(r"^https?://(www\.)?", "", sd["website"]).split("/")[0]
                elif "@" in sd.get("email", ""):
                    e = sd["email"].split("@")[-1].lower().strip()
                    if e not in FREE: dom = e
                if dom:
                    url, so = site_socials(dom); sd["site"] = url or ("https://" + dom); sd.update(so)
                print("SO_MW_SUBJ " + json.dumps(sd, ensure_ascii=False), flush=True)
        if MODE == "mwbuys":
            for i in [str(x) for x in items][CH::NCH]:
                buy(i); time.sleep(2.5)
            print("SO_DONE"); return
        if MODE == "mwsubj":
            for sid in [str(x) for x in items][CH::NCH]:
                subject(sid); time.sleep(2.5)
            print("SO_DONE"); return
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(buy, ids))
        print("SO_MW_T buys", round(time.time() - t0), len(subj), flush=True)
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(subject, list(subj)))
        print("SO_MW_T subj", round(time.time() - t0), flush=True)
        print("SO_DONE")
        return
    if os.environ.get("DDG") == "raw":
        for n, u in enumerate(items):
            try:
                r = requests.get(u, headers=UA, timeout=(10, 40), allow_redirects=True)
                b = base64.b64encode(gzip.compress(r.text.encode())).decode()
                for k in range(0, len(b), 30000):
                    print(f"SO_RAW {n} {k//30000} " + b[k:k+30000])
                print("SO_RAWEND", n, r.status_code, len(r.text))
            except Exception as e:
                print("SO_RAWEND", n, "ERR", str(e)[:100])
        return
    if os.environ.get("DDG") == "fetch":
        for u in items:
            try:
                r = requests.get(u, headers=UA, timeout=(10, 30), allow_redirects=True)
                t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
                links = sorted(set(re.findall(r'href="([^"]{5,120})"', r.text)))[:80]
                t = re.sub(r"<[^>]+>", " ", t); t = re.sub(r"\s+", " ", t)
                print("SO_FETCH", u, r.status_code, r.url[:100]); print("SO_TXT", t[:int(os.environ.get("TXTN","7000"))]); print("SO_LINKS", " ".join(links))
            except Exception as e:
                print("SO_FETCH", u, "ERR", str(e)[:100])
        return
    if os.environ.get("DDG") == "sites":
        for u in items:
            try:
                r = requests.get(u, headers=UA, timeout=(10, 25), allow_redirects=True)
                print("SO_SITE", u, r.status_code, len(r.text), r.url[:80])
            except Exception as e:
                print("SO_SITE", u, "ERR", str(e)[:80])
        return
    if os.environ.get("DDG") == "probe":
        probe(items); return
    print("SO_START", len(items))
    from concurrent.futures import ThreadPoolExecutor

    def one(it):
        t0 = time.time()
        i, name, city = it[0], it[1], (it[2] if len(it) > 2 else "")
        row = {"i": i, "src": []}
        try:
            em = org_email(name)
        except Exception:
            em = ""
        dom = em.split("@")[-1].lower().strip() if "@" in em else ""
        if dom and dom not in FREE and "." in dom:
            url, so = site_socials(dom)
            row["site"] = url or f"https://{dom}"
            row["src"].append("сайт" if url else "домен почты")
            row.update(so)
        row["t"] = round(time.time() - t0, 1); row["em"] = bool(em)
        print("SO_ROW " + json.dumps(row, ensure_ascii=False), flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, items))
    print("SO_DONE")


if __name__ == "__main__":
    main()
