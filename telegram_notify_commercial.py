# -*- coding: utf-8 -*-
"""
Tender Radar KZ Commercial — Telegram DIGEST

Правила:
1) В обычном режиме берём совпадения текущего запуска
   (matched_at >= RUN_STARTED_AT).
2) Работаем только с active=true в commercial.telegram_destinations.
3) На каждого активного клиента отправляем одно сообщение-дайджест.
4) В сообщении показываем максимум 5 новых тендеров.
5) Если новых больше — пишем, сколько ещё доступно в кабинете.
6) После успешной отправки помечаем отправленные тендеры как sent.
7) Если в текущем запуске новых совпадений нет, допускается догоняющая
   отправка последних неотправленных совпадений.
8) Для безопасного ручного теста можно задать TELEGRAM_CLIENT_ID.
   Тогда обрабатывается только указанный client_id.
   Если TELEGRAM_CLIENT_ID не задан, рабочий режим остаётся обычным:
   обрабатываются все активные Telegram-направления.
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

MAX_ITEMS = 5


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
            f"   Срок: {t.get('expires_at') or '—'}",
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


def main():
    print("TENDER RADAR KZ COMMERCIAL — TELEGRAM DIGEST")

    cfg = {
        "SUPABASE_URL": env("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": env("SUPABASE_SERVICE_ROLE_KEY"),
        "TELEGRAM_BOT_TOKEN": env("TELEGRAM_BOT_TOKEN"),
        "RUN_STARTED_AT": env("RUN_STARTED_AT"),
        "TELEGRAM_CLIENT_ID": env("TELEGRAM_CLIENT_ID"),
    }

    if not cfg["TELEGRAM_BOT_TOKEN"]:
        print("TELEGRAM: token missing; nothing sent.")
        return 0

    if not cfg["RUN_STARTED_AT"]:
        print("SAFE STOP: RUN_STARTED_AT missing; nothing sent.")
        return 0

    run_started = parse_dt(cfg["RUN_STARTED_AT"])
    print("RUN_STARTED_AT:", run_started.isoformat())

    destinations = rest_get(
        cfg,
        "telegram_destinations"
        "?select=id,client_id,chat_id,label,active,only_urgent"
        "&active=eq.true",
    )

    if not destinations:
        print("No active Telegram destinations.")
        return 0

    # Безопасный ручной режим: только один клиент.
    target_client_id = cfg["TELEGRAM_CLIENT_ID"]
    if target_client_id:
        try:
            target_client_id_int = int(target_client_id)
        except ValueError:
            print(
                f"SAFE STOP: TELEGRAM_CLIENT_ID must be integer; "
                f"got {target_client_id!r}."
            )
            return 0

        destinations = [
            d
            for d in destinations
            if int(d["client_id"]) == target_client_id_int
        ]
        print(
            f"TELEGRAM TEST MODE: only client_id={target_client_id_int}; "
            f"destinations={len(destinations)}"
        )

        if not destinations:
            print(
                f"SAFE STOP: no active Telegram destination for "
                f"client_id={target_client_id_int}."
            )
            return 0
    else:
        print("TELEGRAM NORMAL MODE: all active destinations.")

    all_matches = rest_get(
        cfg,
        "client_tender_matches"
        "?select=client_id,profile_id,tender_id,matched_keyword,matched_at"
        "&order=matched_at.desc"
        "&limit=3000",
    )

    current = []
    for m in all_matches:
        dt = parse_dt(m.get("matched_at"))
        if dt and dt >= run_started:
            current.append(m)

    print("NEW MATCHES THIS RUN:", len(current))
    if not current:
        print("No current-run matches; checking first-time Telegram destinations.")

    existing = rest_get(
        cfg,
        "notifications_sent"
        "?select=destination_id,tender_id,status,channel,sent_at"
        "&channel=eq.telegram",
    )

    already = {
        (int(r["destination_id"]), int(r["tender_id"]))
        for r in existing
        if r.get("status") == "sent"
    }

    last_sent_by_destination = {}
    for r in existing:
        if r.get("status") != "sent" or not r.get("sent_at"):
            continue
        did = int(r["destination_id"])
        dt = parse_dt(r.get("sent_at"))
        if not dt:
            continue
        prev = last_sent_by_destination.get(did)
        if prev is None or dt > prev:
            last_sent_by_destination[did] = dt

    catchup_matches = {}

    for d in destinations:
        if d.get("only_urgent"):
            continue

        did = int(d["id"])
        cid = int(d["client_id"])

        current_unsent = [
            m
            for m in current
            if int(m["client_id"]) == cid
            and (did, int(m["tender_id"])) not in already
        ]

        if current_unsent:
            continue

        last_sent = last_sent_by_destination.get(did)
        fallback = []

        for m in all_matches:
            if int(m["client_id"]) != cid:
                continue
            if (did, int(m["tender_id"])) in already:
                continue

            matched_dt = parse_dt(m.get("matched_at"))
            if last_sent is not None:
                if not matched_dt or matched_dt <= last_sent:
                    continue

            fallback.append(m)
            if len(fallback) >= MAX_ITEMS:
                break

        if fallback:
            catchup_matches[did] = fallback
            if last_sent is None:
                print(
                    f"CLIENT {cid}: first Telegram digest will use "
                    f"{len(fallback)} latest unsent matches."
                )
            else:
                print(
                    f"CLIENT {cid}: catch-up digest will use "
                    f"{len(fallback)} unsent matches after "
                    f"{last_sent.isoformat()}."
                )

    candidate_matches = list(current)
    for rows in catchup_matches.values():
        candidate_matches.extend(rows)

    ids = sorted({int(m["tender_id"]) for m in candidate_matches})
    tenders = {}

    for start in range(0, len(ids), 100):
        chunk = ",".join(str(x) for x in ids[start : start + 100])
        rows = rest_get(
            cfg,
            "tenders"
            "?select=id,title,amount,currency,expires_at,public_url"
            f"&id=in.({chunk})",
        )
        for t in rows:
            tenders[int(t["id"])] = t

    digests_sent = 0
    tenders_marked = 0
    errors = 0

    for d in destinations:
        if d.get("only_urgent"):
            continue

        did = int(d["id"])
        cid = int(d["client_id"])

        client_matches = []
        for m in current:
            if int(m["client_id"]) != cid:
                continue
            if (did, int(m["tender_id"])) in already:
                continue
            client_matches.append(m)

        if not client_matches and did in catchup_matches:
            client_matches = catchup_matches[did]

        if not client_matches:
            print(f"CLIENT {cid}: no unsent matches to send.")
            continue

        try:
            text = build_digest(d, client_matches, tenders)
            message_id = send_telegram(
                cfg["TELEGRAM_BOT_TOKEN"],
                d["chat_id"],
                text,
            )

            mark_all_sent(cfg, d, client_matches, message_id)

            digests_sent += 1
            tenders_marked += len(client_matches)
            print(
                f"DIGEST SENT: client={cid} "
                f"new_tenders={len(client_matches)} "
                f"message_id={message_id}"
            )

        except Exception as e:
            errors += 1
            print(f"DIGEST ERROR client={cid}: {str(e)[:1000]}")

    print(
        f"DONE digests_sent={digests_sent} "
        f"tenders_marked_sent={tenders_marked} "
        f"errors={errors}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
