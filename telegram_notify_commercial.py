# -*- coding: utf-8 -*-
"""New commercial Telegram digest. Dry run by default; explicit new database and bot.
Up to five unique active unsent tenders per destination; marks only displayed items.
Licence, opt-out and current profile filters are checked before sending.
Run serially: external delivery and database marking are not atomic.
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

MAX_ITEMS = 5
TARGET = "https://aypqwhhplogolzczubwi.supabase.co"


def env(name, default=""):
    return os.getenv(name, default).strip()


def parse_dt(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def headers(cfg, write=False):
    key = cfg["SUPABASE_SERVICE_ROLE_KEY"]
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept-Profile": "commercial",
    }
    if write:
        h["Content-Type"] = "application/json"
        h["Content-Profile"] = "commercial"
    return h


def rest_get(cfg, path):
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    req = urllib.request.Request(url, headers=headers(cfg), method="GET")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def rest_post(cfg, path, payload, prefer="return=minimal"):
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    h = headers(cfg, write=True)
    h["Prefer"] = prefer
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=h,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


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


def short(text, n=160):
    s = str(text or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def money_text(amount, currency):
    if amount in (None, ""):
        return "—"
    try:
        v = float(amount)
        txt = (
            f"{int(v):,}".replace(",", " ")
            if v.is_integer()
            else f"{v:,.2f}".replace(",", " ")
        )
    except Exception:
        txt = str(amount)
    return f"{txt} {currency or 'KZT'}"


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        result = json.loads(r.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(str(result))
    return str(result.get("result", {}).get("message_id", ""))


def deadline_text(value):
    if not value:
        return "—"
    try:
        dt = parse_dt(value)
    except (TypeError, ValueError, OverflowError):
        return "Дата не определена"
    return dt.astimezone(timezone(timedelta(hours=5))).strftime("%d.%m.%Y, %H:%M") + " (Казахстан, UTC+5)"


def build_digest(destination, matches, tenders):
    ordered = sorted(
        matches,
        key=lambda m: parse_dt(m.get("matched_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    lines = [
        "🔔 Tender Radar KZ Commercial",
        "",
        destination.get("label") or "Новые тендеры",
        f"Найдено новых тендеров: {len(ordered)}",
        "",
    ]

    for i, m in enumerate(ordered[:MAX_ITEMS], 1):
        t = tenders.get(int(m["tender_id"]), {})
        matched = ", ".join(normalize_list(m.get("matched_keyword"))) or "—"

        lines += [
            f"{i}. {short(t.get('title') or 'Тендер без названия')}",
            f"   Сумма: {money_text(t.get('amount'), t.get('currency'))}",
            f"   Срок: {deadline_text(t.get('expires_at'))}",
            f"   Совпадение: {short(matched, 80)}",
        ]
        if t.get("public_url"):
            lines.append(f"   {t['public_url']}")
        lines.append("")

    rest = len(ordered) - min(len(ordered), MAX_ITEMS)
    if rest > 0:
        lines += [
            f"Ещё {rest} новых тендеров — в личном кабинете Tender Radar.",
            "",
        ]

    lines.append("Сообщение сформировано автоматически.")
    return "\n".join(lines)


def mark_all_sent(cfg, destination, matches, message_id):
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for m in matches:
        rows.append(
            {
                "client_id": m["client_id"],
                "profile_id": m["profile_id"],
                "tender_id": m["tender_id"],
                "destination_id": destination["id"],
                "channel": "telegram",
                "status": "sent",
                "provider_message_id": message_id,
                "error_text": None,
                "sent_at": now,
            }
        )

    if rows:
        rest_post(
            cfg,
            "notifications_sent?on_conflict=destination_id,tender_id,channel",
            rows,
            "resolution=merge-duplicates,return=minimal",
        )


def paid(client, now):
    expiry = parse_dt(client.get("expires_at"))
    return (client.get("status") == "active" and client.get("payment_status") == "active"
            and client.get("payment_provider") == "gumroad" and bool(client.get("license_key_hash"))
            and bool(client.get("license_verified_at")) and expiry is not None and expiry > now
            and not client.get("telegram_opt_out") and int(client.get("telegram_limit") or 0) > 0)


def eligible_tender(tender, profile, now, urgent=False):
    expiry = parse_dt(tender.get("expires_at"))
    if not tender.get("is_active") or not expiry or expiry <= now or not profile.get("active"):
        return False
    if urgent and (expiry-now).total_seconds() > int(profile.get("urgent_hours") or 48)*3600:
        return False
    if tender.get("source_code") not in normalize_list(profile.get("sources")):
        return False
    text = " ".join(str(tender.get(k) or "") for k in ("title", "description", "customer_name")).casefold()
    included = normalize_list(profile.get("include_keywords"))
    if not included or not any(k.casefold() in text for k in included):
        return False
    if any(k.casefold() in text for k in normalize_list(profile.get("exclude_keywords"))):
        return False
    regions = normalize_list(profile.get("regions"))
    if regions and str(tender.get("region") or "").casefold() not in {r.casefold() for r in regions}:
        return False
    amount = tender.get("amount")
    for key, lower in (("min_amount", True), ("max_amount", False)):
        bound = profile.get(key)
        if bound is not None and (amount is None or (float(amount) < float(bound) if lower else float(amount) > float(bound))):
            return False
    return True


def rest_all(cfg, path):
    rows = []
    separator = "&" if "?" in path else "?"
    for offset in range(0, 100000, 500):
        page = rest_get(cfg, path + separator + f"limit=500&offset={offset}")
        rows.extend(page)
        if len(page) < 500:
            return rows
    raise RuntimeError("Pagination safety limit reached; nothing sent")


def main():
    cfg = {"SUPABASE_URL": env("TRKZ_TEST_SUPABASE_URL"),
           "SUPABASE_SERVICE_ROLE_KEY": env("TRKZ_TEST_SUPABASE_SERVICE_ROLE_KEY"),
           "TELEGRAM_BOT_TOKEN": env("TRKZ_TEST_TELEGRAM_BOT_TOKEN")}
    if cfg["SUPABASE_URL"] != TARGET or not cfg["SUPABASE_SERVICE_ROLE_KEY"]:
        raise RuntimeError("New commercial database configuration required")
    apply = env("TRKZ_TELEGRAM_APPLY") == "true"
    if apply:
        if not cfg["TELEGRAM_BOT_TOKEN"]:
            raise RuntimeError("New bot token required")
        req = urllib.request.Request("https://api.telegram.org/bot" + cfg["TELEGRAM_BOT_TOKEN"] + "/getMe")
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                bot = json.load(response)
        except Exception:
            raise RuntimeError("Bot identity check failed") from None
        if not bot.get("ok") or bot.get("result", {}).get("username") != "mnsystems_tender_radar_kz_bot":
            raise RuntimeError("Unexpected Telegram bot; nothing sent")
    now = datetime.now(timezone.utc)
    clients = {int(c["id"]): c for c in rest_all(cfg, "clients?select=*&order=id.asc") if paid(c, now)}
    profiles = {(int(p["client_id"]), int(p["id"])): p for p in rest_all(cfg, "profiles?select=*&active=eq.true&order=id.asc")}
    destinations = rest_all(cfg, "telegram_destinations?select=*&active=eq.true&order=id.asc")
    target = env("TELEGRAM_CLIENT_ID")
    if target and not target.isdigit():
        raise RuntimeError("Client ID must be numeric")
    destinations = [d for d in destinations if int(d["client_id"]) in clients and (not target or int(d["client_id"]) == int(target))]
    matches = rest_all(cfg, "client_tender_matches?select=*&order=matched_at.desc,id.desc")
    sent = rest_all(cfg, "notifications_sent?select=destination_id,tender_id&channel=eq.telegram&status=eq.sent&order=id.asc")
    already = {(int(r["destination_id"]), int(r["tender_id"])) for r in sent}
    ids = sorted({int(m["tender_id"]) for m in matches if int(m["client_id"]) in clients})
    tenders = {}
    for start in range(0, len(ids), 100):
        chunk = ",".join(str(i) for i in ids[start:start+100])
        for t in rest_get(cfg, "tenders?select=*&id=in.(" + chunk + ")"):
            tenders[int(t["id"])] = t
    digests = marked = errors = candidates = 0
    for d in destinations:
        chosen = {}
        for m in matches:
            cid, tid, did = int(m["client_id"]), int(m["tender_id"]), int(d["id"])
            profile = profiles.get((cid, int(m["profile_id"])))
            t = tenders.get(tid)
            if cid != int(d["client_id"]) or (did, tid) in already or not profile or not t or m.get("status") in ("not_fit", "rejected"):
                continue
            if eligible_tender(t, profile, now, d.get("only_urgent", False)):
                chosen.setdefault(tid, m)
            if len(chosen) == MAX_ITEMS:
                break
        batch = list(chosen.values())
        if not batch:
            continue
        candidates += len(batch)
        if not apply:
            print(f"DRY RUN client={d['client_id']} eligible_tenders={len(batch)}")
            continue
        try:
            # Recheck licence immediately before the external send.
            current = rest_get(cfg, "clients?select=*&id=eq." + str(d["client_id"]))
            if not current or not paid(current[0], datetime.now(timezone.utc)):
                continue
            message_id = send_telegram(cfg["TELEGRAM_BOT_TOKEN"], d["chat_id"], build_digest(d, batch, tenders))
            mark_all_sent(cfg, d, batch, message_id)
            digests += 1
            marked += len(batch)
        except Exception as error:
            errors += 1
            print(f"DIGEST ERROR client={d['client_id']} type={type(error).__name__}")
    print(json.dumps({"mode": "apply" if apply else "dry_run", "candidate_tenders": candidates,
                      "digests_sent": digests, "tenders_marked_sent": marked, "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
