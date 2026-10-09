# -*- coding: utf-8 -*-
"""
Tender Radar KZ Commercial — SAMRUK TEST orchestrator

Назначение:
- читает активные профили commercial.profiles из Supabase;
- берёт только профили, где в sources выбран "samruk";
- собирает уникальные include_keywords;
- запускает samruk_collector_commercial_TEST_V2.py;
- НЕ пишет ничего в Supabase;
- НЕ трогает рабочий Goszakup;
- после запуска показывает краткий итог по output/samruk_tenders.json.

Нужны переменные среды:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Опционально:
  SAMRUK_MAX_PAGES      по умолчанию 1
  SAMRUK_DETAIL_LIMIT   по умолчанию 3
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"


def env(name, default=""):
    return os.getenv(name, default).strip()


def cfg():
    url = env("SUPABASE_URL")
    key = env("SUPABASE_SERVICE_ROLE_KEY")
    if not url:
        raise RuntimeError("SUPABASE_URL не задан")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY не задан")
    return {"SUPABASE_URL": url, "SUPABASE_SERVICE_ROLE_KEY": key}


def headers(c):
    key = c["SUPABASE_SERVICE_ROLE_KEY"]
    return {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        # Таблицы проекта находятся в схеме commercial.
        # Без этого заголовка PostgREST обращается не к той схеме.
        "Accept-Profile": "commercial",
    }


def rest_get(c, path):
    url = c["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, headers=headers(c), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Supabase HTTP {e.code}: {body}"
        ) from e


def normalize_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [x.strip() for x in v.split(",") if x.strip()]
    return []


def load_profiles(c):
    return rest_get(
        c,
        "profiles?select=id,client_id,name,include_keywords,exclude_keywords,sources,active"
        "&active=eq.true&order=id.asc",
    )


def samruk_profiles_and_keywords(c):
    profiles = []
    keywords = []
    seen = set()

    for row in load_profiles(c):
        sources = [x.lower() for x in normalize_list(row.get("sources"))]
        if "samruk" not in sources:
            continue

        profiles.append(row)

        for word in normalize_list(row.get("include_keywords")):
            key = word.lower()
            if key not in seen:
                seen.add(key)
                keywords.append(word)

    return profiles, keywords


def run_collector(keywords):
    collector = ROOT / "samruk_collector_commercial_TEST_V2.py"
    if not collector.exists():
        raise RuntimeError(
            "Не найден samruk_collector_commercial_TEST_V2.py рядом с оркестратором"
        )

    child_env = os.environ.copy()
    child_env["SAMRUK_KEYWORDS"] = json.dumps(keywords, ensure_ascii=False)

    # Безопасный первый тест: немного страниц и немного подробных карточек.
    child_env.setdefault("SAMRUK_MAX_PAGES", "1")
    child_env.setdefault("SAMRUK_DETAIL_LIMIT", "3")

    print()
    print("RUN:", collector.name)
    print("SAMRUK_MAX_PAGES:", child_env["SAMRUK_MAX_PAGES"])
    print("SAMRUK_DETAIL_LIMIT:", child_env["SAMRUK_DETAIL_LIMIT"])

    proc = subprocess.run(
        [sys.executable, str(collector)],
        cwd=str(ROOT),
        env=child_env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{collector.name} завершился с кодом {proc.returncode}"
        )


def load_result():
    path = OUT / "samruk_tenders.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Не удалось прочитать {path}: {e}")
    return data if isinstance(data, list) else []


def main():
    print("=" * 72)
    print("TENDER RADAR KZ COMMERCIAL — SAMRUK TEST V2 / DRY RUN")
    print("NO SUPABASE WRITE • NO GOSZAKUP CHANGES")
    print("=" * 72)

    c = cfg()
    profiles, keywords = samruk_profiles_and_keywords(c)

    print("SAMRUK ACTIVE PROFILES:", len(profiles))
    for p in profiles:
        print(
            f'  profile={p.get("id")} client={p.get("client_id")} '
            f'name={p.get("name")}'
        )

    print("SAMRUK COMMERCIAL KEYWORDS:", len(keywords))
    for word in keywords:
        print("  -", word)

    if not profiles:
        print("STOP: нет активных профилей с источником samruk.")
        return 0

    if not keywords:
        print("STOP: у профилей Samruk нет include_keywords.")
        return 0

    run_collector(keywords)

    rows = load_result()
    print()
    print("=" * 72)
    print("SAMRUK TEST RESULT")
    print("=" * 72)
    print("ROWS FOUND:", len(rows))

    for r in rows[:10]:
        print(
            "-",
            r.get("source_lot_id"),
            "|",
            str(r.get("title") or "")[:100],
        )

    print()
    print("SAFE END: данные только собраны в output; Supabase не изменялся.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
