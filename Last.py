"""
Last.py

Take `.po` files from the `translated/` folder and prepare a folder layout compatible
with Unreal Engine import (the inverse of `First.py`). For each language file in
`translated/` (e.g. `translated/Czech.po`) this script will create a subfolder in
`Last_Format/` named by language code (e.g. `cs`) and copy the `.po` as `Game.po`.

Usage:
    python Last.py [--translated-dir translated] [--out-dir Last_Format] [--dry] [--overwrite] [--move] [--map-file mapping.json]

Options:
  --translated-dir  Source folder with translated `.po` files (default: translated)
    --out-dir         Destination root (default: Last_Format)
  --dry             Dry run: only print planned actions
  --overwrite       Overwrite existing Game.po files
  --move            Move files instead of copying
  --map-file        Optional JSON mapping file mapping language names -> folder codes

This script is conservative by default (copy, not move). Supply `--move` to
perform destructive moves.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

# Default reverse mapping: language name -> folder code
DEFAULT_NAME_TO_CODE = {
    'Chinese (Simplified)': 'zh',
    'Czech': 'cs',
    'French': 'fr',
    'German': 'de',
    'Japanese': 'ja',
    'Portugase (Brazil)': 'pt',
    'Portuguese (Brazil)': 'pt',
    'Russian': 'ru',
    'Spanish': 'es',
    'Turkish': 'tr',
    'Ukrainian': 'uk',
    'English': 'en',
}


def load_mapping(map_file: str):
    if not map_file:
        return {}
    try:
        with open(map_file, 'r', encoding='utf-8') as f:
            j = json.load(f)
            if not isinstance(j, dict):
                print(f"Map file {map_file} does not contain a JSON object; ignoring.")
                return {}
            # normalize keys to exact strings as provided (language name -> code)
            return {k: v for k, v in j.items()}
    except Exception as e:
        print(f"Failed to load mapping file {map_file}: {e}")
        return {}


def safe_mkdir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def find_translated_pos(src: Path):
    if not src.exists():
        return []
    out = []
    for p in src.glob('*.po'):
        if p.is_file():
            out.append(p)
    return sorted(out)


def main():
    parser = argparse.ArgumentParser(description='Prepare First_Format layout from translated .po files')
    parser.add_argument('--translated-dir', default='translated', help='Source folder with translated .po files')
    parser.add_argument('--out-dir', default='Last_Format', help='Destination root folder (UE import layout)')
    parser.add_argument('--dry', action='store_true', help='Dry run: only print planned actions')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing Game.po files')
    parser.add_argument('--move', action='store_true', help='Move files instead of copying')
    parser.add_argument('--map-file', default=None, help='Optional JSON mapping file (language name -> folder code)')
    args = parser.parse_args()

    src_dir = Path(args.translated_dir)
    out_dir = Path(args.out_dir)
    safe_mkdir(out_dir)

    user_map = load_mapping(args.map_file)
    name_to_code = {**DEFAULT_NAME_TO_CODE, **user_map}

    pos = find_translated_pos(src_dir)
    if not pos:
        print(f"No .po files found in '{src_dir}'. Nothing to do.")
        return

    planned = []
    errors = []

    for p in pos:
        name = p.stem  # e.g. 'Czech' or 'Chinese (Simplified)'
        # try to map by exact name first; fallback to title-cased stem
        folder_code = name_to_code.get(name)
        if not folder_code:
            # try normalized matches
            maybe = name.strip()
            folder_code = name_to_code.get(maybe.title())
        if not folder_code:
            # last resort: try lowercase code match (if name is like 'cs' etc.)
            if len(name) <= 3 and name.lower() in name_to_code.values():
                folder_code = name.lower()
        if not folder_code:
            print(f"Warning: no folder code mapping for language '{name}'. Skipping.")
            continue

        dest_folder = out_dir / folder_code
        dest_path = dest_folder / 'Game.po'

        if dest_path.exists() and not args.overwrite:
            print(f"Destination {dest_path} already exists; use --overwrite to replace. Skipping {p}.")
            continue

        action = f"COPY {p} -> {dest_path}"
        planned.append((p, dest_path, action))

    # Execute or dry-run
    if args.dry:
        print("Dry run, planned actions:")
        for _, _, act in planned:
            print("  - "+act)
        print(f"Total: {len(planned)} file(s)")
        return

    # perform copies/moves
    for src, dst, act in planned:
        try:
            safe_mkdir(dst.parent)
            if dst.exists() and args.overwrite:
                try:
                    dst.unlink()
                except Exception:
                    pass
            if args.move:
                shutil.move(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            print(act)
        except Exception as e:
            errors.append((src, dst, str(e)))

    if errors:
        print('\nErrors:')
        for s, d, e in errors:
            print(f"  - {s} -> {d}: {e}")
    else:
        print(f"\nDone. Prepared {len(planned)} file(s) in '{out_dir}'.")


if __name__ == '__main__':
    main()
