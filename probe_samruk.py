"""Проверка доступности сайта Самрука с серверов GitHub (только чтение)."""
import requests, time
for url in ["https://zakup.sk.kz/", "https://zakup.sk.kz/#/ext", "https://zakup.sk.kz/eprocsearch/api/external/adverts?page=0&size=1", "https://www.sk.kz/", "https://goszakup.gov.kz/"]:
    t = time.time()
    try:
        r = requests.get(url, timeout=(15, 40), headers={"User-Agent": "Mozilla/5.0"})
        print(f"SAMRUK_PROBE {url} -> {r.status_code} {len(r.content)}b {time.time()-t:.1f}s")
    except Exception as e:
        print(f"SAMRUK_PROBE {url} -> ERROR {type(e).__name__} {time.time()-t:.1f}s {str(e)[:120]}")
