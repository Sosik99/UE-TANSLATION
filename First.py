"""
First.py

Scan the `First_Format/` folder for language subfolders containing `.po` files
(from Unreal Engine exports). Rename/move them into the project's `to_translate/`
directory using the canonical language names used by the pipeline.

Usage:
  python First.py [--first-dir First_Format] [--dest-dir to_translate] [--dry] [--overwrite] [--map-file mapping.json]

Options:
  --first-dir   Source folder containing language subfolders (default: First_Format)
  --dest-dir    Destination folder for renamed .po files (default: to_translate)
  --dry         Do a dry run; print actions but don't move files.
  --overwrite   Overwrite existing destination files if present.
  --map-file    Optional JSON file mapping folder names to target language names.

Behavior:
  - For each top-level subdirectory under `first-dir`, the script will search
    recursively for `.po` files. If found, it will map the folder name (e.g. "zh")
    to a canonical language name (e.g. "Chinese (Simplified)") and move/rename the
    `.po` file to `dest-dir/<LanguageName>.po`.
  - If multiple .po files are found for the same language, they will be named
    `<LanguageName>.po`, `<LanguageName>_1.po`, `<LanguageName>_2.po`, ...

This script is intentionally conservative and provides a dry-run mode. It
includes a sensible default mapping tuned to the languages present in the
project; you can override or extend it with `--map-file`.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

# Default mapping: folder-code -> canonical language name used in other scripts
DEFAULT_CODE_TO_NAME = {
    'zh': 'Chinese (Simplified)',
    'cs': 'Czech',
    'fr': 'French',
    'de': 'German',
    'ja': 'Japanese',
    'pt': 'Portugase (Brazil)',
    'ru': 'Russian',
    'es': 'Spanish',
    'tr': 'Turkish',
    'uk': 'Ukrainian',
    'en': 'English',
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
            # normalize keys to lower-case for folder lookup
            return {k.lower(): v for k, v in j.items()}
    except Exception as e:
        print(f"Failed to load mapping file {map_file}: {e}")
        return {}


def find_po_files_in_dir(root: Path):
    """Recursively find .po files under root and return list of Path objects"""
    out = []
    if not root.exists():
        return out
    for p in root.rglob('*.po'):
        if p.is_file():
            out.append(p)
    return out


def safe_mkdir(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description='Move/rename .po files from First_Format to to_translate')
    parser.add_argument('--first-dir', default='First_Format', help='Source folder with language subfolders')
    parser.add_argument('--dest-dir', default='to_translate', help='Destination folder for renamed .po files')
    parser.add_argument('--dry', action='store_true', help='Dry run: only print actions')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing files in destination')
    parser.add_argument('--move', action='store_true', help='Move files instead of copying (default: copy)')
    parser.add_argument('--delete-en', action='store_true', help="If provided, delete the 'en' folder under --first-dir (and its contents). Use with --dry to preview.")
    parser.add_argument('--map-file', default=None, help='Optional JSON mapping file for folder->language name')
    args = parser.parse_args()

    first_dir = Path(args.first_dir)
    dest_dir = Path(args.dest_dir)
    safe_mkdir(dest_dir)

    user_map = load_mapping(args.map_file)
    # merge default map with user-supplied map (user overrides defaults)
    code_to_name = {**DEFAULT_CODE_TO_NAME, **user_map}

    if not first_dir.exists():
        print(f"Source folder '{first_dir}' does not exist. Nothing to do.")
        return

    # Iterate top-level directories (languages) inside first_dir
    moved = []
    skipped = []
    errors = []

    for child in sorted(first_dir.iterdir()):
        if not child.is_dir():
            # skip files directly under First_Format
            continue
        folder_name = child.name
        folder_name_lower = folder_name.lower()

        # Special handling: never process the English export folder. The user asked
        # for the script to ignore 'en' entirely and optionally delete it.
        if folder_name_lower == 'en':
            if args.delete_en:
                # deletion requested. Honor dry-run flag.
                if args.dry:
                    print(f"DRY: would delete folder '{child}' and its contents (--delete-en)")
                else:
                    try:
                        # shutil.rmtree is destructive; wrap in try/except
                        print(f"Deleting folder '{child}' and its contents (--delete-en)")
                        shutil.rmtree(str(child))
                    except Exception as e:
                        print(f"Failed to delete '{child}': {e}")
                        errors.append((child, None, str(e)))
            else:
                print(f"Skipping 'en' folder '{child}' (use --delete-en to remove it)")
            # either way, do not process this folder further
            continue

        # Determine target language name
        target_name = None
        # 1) exact match by folder code
        if folder_name_lower in code_to_name:
            target_name = code_to_name[folder_name_lower]
        else:
            # 2) try to interpret folder as a language name already
            maybe = folder_name.replace('_', ' ').strip()
            if maybe.title() in code_to_name.values():
                target_name = maybe.title()
            else:
                # 3) fallback: title-case the folder name and use that
                target_name = maybe.title()

        # find .po files under this language folder
        po_files = find_po_files_in_dir(child)
        if not po_files:
            print(f"No .po files found under '{child}', skipping.")
            continue

        # if multiple .po files, enumerate them
        for idx, po in enumerate(sorted(po_files)):
            if idx == 0:
                dest_name = f"{target_name}.po"
            else:
                dest_name = f"{target_name}_{idx}.po"
            dest_path = dest_dir / dest_name

            if dest_path.exists() and not args.overwrite:
                print(f"Destination {dest_path} already exists; use --overwrite to replace. Skipping {po}.")
                skipped.append((po, dest_path))
                continue

            # prepare action
            action = f"MOVE {po} -> {dest_path}"
            if args.dry:
                print("DRY: "+action)
                moved.append((po, dest_path))
            else:
                try:
                    # ensure parent exists
                    safe_mkdir(dest_path.parent)
                    # If destination exists and overwrite requested, remove first
                    if dest_path.exists() and args.overwrite:
                        try:
                            dest_path.unlink()
                        except Exception:
                            pass
                    if args.move:
                        # move semantics
                        shutil.move(str(po), str(dest_path))
                    else:
                        # default: copy (preserve metadata)
                        shutil.copy2(str(po), str(dest_path))
                    print(action)
                    moved.append((po, dest_path))
                except Exception as e:
                    print(f"Failed to copy/move {po} -> {dest_path}: {e}")
                    errors.append((po, dest_path, str(e)))

    # Summary
    print('\nSummary:')
    print(f"Planned moves: {len(moved)} (dry={args.dry})")
    if skipped:
        print(f"Skipped due to existing dest (use --overwrite to replace): {len(skipped)}")
        for s, d in skipped:
            print(f"  - {s} -> {d}")
    if errors:
        print(f"Errors: {len(errors)}")
        for p, d, e in errors:
            print(f"  - {p} -> {d}: {e}")

if __name__ == '__main__':
    main()
