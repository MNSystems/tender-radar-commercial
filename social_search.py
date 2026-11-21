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
    for i in range(4):
        try:
            r = requests.get(BASE + path, params=params, headers=z.HEADERS, timeout=(15, 40))
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except requests.RequestException:
            pass
        time.sleep(3 + i * 4)
    return None


def org_email(name):
    q = re.sub(r'ТОО|ИП|АО|["«»]', " ", name).strip()
    q = re.sub(r"\s+", " ", q)[:60]
    d = gz("/organizations/", {"q": q, "limit": 10}) or {}
    best = None
    for r in d.get("results") or []:
        if norm(r.get("name_ru") or r.get("name")) == norm(name):
            best = r; break
    return (best or {}).get("email") or ""


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


def main():
    items = json.loads(gzip.decompress(base64.b64decode(os.environ["NAMES"])))
    use_ddg = os.environ.get("DDG", "1") == "1"
    print("SO_START", len(items))
    for n, it in enumerate(items):
        i, name, city = it[0], it[1], (it[2] if len(it) > 2 else "")
        row = {"i": i, "src": []}
        em = org_email(name)
        dom = em.split("@")[-1].lower().strip() if "@" in em else ""
        if dom and dom not in FREE and "." in dom:
            url, so = site_socials(dom)
            row["site"] = url or f"https://{dom}"
            row["src"].append("сайт" if url else "домен почты")
            row.update(so)
        if use_ddg and not any(k in row for k in ("ig", "fb")):
            so = ddg(name, city)
            if so:
                row["src"].append("поиск")
                for k, v in so.items():
                    row.setdefault(k, v)
            time.sleep(1.5)
        print("SO_ROW " + json.dumps(row, ensure_ascii=False))
        time.sleep(0.3)
        if n % 50 == 0:
            print("SO_PROGRESS", n)
    print("SO_DONE")


if __name__ == "__main__":
    main()
