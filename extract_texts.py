import polib
import re
import os
import hashlib

# Výrazy, které se nemají překládat (pouze UE příkazy)
NO_TRANSLATE_PATTERNS = [
    r"^r\\.",
    r"^sg\\.",
    r"^t\\.",
    r"^PostProcessAAQuality",
    r"^sg\\.ViewDistanceQuality",
    r"^sg\\.EffectsQuality",
    r"^sg\\.ShadowQuality",
    r"^sg\\.TextureQuality",
    r"^r\\.VSync",
    r"^r\\.ScreenPercentage",
    r"^r\\.setres",
    r".*free3d\\.com$",
    r".*sketchfab\\.com$",
    r".*cgtrader\\.com$",
    r".*fab\\.com$",
    r".*freesound\\.org$",
    r".*unrealengine\\.com$",
]

def should_translate(text):
    for pat in NO_TRANSLATE_PATTERNS:
        if re.match(pat, text):
            return False
    return True

def msgid_hash(msgid):
    return hashlib.md5(msgid.encode('utf-8')).hexdigest().upper()

def extract_and_filter_entries(po_path):
    po = polib.pofile(po_path)
    filtered_entries = []
    for entry in po:
        if entry.msgid and any(c.isalpha() for c in entry.msgid):
            if should_translate(entry.msgid.strip()):
                hashval = msgid_hash(entry.msgid.strip())
                filtered_entries.append((hashval, entry.msgid.strip()))
    return filtered_entries

if __name__ == "__main__":
    # Vytvoř složky, pokud neexistují
    os.makedirs("to_translate", exist_ok=True)
    os.makedirs("to_translate_txt", exist_ok=True)
    
    # Najdi všechny .po soubory ve složce to_translate
    for fname in os.listdir('to_translate'):
        if fname.endswith('.po'):
            po_path = os.path.join('to_translate', fname)
            filtered_entries = extract_and_filter_entries(po_path)
            
            # Ulož texty k překladu do souboru ve formátu PO-like (msgctxt/msgid/msgstr)
            to_translate_file = os.path.join('to_translate_txt', fname.replace('.po', '_to_translate.txt'))
            def _escape_text(s: str) -> str:
                # escape backslashes and double quotes, and represent newlines as literal \n / \r\n
                if s is None:
                    return ''
                t = s.replace('\\', '\\\\')
                t = t.replace('"', '\\"')
                # normalize CRLF first
                t = t.replace('\r\n', '\\r\\n')
                t = t.replace('\n', '\\n')
                return t

            with open(to_translate_file, "w", encoding="utf-8") as f:
                for hashval, text in filtered_entries:
                    if text.strip():
                        esc = _escape_text(text)
                        f.write(f'msgctxt ",{hashval}"\n')
                        f.write(f'msgid "{esc}"\n')
                        f.write('msgstr ""\n\n')
            
            print(f"Extrahované texty byly uloženy do {to_translate_file}")
