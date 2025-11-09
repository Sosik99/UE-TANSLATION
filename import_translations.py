import re
import os
import polib
import hashlib
import difflib

def msgid_hash(msgid):
    return hashlib.md5(msgid.encode('utf-8')).hexdigest().upper()

def parse_hash_blocks(filename):
    """Načte bloky HASH\nTEXT\n\n a vrátí dict hash->text"""
    result = {}
    with open(filename, "r", encoding="utf-8") as f:
        data = f.read().splitlines()

    # Detect PO-like blocks
    is_po_like = any(l.strip().startswith('msgctxt') or l.strip().startswith('msgid') for l in data)
    if is_po_like:
        i = 0
        cur_hash = None
        cur_translation = None
        while i < len(data):
            ln = data[i].strip()
            if ln.startswith('msgctxt'):
                # extract hash between quotes; msgctxt ",HASH" or msgctxt "HASH"
                m = re.match(r'msgctxt\s+"(.*)"', ln)
                if m:
                    content = m.group(1)
                    if content.startswith(','):
                        cur_hash = content[1:]
                    else:
                        cur_hash = content
                i += 1
                continue
            if ln.startswith('msgstr'):
                m = re.match(r'msgstr\s+"(.*)"', ln)
                if m and cur_hash:
                    val = m.group(1)
                    # restore common literal escapes to keep them consistent (we keep as-is)
                    val = val.replace('\\r\\n', '\\r\\n')
                    result[cur_hash] = val
                    cur_hash = None
                i += 1
                continue
            i += 1
        return result

    # Fallback: old simple HASH\nTEXT\n\n format
    key = None
    text = []
    for line in data:
        if key is None and line.strip():
            key = line.strip()
            text = []
        elif key is not None and line.strip():
            text.append(line)
        elif key is not None and not line.strip():
            if key and text:
                result[key] = "".join(text).strip()
            key = None
            text = []
    if key and text:
        result[key] = "".join(text).strip()
    return result

def import_translations(po_file, translations_file):
    # Načti překlady s jejich hash key
    hash_to_translation = parse_hash_blocks(translations_file)
    po = polib.pofile(po_file)
    updated_count = 0
    for entry in po:
        hashval = msgid_hash(entry.msgid.strip())
        if hashval in hash_to_translation:
            # Keep the translation as a single-line quoted string in the PO by ensuring
            # newline characters are represented as literal escape sequences (e.g. "\\r\\n").
            # Unreal expects the translated text as a single string with escape sequences,
            # so we do not convert escapes into real newlines here.
            val = hash_to_translation[hashval]
            try:
                # If the translation accidentally contains real newlines, escape them back
                val = val.replace('\r\n', '\\r\\n')
                val = val.replace('\r', '\\r')
                val = val.replace('\n', '\\n')
            except Exception:
                pass
            try:
                # Normalize sequences like "\\r\\r" (or longer runs) into "\\r\\n"
                # so the PO uses CRLF for paragraph breaks instead of repeated \r.
                val = re.sub(r'(?:\\r){2,}', r'\\r\\n', val)
            except Exception:
                pass
            entry.msgstr = val
            updated_count += 1
    print(f"Aktualizováno {updated_count} překladů z celkem {len(po)} záznamů")
    output_file = os.path.join('translated', os.path.basename(po_file))
    po.save(output_file)
    print(f"Překlady byly importovány do {output_file}")
    # Post-process the saved PO to collapse multi-line quoted msgid/msgstr into single quoted lines
    try:
        def _collapse_multiline_quotes(path):
            with open(path, 'r', encoding='utf-8') as rf:
                lines = rf.readlines()

            out_lines = []
            i = 0
            while i < len(lines):
                ln = lines[i]
                stripped = ln.lstrip()
                if stripped.startswith('msgid ') or stripped.startswith('msgstr '):
                    key = 'msgid' if stripped.startswith('msgid ') else 'msgstr'
                    # capture the initial quoted part on the same line
                    m = re.match(r"(msgid|msgstr)\s+(.*)$", stripped)
                    if not m:
                        out_lines.append(ln)
                        i += 1
                        continue
                    rest = m.group(2).rstrip('\n')
                    parts = []
                    # if rest starts and ends with a quote, extract inner
                    if rest.strip().startswith('"'):
                        # if this line contains a closing quote at end, take inner content
                        inner = rest.strip()
                        if inner.endswith('"') and len(inner) >= 2:
                            inner_content = inner[1:-1]
                            parts.append(inner_content)
                        else:
                            # malformed, just append as-is
                            parts.append(inner)
                    else:
                        parts.append(rest)

                    # now capture following continuation lines starting with a quoted string
                    j = i + 1
                    while j < len(lines):
                        nxt = lines[j].lstrip()
                        if re.match(r'^".*"\s*$', nxt):
                            cont = nxt.strip()
                            parts.append(cont[1:-1])
                            j += 1
                        else:
                            break

                    # combine parts into single string
                    combined = ''.join(parts)
                    # Reduce multiple backslashes before r/n markers to a single backslash
                    try:
                        combined = re.sub(r'(?:\\\\)+(r|n)', r'\\\1', combined)
                    except Exception:
                        pass
                    # escape only double quotes for single-line representation; keep backslashes as-is
                    combined_repr = combined.replace('"', '\\"')
                    out_lines.append(f"{key} \"{combined_repr}\"\n")
                    i = j
                else:
                    out_lines.append(ln)
                    i += 1

            with open(path, 'w', encoding='utf-8') as wf:
                wf.writelines(out_lines)

        _collapse_multiline_quotes(output_file)
    except Exception:
        pass

if __name__ == "__main__":
    os.makedirs("to_translate", exist_ok=True)
    os.makedirs("to_translate_txt", exist_ok=True)
    os.makedirs("translated_txt", exist_ok=True)
    os.makedirs("translated", exist_ok=True)
    # Build a map of normalized translated_txt stems to filenames
    translated_files = [fn for fn in os.listdir('translated_txt') if fn.lower().endswith('_translated.txt')]
    def _normalize(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower() if s else '')
    translated_map = {}
    for fn in translated_files:
        stem = fn[:-len('_translated.txt')]
        translated_map[_normalize(stem)] = fn

    for fname in os.listdir('to_translate'):
        if not fname.endswith('.po'):
            continue
        base_name = fname[:-3]
        po_file = os.path.join('to_translate', fname)
        # try exact match
        translations_file = os.path.join('translated_txt', f"{base_name}_translated.txt")
        if not os.path.exists(translations_file):
            # try normalized match and fuzzy fallback
            norm = _normalize(base_name)
            if norm in translated_map:
                translations_file = os.path.join('translated_txt', translated_map[norm])
            else:
                close = difflib.get_close_matches(norm, list(translated_map.keys()), n=1, cutoff=0.6)
                if close:
                    translations_file = os.path.join('translated_txt', translated_map[close[0]])
                else:
                    translations_file = None
        if translations_file and os.path.exists(translations_file):
            print(f"Importuji překlady pro {fname}... (zdroj: {os.path.basename(translations_file)})")
            import_translations(po_file, translations_file)
        else:
            print(f"Nenalezen překladový soubor pro {fname}, přeskočeno.")
