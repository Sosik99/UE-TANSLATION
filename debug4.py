"""
debug4.py

Reset translations of language names in .po files under `translated/`.
Example: msgid "English" with any msgstr will be set to msgstr "".

Usage:
  python debug4.py        # apply changes in-place (no backups)
  python debug4.py --dry  # dry-run, only prints what would change

This script matches msgid values against a curated list of language names
and common variants (case-insensitive). If an entry's msgid matches, its
msgstr will be cleared.
"""

import argparse
from pathlib import Path
import sys
import polib

BASE = Path(__file__).resolve().parent
PO_DIR = BASE / 'translated'

# Curated list of language names and common variants. Lowercased for matching.
LANG_NAMES = [
    'english', 'spanish', 'french', 'german', 'italian', 'portuguese',
    'portuguese (brazil)', 'portuguese (brazilian)', 'portugese (brazil)',
    'russian', 'japanese', 'chinese', 'chinese (simplified)', 'chinese (traditional)',
    'korean', 'turkish', 'ukrainian', 'czech', 'polish', 'dutch', 'swedish',
    'norwegian', 'danish', 'finnish', 'hungarian', 'romanian', 'bulgarian',
    'greek', 'hebrew', 'arabic', 'hindi', 'bengali', 'vietnamese', 'indonesian',
    'malay', 'thai', 'slovak', 'serbian', 'croatian', 'slovenian', 'estonian',
    'latvian', 'lithuanian', 'persian', 'iranian', 'catalan', 'galician',
    'basque', 'uk', 'zh-cn', 'zh-tw'
]


def is_language_name(s: str) -> bool:
    if not s:
        return False
    low = s.strip().lower()
    # direct match
    if low in LANG_NAMES:
        return True
    # some msgids include parentheses or region markers like 'Portuguese (Brazil)'
    for name in LANG_NAMES:
        if low == name:
            return True
    return False


def process_file(path: Path, dry=False):
    po = polib.pofile(str(path))
    changed = False
    for entry in po:
        if not entry.msgid:
            continue
        # Only consider exact msgid matches (strip whitespace)
        if is_language_name(entry.msgid):
            if entry.msgstr != '':
                print(f"Will clear '{entry.msgid}' in {path.name}")
                if not dry:
                    entry.msgstr = ''
                    changed = True

    if changed and not dry:
        # disable wrapping to keep single-line msgstr when possible
        try:
            po.wrapwidth = 0
        except Exception:
            pass
        po.save(str(path))
        print(f"Saved {path} (no backup)")


def main():
    parser = argparse.ArgumentParser(description='Reset language-name translations in translated/*.po')
    parser.add_argument('--dry', action='store_true', help='Dry-run: do not save changes')
    args = parser.parse_args()

    if not PO_DIR.exists() or not PO_DIR.is_dir():
        print(f"Translated directory not found: {PO_DIR}")
        sys.exit(1)

    files = sorted(PO_DIR.glob('*.po'))
    if not files:
        print(f"No .po files found in {PO_DIR}")
        return

    for p in files:
        process_file(p, dry=args.dry)


if __name__ == '__main__':
    main()
