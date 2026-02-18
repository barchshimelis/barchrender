#!/usr/bin/env python3
"""
find_po_duplicates_v2.py – dump every duplicate msgid/msgctxt inside locale/*/LC_MESSAGES/django.po
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
LOCALE_DIR = ROOT / "locale"
PO_FILENAME = "LC_MESSAGES/django.po"


def read_po(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8").splitlines()


def collect_quoted(lines: List[str], start: int, keyword: str) -> Tuple[str, int]:
    """Return the concatenated string literal that starts at lines[start] after keyword."""
    raw = lines[start]
    payload = raw[len(keyword):].lstrip()
    if not payload.startswith('"'):
        return "", start
    value = payload[1:-1]
    idx = start + 1
    while idx < len(lines):
        stripped = lines[idx].lstrip()
        if stripped.startswith('"'):
            value += stripped[1:-1]
            idx += 1
        else:
            break
    return value, idx - 1


def find_duplicates(po_path: Path) -> Dict[Tuple[Optional[str], str], List[int]]:
    lines = read_po(po_path)
    duplicates: Dict[Tuple[Optional[str], str], List[int]] = defaultdict(list)
    pending_context: Optional[str] = None
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("msgctxt "):
            pending_context, idx = collect_quoted(lines, idx, "msgctxt ")
        elif line.startswith("msgid "):
            line_no = idx + 1  # 1-indexed for readability
            msgid, idx = collect_quoted(lines, idx, "msgid ")
            if msgid:
                duplicates[(pending_context, msgid)].append(line_no)
            pending_context = None  # reset after pairing with the msgid
        elif not line.strip():
            pending_context = None
        idx += 1

    return {key: locs for key, locs in duplicates.items() if len(locs) > 1}


def main() -> int:
    if not LOCALE_DIR.exists():
        print(f"[error] Locale directory not found: {LOCALE_DIR}")
        return 1

    found_any = False
    for lang_dir in sorted(LOCALE_DIR.iterdir()):
        po_file = lang_dir / PO_FILENAME
        if not po_file.is_file():
            continue

        dupes = find_duplicates(po_file)
        if not dupes:
            continue

        found_any = True
        rel = po_file.relative_to(ROOT)
        print(f"\n[{lang_dir.name}] {rel}")
        for (ctx, msgid), lines in dupes.items():
            ctx_display = ctx if ctx is not None else "None"
            line_list = ", ".join(str(n) for n in lines)
            print(f'  • ctx={ctx_display!r} | msgid="{msgid}" -> lines {line_list}')

    if not found_any:
        print("No duplicate msgid/msgctxt entries detected.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())