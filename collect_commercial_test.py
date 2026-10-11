"""Bounded Goszakup pilot. Dry run by default; never sends notifications."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlencode

import collector_goszakup as collector
import auto_collect_and_sync_commercial as mapper

TARGET = "https://aypqwhhplogolzczubwi.supabase.co"


def config():
    url = os.environ.get("TRKZ_TEST_SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("TRKZ_TEST_SUPABASE_SERVICE_ROLE_KEY", "")
    if url != TARGET or not key:
        raise ValueError("Only the new commercial test project is allowed; test key required")
    return {"SUPABASE_URL": url, "SUPABASE_SERVICE_ROLE_KEY": key}


def all_rows(cfg, table, filters):
    rows, cursor = [], 0
    while True:
        query = dict(filters, order="id.asc", **{"id": "gt." + str(cursor), "limit": 500})
        page = mapper.rest_get(cfg, table + "?" + urlencode(query))
        if not page:
            return rows
        if page[-1]["id"] <= cursor:
            raise ValueError("Non-advancing database cursor")
        rows.extend(page)
        cursor = page[-1]["id"]


def profiles(cfg):
    clients = all_rows(cfg, "clients", {
        "select": "id", "status": "eq.active", "payment_status": "eq.active",
        "payment_provider": "eq.gumroad", "license_key_hash": "not.is.null",
        "license_verified_at": "not.is.null",
        "expires_at": "gt." + datetime.now(timezone.utc).isoformat(),
    })
    allowed = {c["id"] for c in clients}
    return [p for p in all_rows(cfg, "profiles", {"select": "*", "active": "eq.true"})
            if p["client_id"] in allowed and "goszakup" in mapper.normalize_list(p.get("sources"))]


def eligible(tender, now):
    # A future date alone must not revive a cancelled/completed lot.
    status = str(tender.get("status_name") or "").lower()
    if not ("прием" in status or "приём" in status):
        return False
    try:
        end = datetime.fromisoformat(str(tender["expires_at"]).replace("Z", "+00:00"))
        return end.tzinfo is not None and end > now
    except (ValueError, TypeError, KeyError):
        return False


def match(profile, tender):
    text = mapper.tender_text(tender)
    words = [w for w in mapper.normalize_list(profile.get("include_keywords")) if w.lower() in text]
    if not words or any(w.lower() in text for w in mapper.normalize_list(profile.get("exclude_keywords"))):
        return None
    regions = mapper.normalize_list(profile.get("regions"))
    if regions and str(tender.get("region") or "").casefold() not in {r.casefold() for r in regions}:
        return None
    amount = tender.get("amount")
    for field, minimum in (("min_amount", True), ("max_amount", False)):
        bound = profile.get(field)
        if bound is not None and (amount is None or (float(amount) < float(bound) if minimum else float(amount) > float(bound))):
            return None
    return {"client_id": profile["client_id"], "profile_id": profile["id"],
            "tender_id": tender["id"], "matched_keyword": words, "relevance_score": 100,
            "match_reason": {"source": "goszakup", "include": words, "rule": "bounded pilot"}}


def upsert(cfg, table, conflict, rows):
    for start in range(0, len(rows), 100):
        mapper.rest_post(cfg, table + "?on_conflict=" + conflict, rows[start:start+100],
                         prefer="resolution=merge-duplicates,return=minimal")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("limit must be between 1 and 200")
    cfg = config()
    token = os.environ.get("TRKZ_TEST_GOSZAKUP_TOKEN", "")
    if not token:
        raise ValueError("TRKZ_TEST_GOSZAKUP_TOKEN required")
    active_profiles = profiles(cfg)
    keywords = sorted({w for p in active_profiles for w in mapper.normalize_list(p.get("include_keywords"))})
    collected = []
    # Strict: any source failure stops the run before database writes.
    for keyword in keywords:
        collected.extend(collector.collect_keyword(token, keyword, args.limit))
    with tempfile.TemporaryDirectory(prefix="trkz-test-") as directory:
        collector.OUTPUT_DIR = mapper.OUT = Path(directory)
        collector.save_json(collector.deduplicate(collected))
        rows = mapper.make_goszakup()
    now = datetime.now(timezone.utc)
    for row in rows:
        row["is_active"] = eligible(row, now)
    summary = {"mode": "apply" if args.apply else "dry-run", "source": "goszakup",
               "partial_scan": True, "profiles": len(active_profiles), "keywords": len(keywords),
               "collected": len(rows), "active": sum(r["is_active"] for r in rows)}
    if args.apply and rows:
        upsert(cfg, "tenders", "source_code,source_lot_id", rows)
        # Re-read access and filters immediately before matching.
        active_profiles = profiles(cfg)
        fetched = {r["source_lot_id"] for r in rows}
        tenders = all_rows(cfg, "tenders", {"select": "*", "source_code": "eq.goszakup", "is_active": "eq.true"})
        matches = [m for t in tenders if t["source_lot_id"] in fetched and eligible(t, datetime.now(timezone.utc))
                   for p in active_profiles if (m := match(p, t))]
        upsert(cfg, "client_tender_matches", "profile_id,tender_id", matches)
        summary["matches_upserted"] = len(matches)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
