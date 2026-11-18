import json, collector_zakup as z
rows = z.collect_samruk(["картридж", "светильник"])
print("SKROWS", len(rows))
for r in rows[:5]:
    print("SKROW", json.dumps({k: r[k] for k in ("source_lot_id","title","customer_name","amount","expires_at","public_url")}, ensure_ascii=False))
