"""Read-only bounded Samruk audit; no database writes or notifications."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import tempfile
import collect_commercial_test as pilot

def main():
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
            zero = re.search(r"Найдено\\s*:?\\s*0(?!\\d)", normalized, re.IGNORECASE)
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
    with tempfile.TemporaryDirectory(prefix="trkz-samruk-audit-") as directory:
        collector.OUT = Path(directory)
        driver = collector.make_driver()
        try:
            rows = collector.enrich_rows(driver, collector.collect(driver))
        finally:
            driver.quit()
    now = datetime.now(timezone.utc)
    candidates = 0
    for row in rows:
        try:
            end = datetime.fromisoformat(str(row.get("expires_at")).replace("Z", "+00:00"))
            future = end.tzinfo is not None and end > now
        except (ValueError, TypeError):
            future = False
        if not future or not row.get("is_active"):
            continue
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
    print(json.dumps({
        "mode": "dry-run", "source": "samruk", "partial_scan": True,
        "profiles": len(profiles), "keywords": len(keywords), "collected": len(rows),
        "candidate_matches": candidates,
        "details_ok": sum(bool((r.get("raw") or {}).get("detail_checked")) for r in rows),
        "database_writes": 0, "notifications": 0,
        "deadline_note": "Unenriched deadlines are estimates; import not approved."
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
