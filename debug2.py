"""
debug2.py

Aggressively clear translations (set msgstr to "") for entries that look
like Unreal Engine console commands, tokens, placeholders or simple numeric
resolution strings. Operates on all `.po` files in the `translated/` folder.

Usage:
    python debug2.py         # runs and modifies .po files (no .bak created)
  python debug2.py --dry   # dry-run: prints actions but doesn't save

This is intentionally opinionated: any msgid containing UE-style prefixes
(r., t., sg., stat), resolution patterns like 1920x1080, placeholders like
__UE_TOKEN_... or specific known keys (e.g. t.MaxFPS) will have their
msgstr cleared so the game will fall back to the original msgid.
"""

import re
import shutil
import sys
from pathlib import Path
import argparse

try:
    import polib
except Exception:
    print("polib not installed; please pip install polib")
    sys.exit(1)

BASE = Path(__file__).resolve().parent
PO_DIR = BASE / 'translated'


def should_clear(msgid: str, msgstr: str) -> bool:
    if not msgid:
        return False
    s = msgid
    # placeholder in translation or id
    if msgstr and '__UE_TOKEN_' in msgstr:
        return True
    if '__UE_TOKEN_' in s:
        return True

    # resolution pattern like 1920x1080 or 3840×2160 (x or ×) or '640 x 480'
    if re.search(r"\b\d+\s*[x×]\s*\d+\b", s):
        return True

    # UE-style prefixes / commands (r., t., sg., stat, ai., p., net.)
    if re.search(r"\b(r\.|t\.|sg\.|stat\b|ai\.|p\.|net\.|sg\b)", s, re.IGNORECASE):
        return True

    # common specific tokens
    specific = [
        'r.setres', 'r.ScreenPercentage', 'r.VSync', 't.MaxFPS',
        'sg.ViewDistanceQuality', 'sg.TextureQuality', 'sg.PostProcessQuality',
        'sg.ShadowQuality', 'sg.EffectsQuality', 'r.ReflectionMethod',
        'r.TonemapperGamma'
    ]
    lower = s.lower()
    for tok in specific:
        if tok.lower() in lower:
            return True

    return False


def process_file(pofile: Path, dry=False):
    print(f"Processing {pofile}")
    po = polib.pofile(str(pofile))
    changed = False
    for entry in po:
        if not entry.msgid:
            continue
        if should_clear(entry.msgid, entry.msgstr or ''):
            if entry.msgstr != '':
                print(f"  Clearing msgstr for msgid: {entry.msgid[:80]!r}...")
                entry.msgstr = ''
                changed = True

    if changed:
        if dry:
            print(f"  [dry-run] would save {pofile} (no backup)")
            return
        # disable wrapping so polib writes single-line values where possible
        try:
            po.wrapwidth = 0
        except Exception:
            pass
        po.save(str(pofile))
        print(f"  Saved {pofile} (no backup created)")
    else:
        print("  No changes needed")


def main():
    parser = argparse.ArgumentParser(description='Aggressively clear UE tokens from translated .po files')
    parser.add_argument('--dry', action='store_true', help='Dry-run: do not save changes')
    args = parser.parse_args()

    if not PO_DIR.exists() or not PO_DIR.is_dir():
        print(f"Translated directory not found: {PO_DIR}")
        sys.exit(1)

    po_files = sorted(PO_DIR.glob('*.po'))
    if not po_files:
        print(f"No .po files found in {PO_DIR}")
        return

    for p in po_files:
        process_file(p, dry=args.dry)


if __name__ == '__main__':
    main()
