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


def main():
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
    if os.environ.get("DDG") == "fetch":
        for u in items:
            try:
                r = requests.get(u, headers=UA, timeout=(10, 30), allow_redirects=True)
                t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
                links = sorted(set(re.findall(r'href="([^"]{5,120})"', r.text)))[:80]
                t = re.sub(r"<[^>]+>", " ", t); t = re.sub(r"\s+", " ", t)
                print("SO_FETCH", u, r.status_code, r.url[:100]); print("SO_TXT", t[:2500]); print("SO_LINKS", " ".join(links))
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
