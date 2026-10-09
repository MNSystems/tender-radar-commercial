# -*- coding: utf-8 -*-
"""
Tender Radar KZ Commercial — Goszakup sync + automatic profile matching
PROTOCOL 13B — AUTO MATCH REFRESH

Flow:
Goszakup -> commercial.tenders -> commercial.client_tender_matches

Secrets / env:
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
GOSZAKUP_TOKEN
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

KZ_TZ = timezone(timedelta(hours=5))


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_config():
    cfg = {
        "SUPABASE_URL": env("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": env("SUPABASE_SERVICE_ROLE_KEY"),
        "GOSZAKUP_TOKEN": env("GOSZAKUP_TOKEN"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise RuntimeError("Missing configuration: " + ", ".join(missing))
    return cfg


def headers(cfg, *, write=False):
    h = {
        "apikey": cfg["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": "Bearer " + cfg["SUPABASE_SERVICE_ROLE_KEY"],
        "Accept-Profile": "commercial",
    }
    if write:
        h.update({
            "Content-Type": "application/json",
            "Content-Profile": "commercial",
        })
    return h


def rest_get(cfg, path):
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, headers=headers(cfg), method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rest_post(cfg, path, payload, prefer="return=minimal"):
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers(cfg, write=True), "Prefer": prefer},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def nempty(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


def normalize_goszakup_datetime(v):
    s = nempty(v)
    if not s:
        return None
    raw = str(s).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KZ_TZ)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def goszakup_is_active(status, expires_at):
    s = str(status or "").lower()
    if "прием" in s or "приём" in s:
        return True
    if expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return exp > datetime.now(exp.tzinfo)
        except Exception:
            pass
    return False


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
        "profiles?select=id,client_id,name,include_keywords,exclude_keywords,sources,active&active=eq.true"
    )


def load_commercial_keywords(cfg):
    found = []
    seen = set()

    for row in load_profiles(cfg):
        sources = normalize_list(row.get("sources"))
        if "goszakup" not in sources:
            continue

        for word in normalize_list(row.get("include_keywords")):
            key = word.lower()
            if key not in seen:
                seen.add(key)
                found.append(word)

    if not found:
        raise RuntimeError(
            "Нет активных ключевых слов для профилей, где выбран источник goszakup."
        )
    return found


def run_collector(cfg, keywords):
    collector = ROOT / "collector_goszakup.py"
    if not collector.exists():
        raise RuntimeError("Не найден collector_goszakup.py")

    child_env = os.environ.copy()
    child_env["GOSZAKUP_TOKEN"] = cfg["GOSZAKUP_TOKEN"]
    child_env["GOSZAKUP_KEYWORDS"] = ",".join(keywords)

    print("COMMERCIAL KEYWORDS:", ", ".join(keywords))
    proc = subprocess.run(
        [sys.executable, str(collector)],
        cwd=str(ROOT),
        env=child_env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"collector_goszakup.py завершился с кодом {proc.returncode}"
        )


def make_goszakup():
    rows = load_json(OUT / "tenders.json")
    out = []

    for r in rows:
        if not isinstance(r, dict):
            continue

        ext = str(r.get("external_id") or "").strip()
        lotnum = str(r.get("lot_number") or "").strip()
        ann = str(r.get("announcement_number") or "").strip()
        sid = ext or lotnum or ann
        if not sid:
            continue

        status = str(r.get("status") or "")
        published_at = normalize_goszakup_datetime(r.get("publish_date"))
        started_at = normalize_goszakup_datetime(r.get("start_date"))
        expires_at = normalize_goszakup_datetime(r.get("end_date"))
        is_active = goszakup_is_active(status, expires_at)

        out.append({
            "source_code": "goszakup",
            "source_tender_id": ann or None,
            "source_lot_id": sid,
            "public_url": nempty(r.get("public_url")),
            "title": nempty(r.get("title")),
            "description": nempty(r.get("description")),
            "customer_name": nempty(r.get("customer_name")),
            "customer_bin": nempty(r.get("customer_bin")),
            "region": nempty(r.get("region")),
            "procurement_method": nempty(r.get("trade_method")),
            "status_name": nempty(status),
            "amount": r.get("amount_kzt"),
            "currency": "KZT",
            "quantity": r.get("quantity"),
            "unit": nempty(r.get("unit")),
            "category": nempty(r.get("category")),
            "published_at": published_at,
            "started_at": started_at,
            "expires_at": expires_at,
            "is_active": is_active,
            "raw": r,
        })

    return out


def deactivate_existing_goszakup(cfg):
    endpoint = (
        cfg["SUPABASE_URL"].rstrip("/")
        + "/rest/v1/tenders?source_code=eq.goszakup&is_active=eq.true"
    )
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({"is_active": False}).encode("utf-8"),
        headers={**headers(cfg, write=True), "Prefer": "return=minimal"},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp.read()


def upload_rows(cfg, rows):
    if not rows:
        print("WARNING: Goszakup returned 0 rows. Existing rows unchanged.")
        return 0

    endpoint = (
        cfg["SUPABASE_URL"].rstrip("/")
        + "/rest/v1/tenders?on_conflict=source_code,source_lot_id"
    )
    h = {
        **headers(cfg, write=True),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    sent = 0
    for start in range(0, len(rows), 100):
        batch = rows[start:start + 100]
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(batch, ensure_ascii=False).encode("utf-8"),
            headers=h,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        sent += len(batch)
        print("SYNC goszakup:", sent, "/", len(rows))
    return sent


def tender_text(t):
    return " ".join([
        str(t.get("title") or ""),
        str(t.get("description") or ""),
        str(t.get("category") or ""),
    ]).lower()


def auto_match_profiles(cfg):
    print("AUTO MATCH: start")

    profiles = load_profiles(cfg)
    tenders = rest_get(
        cfg,
        "tenders?select=id,source_code,title,description,category,is_active"
        "&source_code=eq.goszakup&is_active=eq.true"
    )
    matches_to_upsert = []

    for p in profiles:
        if "goszakup" not in normalize_list(p.get("sources")):
            continue

        include_words = [x.lower() for x in normalize_list(p.get("include_keywords"))]
        exclude_words = [x.lower() for x in normalize_list(p.get("exclude_keywords"))]

        if not include_words:
            continue

        for t in tenders:
            text = tender_text(t)

            matched = [w for w in include_words if w and w in text]
            excluded = [w for w in exclude_words if w and w in text]

            if not matched or excluded:
                continue

            matches_to_upsert.append({
                "client_id": p["client_id"],
                "profile_id": p["id"],
                "tender_id": t["id"],
                "relevance_score": 100,
                "matched_keyword": matched,
                "match_reason": {
                    "source": "goszakup",
                    "include": matched,
                    "exclude": [],
                    "rule": "automatic keyword match",
                },
                # 14D SAFE:
                # Не передаём status при UPSERT.
                # Для НОВОЙ записи PostgreSQL возьмёт DEFAULT 'new'.
                # Для УЖЕ существующей записи пользовательский статус
                # (viewed / interested / in_work / rejected) сохранится.
                # is_favorite также не передаётся и поэтому не перезаписывается.
            })

    if not matches_to_upsert:
        print("AUTO MATCH: no qualifying matches")
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
        print("AUTO MATCH:", synced, "/", len(matches_to_upsert))

    return synced


def main():
    print("=" * 72)
    print("TENDER RADAR KZ COMMERCIAL — GOSZAKUP + AUTO MATCH")
    print("=" * 72)

    cfg = get_config()
    keywords = load_commercial_keywords(cfg)

    run_collector(cfg, keywords)
    rows = make_goszakup()

    print("Prepared rows:", len(rows))
    if not rows:
        print("STOP: fresh set is empty.")
        return 0

    deactivate_existing_goszakup(cfg)
    sent = upload_rows(cfg, rows)

    matches = auto_match_profiles(cfg)

    print("DONE. Synced:", sent)
    print("DONE. Matches refreshed:", matches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
