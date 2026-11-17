"""Пробный запрос к открытому API zakup.gov.kz (только чтение, без токена)."""
import json, requests
B = "https://zakup.gov.kz/api/core/api/public/"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def show(path, params=None):
    try:
        r = requests.get(B + path, params=params, headers=H, timeout=(20, 60))
        t = r.text
        print(f"ZAKUP {path} {params} -> {r.status_code} len={len(t)}")
        try:
            j = r.json()
            if isinstance(j, dict):
                print("ZAKUP keys", list(j.keys())[:20])
                items = j.get("results") or j.get("items") or j.get("data") or []
                if isinstance(items, list) and items:
                    print("ZAKUP count", j.get("count"), "first", json.dumps(items[0], ensure_ascii=False)[:1500])
            elif isinstance(j, list) and j:
                print("ZAKUP list", len(j), json.dumps(j[0], ensure_ascii=False)[:1500])
        except Exception:
            print("ZAKUP body", t[:400].replace("\n", " "))
    except Exception as e:
        print(f"ZAKUP {path} ERROR {e!r}"[:300])
show("")
show("lots/", {"limit": 2})
show("lots/", {"limit": 2, "search": "освещение"})
show("lots/", {"limit": 2, "name_ru": "освещение"})
show("announcements/", {"limit": 2})
show("trd-buy/", {"limit": 2})
