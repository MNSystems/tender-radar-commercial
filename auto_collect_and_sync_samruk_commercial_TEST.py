# -*- coding: utf-8 -*-
"""
Tender Radar KZ Commercial — SAMRUK -> Supabase TEST SYNC

Назначение:
1) читает active=true профили commercial.profiles;
2) берет только профили, где sources содержит "samruk";
3) запускает samruk_collector_commercial_TEST_V2.py;
4) читает output/samruk_tenders.json;
5) безопасно дедуплицирует лоты по source_lot_id;
6) UPSERT только source_code="samruk" в commercial.tenders;
7) создает/обновляет совпадения только для Samruk-профилей
   в commercial.client_tender_matches.

ВАЖНО:
- рабочий Goszakup НЕ трогает;
- существующие Samruk-строки массово НЕ деактивирует;
- Telegram НЕ запускает;
- это первый безопасный тест записи Samruk в Supabase.

Env:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Optional:
  SAMRUK_MAX_PAGES      default 1
  SAMRUK_DETAIL_LIMIT   default 3
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)


def env(name, default=""):
    return os.getenv(name, default).strip()


def get_config():
    cfg = {
        "SUPABASE_URL": env("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": env("SUPABASE_SERVICE_ROLE_KEY"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise RuntimeError("Missing configuration: " + ", ".join(missing))
    return cfg


def headers(cfg, *, write=False):
    key = cfg["SUPABASE_SERVICE_ROLE_KEY"]
    h = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "Accept-Profile": "commercial",
    }
    if write:
        h.update({
            "Content-Type": "application/json",
            "Content-Profile": "commercial",
        })
    return h


def http_error(prefix, e):
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return RuntimeError(f"{prefix}: HTTP {e.code}: {body}")


def rest_get(cfg, path):
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, headers=headers(cfg), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise http_error("Supabase GET", e) from e


def rest_post(cfg, path, payload, prefer="return=minimal"):
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers(cfg, write=True), "Prefer": prefer},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise http_error("Supabase POST", e) from e


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


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


def load_profiles(cfg):
    return rest_get(
        cfg,
        "profiles?select=id,client_id,name,include_keywords,exclude_keywords,sources,active"
        "&active=eq.true&order=id.asc",
    )


def samruk_profiles_and_keywords(cfg):
    profiles = []
    keywords = []
    seen = set()

    for row in load_profiles(cfg):
        sources = [x.lower() for x in normalize_list(row.get("sources"))]
        if "samruk" not in sources:
            continue

        profiles.append(row)

        for word in normalize_list(row.get("include_keywords")):
            k = word.lower()
            if k not in seen:
                seen.add(k)
                keywords.append(word)

    return profiles, keywords


def run_collector(keywords):
    collector = ROOT / "samruk_collector_commercial_TEST_V2.py"
    if not collector.exists():
        raise RuntimeError(
            "Не найден samruk_collector_commercial_TEST_V2.py в корне репозитория"
        )

    child_env = os.environ.copy()
    child_env["SAMRUK_KEYWORDS"] = json.dumps(keywords, ensure_ascii=False)
    child_env.setdefault("SAMRUK_MAX_PAGES", "1")
    child_env.setdefault("SAMRUK_DETAIL_LIMIT", "3")

    print("RUN COLLECTOR:", collector.name)
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


def merge_rows(rows):
    """
    Один и тот же lot может найден по нескольким ключевым словам.
    В Supabase нужен один tender на (source_code, source_lot_id).
    При этом сохраняем полный список search_keywords в raw.
    """
    merged = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        lot_id = str(row.get("source_lot_id") or "").strip()
        if not lot_id:
            continue

        raw = row.get("raw")
        if not isinstance(raw, dict):
            raw = {}

        keyword = str(raw.get("keyword") or row.get("category") or "").strip()

        if lot_id not in merged:
            item = dict(row)
            item["source_code"] = "samruk"
            item_raw = dict(raw)
            item_raw["search_keywords"] = [keyword] if keyword else []
            item["raw"] = item_raw
            merged[lot_id] = item
            continue

        current = merged[lot_id]
        current_raw = current.get("raw") or {}
        found = normalize_list(current_raw.get("search_keywords"))
        if keyword and keyword.lower() not in {x.lower() for x in found}:
            found.append(keyword)
        current_raw["search_keywords"] = found

        # Предпочитаем более обогащенную detailed-карточку.
        cur_detail = bool(current_raw.get("detail_checked"))
        new_detail = bool(raw.get("detail_checked"))

        if new_detail and not cur_detail:
            replacement = dict(row)
            replacement["source_code"] = "samruk"
            replacement_raw = dict(raw)
            replacement_raw["search_keywords"] = found
            replacement["raw"] = replacement_raw
            merged[lot_id] = replacement
        else:
            current["raw"] = current_raw

    return list(merged.values())


# Точная структура commercial.tenders подтверждена в Supabase.
# В таблице НЕТ status_code. Пишем только реально существующие поля.
ALLOWED_TENDER_FIELDS = {
    "source_code",
    "source_tender_id",
    "source_lot_id",
    "public_url",
    "title",
    "description",
    "customer_name",
    "customer_bin",
    "region",
    "procurement_method",
    "status_name",
    "amount",
    "currency",
    "quantity",
    "unit",
    "category",
    "published_at",
    "started_at",
    "expires_at",
    "is_active",
    "raw",
}


def clean_for_supabase(rows):
    out = []
    for row in rows:
        clean = {k: row.get(k) for k in ALLOWED_TENDER_FIELDS if k in row}
        clean["source_code"] = "samruk"
        out.append(clean)
    return out


def upload_tenders(cfg, rows):
    if not rows:
        print("STOP: Samruk returned 0 rows; Supabase unchanged.")
        return 0

    endpoint = "tenders?on_conflict=source_code,source_lot_id"
    sent = 0

    for start in range(0, len(rows), 100):
        batch = rows[start:start + 100]
        rest_post(
            cfg,
            endpoint,
            batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        sent += len(batch)
        print("SYNC samruk:", sent, "/", len(rows))

    return sent


def tender_text(t):
    parts = [
        str(t.get("title") or ""),
        str(t.get("description") or ""),
        str(t.get("category") or ""),
    ]

    raw = t.get("raw")
    if isinstance(raw, dict):
        parts.extend(normalize_list(raw.get("search_keywords")))

    return " ".join(parts).lower()


def flexible_exclude_hit(text, word):
    """
    Более устойчивое исключение для русских словоформ.

    Пример:
      профиль исключает "обслуживание"
      тендер содержит "обслуживанию"
      -> считаем совпадением по основе "обслуживан".

    Сначала проверяем обычное вхождение целого слова/фразы.
    Затем для одного слова пробуем убрать типичное русское окончание.
    """
    word = str(word or "").strip().lower()
    if not word:
        return False

    if word in text:
        return True

    # Для фраз не делаем агрессивное усечение: слишком велик риск ложных совпадений.
    if " " in word:
        return False

    endings = (
        "иями", "ями", "ами",
        "ого", "ему", "ому", "ыми", "ими",
        "ия", "ие", "ий", "ый", "ая", "ое",
        "ой", "ей", "ом", "ем",
        "ка",
        "а", "я", "ы", "и", "е", "у", "ю",
    )

    for ending in endings:
        if word.endswith(ending):
            stem = word[:-len(ending)]
            if len(stem) >= 5 and stem in text:
                return True

    return False


def auto_match_profiles(cfg, profiles):
    print("AUTO MATCH SAMRUK: start")

    tenders = rest_get(
        cfg,
        "tenders?select=id,source_code,title,description,category,is_active,raw"
        "&source_code=eq.samruk&is_active=eq.true"
        "&limit=5000",
    )

    matches_to_upsert = []

    for p in profiles:
        sources = [x.lower() for x in normalize_list(p.get("sources"))]
        if "samruk" not in sources:
            continue

        include_words = [
            x.lower() for x in normalize_list(p.get("include_keywords"))
        ]
        exclude_words = [
            x.lower() for x in normalize_list(p.get("exclude_keywords"))
        ]

        if not include_words:
            continue

        for t in tenders:
            text = tender_text(t)
            matched = [w for w in include_words if w and w in text]
            excluded = [
                w for w in exclude_words
                if flexible_exclude_hit(text, w)
            ]

            if not matched or excluded:
                if matched and excluded:
                    print(
                        f"EXCLUDED: profile={p['id']} tender={t['id']} "
                        f"exclude={excluded}"
                    )
                continue

            matches_to_upsert.append({
                "client_id": p["client_id"],
                "profile_id": p["id"],
                "tender_id": t["id"],
                "relevance_score": 100,
                "matched_keyword": matched,
                "match_reason": {
                    "source": "samruk",
                    "include": matched,
                    "exclude": [],
                    "rule": "automatic keyword match",
                },
                "status": "new",
            })

    if not matches_to_upsert:
        print("AUTO MATCH SAMRUK: no qualifying matches")
        return 0

    synced = 0
    for start in range(0, len(matches_to_upsert), 100):
        batch = matches_to_upsert[start:start + 100]
        rest_post(
            cfg,
            "client_tender_matches?on_conflict=profile_id,tender_id",
            batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        synced += len(batch)
        print("AUTO MATCH SAMRUK:", synced, "/", len(matches_to_upsert))

    return synced


def main():
    print("=" * 72)
    print("TENDER RADAR KZ COMMERCIAL — SAMRUK -> SUPABASE TEST SYNC")
    print("GOSZAKUP UNCHANGED • TELEGRAM NOT STARTED")
    print("SCHEMA FIX: commercial.tenders = 24 columns, no status_code")
    print("FILTER FIX: flexible Russian exclude wordforms enabled")
    print("=" * 72)

    cfg = get_config()
    profiles, keywords = samruk_profiles_and_keywords(cfg)

    print("SAMRUK ACTIVE PROFILES:", len(profiles))
    print("SAMRUK KEYWORDS:", len(keywords))

    if not profiles:
        print("STOP: нет активных Samruk-профилей.")
        return 0

    if not keywords:
        print("STOP: нет ключевых слов Samruk.")
        return 0

    run_collector(keywords)

    source_rows = load_json(OUT / "samruk_tenders.json")
    merged = merge_rows(source_rows)
    rows = clean_for_supabase(merged)

    print("COLLECTED RAW ROWS:", len(source_rows))
    print("UNIQUE SAMRUK LOTS:", len(rows))

    if not rows:
        print("STOP: fresh Samruk set is empty.")
        return 0

    sent = upload_tenders(cfg, rows)
    matches = auto_match_profiles(cfg, profiles)

    print("=" * 72)
    print("DONE")
    print("SAMRUK TENDERS SYNCED:", sent)
    print("SAMRUK MATCHES UPSERTED:", matches)
    print("TELEGRAM: NOT RUN")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
