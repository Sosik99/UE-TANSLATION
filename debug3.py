"""
debug3.py

Rewrite .po files in `translated/` by collapsing multiline quoted msgid/msgstr
blocks into single quoted strings. This removes the multiple ""-quoted lines
format (the lines like

  msgid ""
  "line1"
  "line2"

and replaces it with

  msgid "line1 line2"

The script intentionally does not create backups and operates in-place.

It will skip the PO header (the initial msgid "" / msgstr "" metadata block).

Usage:
  python debug3.py

Be careful: this will rewrite files in `translated/` in-place without .bak files.
"""

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PO_DIR = BASE / 'translated'


def collapse_quoted_block(block: str) -> str:
    # block is a sequence of lines like:
    # "first part"
    # "second part"
    # We want to extract inner content and join with a single space,
    # preserving any literal backslash escapes (e.g. \r\n) inside segments.
    parts = re.findall(r'"(.*)"', block)
    # join with space, collapse multiple whitespace into single space
    joined = ' '.join(p for p in parts if p != '')
    joined = re.sub(r'\s+', ' ', joined).strip()
    return '"' + joined + '"'


def process_text(text: str) -> str:
    # Find header block (first occurrence of msgid "" followed by msgstr "" and quoted lines)
    header_match = re.search(r'\A([\s\S]*?msgid ""\nmsgstr ""\n(?:".*"\n)+)', text)
    header = ''
    rest = text
    if header_match:
        header = header_match.group(1)
        rest = text[len(header):]

    # Collapse msgid blocks: msgid ""\n("..."\n)+  -> msgid "joined"
    def _msgid_repl(m):
        quoted = m.group(2)
        new = collapse_quoted_block(quoted)
        return m.group(1) + new + '\n'

    rest = re.sub(r'(msgid\s+)""\n((?:".*"\n)+)', _msgid_repl, rest)

    # Collapse msgstr blocks similarly: msgstr ""\n("..."\n)+ -> msgstr "joined"
    def _msgstr_repl(m):
        quoted = m.group(2)
        new = collapse_quoted_block(quoted)
        return m.group(1) + new + '\n'

    rest = re.sub(r'(msgstr\s+)""\n((?:".*"\n)+)', _msgstr_repl, rest)

    return header + rest


def process_file(path: Path):
    print(f"Processing {path}")
    txt = path.read_text(encoding='utf-8')
    new = process_text(txt)
    if new != txt:
        path.write_text(new, encoding='utf-8')
        print(f"  Rewrote {path} (in-place, no backup)")
    else:
        print(f"  No changes for {path}")


def main():
    if not PO_DIR.exists() or not PO_DIR.is_dir():
        print(f"Translated directory not found: {PO_DIR}")
        sys.exit(1)
    files = sorted(PO_DIR.glob('*.po'))
    if not files:
        print(f"No .po files found in {PO_DIR}")
        return
    for p in files:
        process_file(p)


if __name__ == '__main__':
    main()
