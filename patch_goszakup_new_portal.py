# -*- coding: utf-8 -*-
"""
Tender Radar KZ Commercial
Hotfix for Goszakup Unified Platform links.

The old collector built /ru/announce/index/{numberAnno}.
The unified portal expects the internal TrdBuy.id.
This script patches the checked-out collector_goszakup.py before each run.
"""

from pathlib import Path

p = Path(__file__).resolve().parent / "collector_goszakup.py"
s = p.read_text(encoding="utf-8")

replacements = [
    (
        'PUBLIC_ANNOUNCE_URL = "https://www.goszakup.gov.kz/ru/announce/index/{number_anno}"',
        'PUBLIC_ANNOUNCE_URL = "https://www.goszakup.gov.kz/ru/announce/index/{announcement_id}"'
    ),
    (
        '    announcement_number: str\n    title: str',
        '    announcement_number: str\n    announcement_id: str\n    title: str'
    ),
    (
        '    ann = str(safe(lot, "trdBuyNumberAnno") or safe(buy, "numberAnno"))\n    external_id = str(safe(lot, "id"))',
        '    ann = str(safe(lot, "trdBuyNumberAnno") or safe(buy, "numberAnno"))\n'
        '    announcement_id = str(safe(lot, "trdBuyId") or safe(buy, "id"))\n'
        '    external_id = str(safe(lot, "id"))'
    ),
    (
        '        announcement_number=ann,\n        title=str(safe(lot, "nameRu")),',
        '        announcement_number=ann,\n        announcement_id=announcement_id,\n        title=str(safe(lot, "nameRu")),'
    ),
    (
        '        public_url=PUBLIC_ANNOUNCE_URL.format(number_anno=ann) if ann else "",',
        '        public_url=PUBLIC_ANNOUNCE_URL.format(announcement_id=announcement_id) if announcement_id else "",'
    ),
]

changed = 0
for old, new in replacements:
    if old in s:
        s = s.replace(old, new, 1)
        changed += 1
    elif new in s:
        pass
    else:
        raise RuntimeError("Expected fragment not found in collector_goszakup.py")

p.write_text(s, encoding="utf-8")
print(f"Goszakup link hotfix OK; patched fragments: {changed}")
