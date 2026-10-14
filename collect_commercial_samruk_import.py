"""Bounded manual Samruk import into the isolated commercial project; no notifications."""
import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import tempfile
import collect_commercial_test as pilot

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--profile-id', type=int, default=None, help='Limit matching and keywords to this eligible profile')
    args = parser.parse_args()
    cfg = pilot.config()
    clients = pilot.all_rows(cfg, "clients", {
        "select": "id", "status": "eq.active", "payment_status": "eq.active",
        "payment_provider": "eq.gumroad", "license_key_hash": "not.is.null",
        "license_verified_at": "not.is.null",
        "expires_at": "gt." + datetime.now(timezone.utc).isoformat()})
    allowed = {c["id"] for c in clients}
    profiles = [p for p in pilot.all_rows(cfg, "profiles", {"select": "*", "active": "eq.true"})
                if p["client_id"] in allowed
                and "samruk" in pilot.mapper.normalize_list(p.get("sources"))]
    if args.profile_id is not None:
        profiles = [p for p in profiles if p['id'] == args.profile_id]
        if not profiles:
            raise ValueError('Profile not found or not eligible for paid Samruk search')
    keywords = sorted({w for p in profiles for w in pilot.mapper.normalize_list(p.get("include_keywords"))})
    if not keywords:
        print(json.dumps({"mode": "dry-run", "source": "samruk", "collected": 0}))
        return
    import samruk_collector_commercial_TEST_V2 as collector
    collector.KEYWORDS = keywords
    collector.MAX_PAGES_PER_KEYWORD = 1
    collector.DETAIL_LIMIT = 0  # Enrich all active rows in the bounded first-page sample.
    original_wait = collector.wait_for_page_snapshot
    def strict_wait(driver, previous_signature=None, timeout=collector.WAIT_SECONDS):
        items = original_wait(driver, previous_signature, timeout)
        if items:
            return items
        def page_state():
            body = driver.find_element(collector.By.TAG_NAME, "body").text or ""
            normalized = " ".join(body.split())
            zero = re.search(r"Найдено\s*:?\s*0(?!\d)", normalized, re.IGNORECASE)
            empty_message = "по вашему запросу ничего не найдено" in normalized.casefold()
            return normalized, bool(zero) or empty_message
        body, zero = page_state()
        if zero:
            return []
        # One bounded retry for a slowly rendered SPA; ambiguity remains an error.
        items = original_wait(driver, previous_signature, timeout)
        if items:
            return items
        body, zero = page_state()
        if zero:
            return []
        print("SAMRUK_PAGE_DIAGNOSTIC " + json.dumps({
            "url": driver.current_url, "title": driver.title,
            "body_excerpt": body[:4000]
        }, ensure_ascii=False), flush=True)
        raise RuntimeError("Samruk returned neither cards nor an explicit zero result after retry")
    collector.wait_for_page_snapshot = strict_wait
    # Capture the freshly loaded detail body and use acceptance dates only.
    original_detail_wait = collector.wait_for_detail_text
    detail_bodies = {}
    def checked_detail_wait(driver, lot_id, timeout=collector.WAIT_SECONDS):
        body = original_detail_wait(driver, lot_id, timeout)
        detail_bodies[str(lot_id)] = body
        return body
    collector.wait_for_detail_text = checked_detail_wait
    original_enrich = collector.enrich_from_open_detail
    def verified_enrich(driver, row):
        result = original_enrich(driver, row)
        body = detail_bodies.pop(str(row["source_lot_id"]), "")
        start = collector.date_for_labels(body, ["НАЧАЛО ПРИЕМА ЗАЯВОК", "НАЧАЛО ПРИЁМА ЗАЯВОК"])
        end = collector.date_for_labels(body, ["КОНЕЦ ПРИЕМА ЗАЯВОК", "КОНЕЦ ПРИЁМА ЗАЯВОК"])
        result["started_at"] = start
        result["expires_at"] = end
        result["raw"]["acceptance_deadline_checked"] = bool(end)
        return result
    collector.enrich_from_open_detail = verified_enrich
    with tempfile.TemporaryDirectory(prefix="trkz-samruk-audit-") as directory:
        collector.OUT = Path(directory)
        driver = collector.make_driver()
        try:
            rows = collector.enrich_rows(driver, collector.collect(driver))
        finally:
            driver.quit()
    now = datetime.now(timezone.utc)
    verified_rows = []
    candidates = 0
    for row in rows:
        try:
            end = datetime.fromisoformat(str(row.get("expires_at")).replace("Z", "+00:00"))
            future = end.tzinfo is not None and end > now
        except (ValueError, TypeError):
            future = False
        raw = row.get("raw") or {}
        if raw.get("detail_error"):
            raise RuntimeError("Detail failed for lot " + str(row["source_lot_id"]))
        if not future or not row.get("is_active") or not raw.get("detail_checked") or not raw.get("acceptance_deadline_checked"):
            continue
        if str(row.get("status_name") or "").strip().casefold() != "опубликовано":
            continue
        row["category"] = None
        verified_rows.append(row)
        # Search provenance is not proof of matching.
        probe = dict(row, id=row["source_lot_id"], category=None)
        for profile in profiles:
            result = pilot.match(profile, probe)
            if result:
                candidates += 1
                print("SAMRUK_PREVIEW " + json.dumps({
                    "profile_id": profile["id"], "lot_id": row["source_lot_id"],
                    "title": row["title"], "amount": row.get("amount"),
                    "customer": row.get("customer_name"), "expires_at": row.get("expires_at"),
                    "status": row.get("status_name"),
                    "detail_checked": bool((row.get("raw") or {}).get("detail_checked")),
                    "description": row.get("description"),
                    "detail_error": (row.get("raw") or {}).get("detail_error"),
                    "matched_keywords": result["matched_keyword"], "url": row["public_url"]
                }, ensure_ascii=False))
    matches_upserted = 0
    if args.apply and verified_rows:
        fields = ("source_code source_tender_id source_lot_id public_url title description "
                  "customer_name customer_bin region procurement_method status_name amount "
                  "currency quantity unit category published_at started_at expires_at is_active raw").split()
        payload = [{key: row.get(key) for key in fields} for row in verified_rows]
        for row in payload:
            if row["source_code"] != "samruk":
                raise RuntimeError("Unexpected source")
        pilot.upsert(cfg, "tenders", "source_code,source_lot_id", payload)
        ids = {str(row["source_lot_id"]) for row in verified_rows}
        stored = pilot.all_rows(cfg, "tenders", {"select": "*", "source_code": "eq.samruk"})
        # Recheck active paid clients and current profiles after collection.
        clients = pilot.all_rows(cfg, "clients", {
            "select": "id", "status": "eq.active", "payment_status": "eq.active",
            "payment_provider": "eq.gumroad", "license_key_hash": "not.is.null",
            "license_verified_at": "not.is.null",
            "expires_at": "gt." + datetime.now(timezone.utc).isoformat()})
        allowed = {client["id"] for client in clients}
        current_profiles = [profile for profile in pilot.all_rows(cfg, "profiles", {"select": "*", "active": "eq.true"})
                            if profile["client_id"] in allowed
                            and "samruk" in pilot.mapper.normalize_list(profile.get("sources"))]
        if args.profile_id is not None:
            current_profiles = [p for p in current_profiles if p['id'] == args.profile_id]
        matches = []
        for tender in stored:
            if str(tender["source_lot_id"]) not in ids:
                continue
            end = datetime.fromisoformat(str(tender["expires_at"]).replace("Z", "+00:00"))
            if end <= datetime.now(timezone.utc):
                continue
            for profile in current_profiles:
                result = pilot.match(profile, tender)
                if result:
                    result["match_reason"] = {"source": "samruk", "include": result["matched_keyword"],
                                              "rule": "verified bounded manual import"}
                    matches.append(result)
        # Omit status and is_favorite to preserve the client's work.
        pilot.upsert(cfg, "client_tender_matches", "profile_id,tender_id", matches)
        matches_upserted = len(matches)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run", "source": "samruk", "partial_scan": True,
        "profiles": len(profiles), "keywords": len(keywords), "collected": len(rows),
        "candidate_matches": candidates,
        "details_ok": sum(bool((r.get("raw") or {}).get("detail_checked")) for r in rows),
        "verified_tenders": len(verified_rows), "matches_upserted": matches_upserted,
        "notifications": 0,
        "deadline_note": "Only detailed lots with future acceptance deadlines are eligible."
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
