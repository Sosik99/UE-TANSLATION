import os
from googletrans import Translator
import time
import re
import random
import traceback
from datetime import datetime
import json
import urllib.parse
import urllib.request
import difflib
import atexit

# Prevent system sleep on Windows while this script is running.
_sleep_prevented = False
_es_prev = None
def prevent_sleep():
    """Prevent Windows from sleeping while translations run. No-op on non-Windows."""
    global _sleep_prevented, _es_prev
    try:
        if os.name == 'nt':
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_AWAYMODE_REQUIRED = 0x00000040
            # call SetThreadExecutionState to prevent sleep
            fun = ctypes.windll.kernel32.SetThreadExecutionState
            # preserve previous state (best-effort)
            _es_prev = fun(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
            _sleep_prevented = True
    except Exception:
        _sleep_prevented = False

def restore_sleep():
    """Restore previous execution state on Windows. No-op elsewhere."""
    global _sleep_prevented, _es_prev
    try:
        if os.name == 'nt' and _sleep_prevented:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            # calling with ES_CONTINUOUS clears previous flags
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            _sleep_prevented = False
    except Exception:
        pass

atexit.register(restore_sleep)

translator = Translator()

# Mapování jazykových názvů na kódy googletrans
LANG_MAP = {
    'Chinese (Simplified)': 'zh-cn',
    'Czech': 'cs',
    'French': 'fr',
    'German': 'de',
    'Japanese': 'ja',
    'Portuguese (Brazil)': 'pt',
    'Russian': 'ru',
    'Spanish': 'es',
    'Turkish': 'tr',
    'Ukrainian': 'uk',
}

input_dir = "to_translate_txt"
output_dir = "translated_txt"
logs_dir = "logs"

if not os.path.exists(logs_dir):
    try:
        os.makedirs(logs_dir)
    except Exception:
        pass

# Optional local secrets file. Create `local_secrets.json` in the project root and add keys there
# Example:
# {
#   "GOOGLE_TRANSLATE_API_KEY": "your_key_here"
# }
LOCAL_SECRETS = {}
local_secrets_path = os.path.join(os.path.dirname(__file__), 'local_secrets.json')
if os.path.exists(local_secrets_path):
    try:
        with open(local_secrets_path, 'r', encoding='utf-8') as ls:
            LOCAL_SECRETS = json.load(ls)
    except Exception:
        LOCAL_SECRETS = {}

def log_failure(lang_name, text, attempt, exc, result_repr=None):
    """Append a structured failure entry to logs/failed_<lang>.log"""
    try:
        fname = os.path.join(logs_dir, f"failed_{lang_name.replace(' ', '_')}.log")
        with open(fname, 'a', encoding='utf-8') as lf:
            lf.write(f"--- {datetime.utcnow().isoformat()}Z ---\n")
            if attempt is not None:
                lf.write(f"Attempt: {attempt}\n")
            lf.write(f"Text: {text!r}\n")
            if result_repr is not None:
                lf.write(f"Result repr: {result_repr}\n")
            lf.write(f"Exception: {repr(exc)}\n")
            lf.write('Traceback:\n')
            lf.write(traceback.format_exc())
            lf.write('\n\n')
    except Exception:
        # best-effort logging, don't crash on logging failures
        pass


def try_gemini_translate(text, lang_name, target_lang_code):
    """Attempt to translate using Google Generative AI (Gemini) via REST API.
    This requires an API key for the Generative API (set GEMINI_API_KEY in env or local_secrets.json).
    The function sends a short prompt instructing the model to return only the translated text.
    Returns translated string or None on failure.
    """
    api_key = os.environ.get('GEMINI_API_KEY') or LOCAL_SECRETS.get('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        # Construct a strict prompt to ensure only the translated text is returned.
        prompt = (
            f"You are a concise translator.\n"
            f"Translate exactly the following text into {lang_name} and return only the translated text, with no extra commentary or formatting:\n\n"
            f"'''{text}'''\n"
        )
        url = 'https://generativeai.googleapis.com/v1beta2/models/gemini-2.5-pro:generate'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        body = {
            'prompt': {
                'text': prompt
            },
            'maxOutputTokens': 10000,
            'temperature': 0.0,
        }
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST', headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read()
            if not resp_body:
                return None
            parsed = json.loads(resp_body.decode('utf-8'))
            # Parse response: look for text in the first candidate
            translated = None
            if isinstance(parsed, dict):
                cand = parsed.get('candidates') or parsed.get('outputs') or parsed.get('output')
                if isinstance(cand, list) and cand:
                    first = cand[0]
                    if isinstance(first, dict):
                        content = first.get('content') or first.get('text')
                        if isinstance(content, list) and content:
                            # find first dict with 'text'
                            for item in content:
                                if isinstance(item, dict) and 'text' in item:
                                    translated = item.get('text')
                                    break
                            if translated is None:
                                if all(isinstance(x, str) for x in content):
                                    translated = '\n'.join(content)
                        elif isinstance(content, str):
                            translated = content
                if translated is None and 'text' in parsed and isinstance(parsed['text'], str):
                    translated = parsed['text']
            if translated:
                return translated.strip()
    except Exception as e:
        try:
            log_failure(lang_name or 'gemini', text, 'gemini', e, result_repr=None)
        except Exception:
            pass
        return None
    return None


def try_google_cloud_translate(text, target_lang_code, lang_name=None):
    """Attempt to translate using Google Cloud Translation REST API v2 if API key is provided via env var.
    Returns translated text on success, or None on any failure.
    Note: user must set environment variable GOOGLE_TRANSLATE_API_KEY with their API key or put it in local_secrets.json.
    """
    api_key = os.environ.get('GOOGLE_TRANSLATE_API_KEY') or os.environ.get('GOOGLE_API_KEY') or LOCAL_SECRETS.get('GOOGLE_TRANSLATE_API_KEY') or LOCAL_SECRETS.get('GOOGLE_API_KEY')
    if not api_key:
        return None
    try:
        url = 'https://translation.googleapis.com/language/translate/v2'
        data = urllib.parse.urlencode({
            'q': text,
            'target': target_lang_code,
            'format': 'text',
            'key': api_key,
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            if not body:
                return None
            parsed = json.loads(body.decode('utf-8'))
            translated = parsed.get('data', {}).get('translations', [])
            if translated and isinstance(translated, list):
                tt = translated[0].get('translatedText')
                return tt
    except Exception as e:
        try:
            log_failure(lang_name or 'google_cloud', text, 'gct', e, result_repr=None)
        except Exception:
            pass
        return None
    return None

# Seznam patternů UE5 příkazů / literalů, které se nemají překládat.
# These are written as 'contains' style regexes (no required ^ start anchor)
# so any text that contains a matching UE token will be skipped.
ue5_patterns = [
    # common r. console commands (e.g. r.ScreenPercentage, r.setres 1920x1080)
    r"r\.[A-Za-z]+",
    r"r\.setres",
    r"r\.ScreenPercentage",
    r"r\.VSync",
    r"r\.ReflectionMethod",
    # t. commands
    r"t\.MaxFPS",
    r"t\.n\.",
    # sg. scalability/quality commands
    r"sg\.[A-Za-z]+Quality",
    r"sg\.TextureQuality",
    r"sg\.ViewDistanceQuality",
    # common console-like tokens
    r"\bstat\b",
    r"\bshow\b",
    r"\bset\b",
    r"\bget\b",
    r"\bnet\b",
    # resolution-like patterns (digits x digits)
    r"\d+[ ]?[x×][ ]?\d+",
    r"\d+[ ]?FPS",
    # URLs and domains
    r"https?://",
    r"[\w\.-]+\.[a-z]{2,}(/\S*)?",
    # Common literal strings that should never be translated (company names, domains)
    r"freesound\.org",
    r"team\s+galactic\s+games",
    r"galactic\s+games",
    r"galacticgames",
    r"Daniel\s+Seman",
]

# Precompile UE patterns for 'contains' matching. We remove a leading ^ anchor
# so patterns are treated as substrings/searches rather than strict start-only matches.
ue5_compiled = [re.compile(p, re.IGNORECASE) for p in ue5_patterns]

batch_size = 25

# Technical token patterns and preservation lists
TECHNICAL_TOKENS = [r'__UE_TOKEN_\d+__\w+_\d+__', r'__UE_TOKEN_\d+__EN_\d+__']
TECHNICAL_TOKENS_COMPILED = [re.compile(p) for p in TECHNICAL_TOKENS]

# Game development terminology whitelist - prefer to keep these untranslated or use overrides
PRESERVE_TERMS = ['Blueprint', 'Skeletal', 'Vertex', 'Nanite', 'Niagara', 'Material', 'Mesh', 'Spec']

# Common spelling fixes and corrections before translation
SPELLING_FIXES = {
    'Gamapad': 'Gamepad',
    'srart': 'start',
    'BoneeFire': 'BoneFire',
}

# Term overrides: map source tokens to preferred target snippet (english->localized override)
# Keys are lower-cased for insensitive matching; values are the desired localized form per lang if available
TERM_OVERRIDES = {
    'mesh': {'zh-cn': '网格'},
    'spec': {'zh-cn': '高光'},
    'metalpaintmask': {'zh-cn': '金属喷漆遮罩'},
}

def _apply_spelling_fixes(s: str) -> str:
    if not s:
        return s
    for k, v in SPELLING_FIXES.items():
        # simple word-boundary replace (case-insensitive)
        s = re.sub(r'\b' + re.escape(k) + r'\b', v, s, flags=re.IGNORECASE)
    return s

def _apply_term_overrides(s: str, target_lang_code: str) -> str:
    if not s:
        return s
    out = s
    for src_term, per_lang in TERM_OVERRIDES.items():
        if src_term in out.lower():
            val = per_lang.get(target_lang_code)
            if val:
                # Replace occurrences case-insensitively while preserving surrounding text
                out = re.sub(r'(?i)\b' + re.escape(src_term) + r'\b', val, out)
    return out

def preprocess_text_for_translation(text: str, mask_map: dict, target_lang_code: str):
    """Apply spelling fixes, preserve technical tokens and whitelist terms, and apply overrides.
    This function protects mask_map placeholders by replacing them with safe tokens and returns
    a tuple (processed_text, protected_map) where protected_map maps safe_token -> original_placeholder.
    The caller is responsible for restoring safe tokens back to original placeholders after translation.
    """
    if text is None:
        return '', {}
    s = text
    # Apply spelling fixes first
    s = _apply_spelling_fixes(s)

    # Ensure placeholders from mask_map are preserved by temporarily protecting them with a safe wrapper
    protected_map = {}
    if mask_map:
        for idx, k in enumerate(mask_map.keys()):
            # create a compact safe token unlikely to be mangled
            safe = f'<<<UEPH_{idx}>>>'
            protected_map[safe] = k
            s = s.replace(k, safe)

    # Preserve whitelisted terms by marking them with a safe placeholder so they survive translation
    preserve_wrapper = {}
    for term in PRESERVE_TERMS:
        def repl(m):
            key = f'@@PRESERVE_{len(preserve_wrapper)}@@'
            preserve_wrapper[key] = m.group(0)
            return key
        s = re.sub(r'\b' + re.escape(term) + r'\b', repl, s, flags=re.IGNORECASE)

    # Apply term overrides for the target language
    s = _apply_term_overrides(s, target_lang_code)

    # Restore preserve wrappers to their original exact casing (they will be preserved through translation)
    for k, v in preserve_wrapper.items():
        s = s.replace(k, v)

    return s, protected_map

# If True, when the very first translation attempt for a text fails, use the original text
# immediately instead of performing multiple retries or fallbacks. Set by user preference.
FAST_FAIL_ON_FIRST = True

# Nastav pořadí jazyků, které chceš překládat (podle názvů v LANG_MAP)
LANG_ORDER = [
    'Chinese (Simplified)',
    'Czech',
    'French',
    'German',
    'Japanese',
    'Portuguese (Brazil)',
    'Russian',
    'Spanish',
    'Turkish',
    'Ukrainian',
]

# Small built-in translations for common short UI tokens (to avoid unstable remote parsing)
UI_FALLBACKS = {
    'NEW': {
        'Chinese (Simplified)': '新',
        'Czech': 'Nové',
        'French': 'Nouveau',
        'German': 'Neu',
        'Japanese': '新規',
        'Portuguese (Brazil)': 'Novo',
        'Russian': 'Новый',
        'Spanish': 'Nuevo',
        'Turkish': 'Yeni',
        'Ukrainian': 'Новий',
    },
    'READY': {
        'Chinese (Simplified)': '已准备',
        'Czech': 'Připraveno',
        'French': 'Prêt',
        'German': 'Bereit',
        'Japanese': '準備完了',
        'Portuguese (Brazil)': 'Pronto',
        'Russian': 'Готов',
        'Spanish': 'Listo',
        'Turkish': 'Hazır',
        'Ukrainian': 'Готово',
    },
    'SELECTED': {
        'Chinese (Simplified)': '已选择',
        'Czech': 'Vybráno',
        'French': 'Sélectionné',
        'German': 'Ausgewählt',
        'Japanese': '選択済み',
        'Portuguese (Brazil)': 'Selecionado',
        'Russian': 'Выбрано',
        'Spanish': 'Seleccionado',
        'Turkish': 'Seçildi',
        'Ukrainian': 'Вибрано',
    },
    'PLAYERS': {
        'Chinese (Simplified)': '玩家',
        'Czech': 'Hráči',
        'French': 'Joueurs',
        'German': 'Spieler',
        'Japanese': 'プレイヤー',
        'Portuguese (Brazil)': 'Jogadores',
        'Russian': 'Игроки',
        'Spanish': 'Jugadores',
        'Turkish': 'Oyuncular',
        'Ukrainian': 'Гравці',
    },
    'GENERATOR': {
        'Chinese (Simplified)': '生成器',
        'Czech': 'Generátor',
        'French': 'Générateur',
        'German': 'Generator',
        'Japanese': 'ジェネレーター',
        'Portuguese (Brazil)': 'Gerador',
        'Russian': 'Генератор',
        'Spanish': 'Generador',
        'Turkish': 'Jeneratör',
        'Ukrainian': 'Генератор',
    },
}

def get_ui_fallback(lang_name, text):
    key = re.sub(r"[^A-Za-z0-9]+", "", text).upper()
    return UI_FALLBACKS.get(key, {}).get(lang_name)

def format_hms(seconds: int) -> str:
    """Format seconds into Hh:Mm:Ss (e.g. 1h:2m:3s)"""
    try:
        s = int(max(0, int(seconds)))
    except Exception:
        s = 0
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}h:{m}m:{sec}s"

def process_file(input_path, output_path, lang_code, lang_name, total_batches_all, progress_counter):
    lines = []
    hashes = []
    # Detect already translated hashes in existing output (resume support)
    already_translated = set()
    if os.path.exists(output_path):
        try:
            with open(output_path, 'r', encoding='utf-8') as outf:
                for ol in outf:
                    ol = ol.strip()
                    if len(ol) == 32 and all(c in '0123456789ABCDEF' for c in ol.upper()):
                        already_translated.add(ol)
        except Exception:
            # if we cannot read the file for some reason, treat as empty
            already_translated = set()
    # Read input and skip already translated entries
    with open(input_path, "r", encoding="utf-8") as f:
        raw_lines = f.read().splitlines()

    # Detect if file uses PO-like blocks (msgctxt/msgid/msgstr) or old hash+text format
    is_po_like = any(l.strip().startswith('msgctxt') or l.strip().startswith('msgid') for l in raw_lines)
    if is_po_like:
        i = 0
        while i < len(raw_lines):
            ln = raw_lines[i].strip()
            if ln.startswith('msgctxt'):
                # extract hash from msgctxt "...,HASH" or msgctxt "HASH"
                m = re.match(r'msgctxt\s+"(.*)"', ln)
                cur_hash = None
                if m:
                    content = m.group(1)
                    # if content starts with comma, the hash follows the comma
                    if content.startswith(','):
                        cur_hash = content[1:]
                    else:
                        cur_hash = content
                # find the following msgid which is the original text
                orig = ''
                j = i + 1
                while j < len(raw_lines):
                    l2 = raw_lines[j].strip()
                    if l2.startswith('msgid'):
                        mm = re.match(r'msgid\s+"(.*)"', l2)
                        if mm:
                            orig = mm.group(1)
                        j += 1
                        break
                    j += 1
                i = j
                if cur_hash and cur_hash not in already_translated:
                    hashes.append(cur_hash)
                    # unescape literal escape sequences for translation (\n -> newline, etc.)
                    orig_unescaped = orig.replace('\\r\\n', '\r\n').replace('\\n', '\n').replace('\\r', '\r')
                    lines.append(orig_unescaped)
                continue
            elif ln.startswith('msgid'):
                # case: no msgctxt, maybe msgid/msgstr pairs without hashes
                mm = re.match(r'msgid\s+"(.*)"', ln)
                orig = mm.group(1) if mm else ''
                # no hash available; generate a pseudo-hash based on content
                import hashlib
                cur_hash = hashlib.md5(orig.encode('utf-8')).hexdigest().upper()
                if cur_hash not in already_translated:
                    hashes.append(cur_hash)
                    orig_unescaped = orig.replace('\\r\\n', '\r\n').replace('\\n', '\n').replace('\\r', '\r')
                    lines.append(orig_unescaped)
                i += 1
                continue
            else:
                i += 1
    else:
        # old hash + text format
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i].rstrip('\n')
            stripped = line.strip()
            # detect a hash line
            if stripped and len(stripped) == 32 and all(c in '0123456789ABCDEF' for c in stripped.upper()):
                cur_hash = stripped
                i += 1
                # collect subsequent lines until next hash line or EOF
                text_lines = []
                while i < len(raw_lines):
                    nxt = raw_lines[i]
                    nxt_stripped = nxt.strip()
                    if nxt_stripped and len(nxt_stripped) == 32 and all(c in '0123456789ABCDEF' for c in nxt_stripped.upper()):
                        # next hash starts here; don't consume it
                        break
                    # allow blank lines inside the text (preserve them)
                    text_lines.append(nxt)
                    i += 1

                # join preserved lines, strip trailing blank lines
                if text_lines:
                    text_block = '\n'.join(text_lines).strip('\n')
                else:
                    text_block = ''

                # skip if already translated
                if cur_hash in already_translated:
                    continue
                hashes.append(cur_hash)
                lines.append(text_block)
                continue
            i += 1
    total_batches = (len(lines) + batch_size - 1) // batch_size if lines else 0
    batch_times = []
    # Open output for appending so existing translations are preserved
    mode = 'a' if os.path.exists(output_path) else 'w'
    with open(output_path, mode, encoding="utf-8") as f:
        if already_translated:
            print(f"{os.path.basename(input_path)}: Nalezeno již přeložených {len(already_translated)} položek, budou přeskočeny.")
        for i in range(0, len(lines), batch_size):
            batch_start = time.time()
            batch_lines = lines[i:i+batch_size]
            batch_hashes = hashes[i:i+batch_size]
            translations = []
            for idx, text in enumerate(batch_lines):
                if len(text) == 1:
                    translations.append(text)
                    continue
                # default: no masks
                mask_map = None

                # Normalize and decode text for pattern matching so UE console commands
                # or literal tokens are reliably detected (handles leading/trailing spaces
                # and literal escape sequences like "\\r\\n").
                text_stripped = text.strip() if text is not None else ''

                def _decode_escaped_sequences_for_matching(s: str) -> str:
                    if s is None:
                        return ''
                    out = s
                    out = out.replace('\\r\\n', '\r\n')
                    out = out.replace('\\r', '\r')
                    out = out.replace('\\n', '\n')
                    return out

                text_decoded = _decode_escaped_sequences_for_matching(text_stripped)

                # Check patterns against both the raw stripped text and the decoded form
                matched_ue_pattern = any(
                    (pc.search(text_stripped) is not None) or (pc.search(text_decoded) is not None)
                    for pc in ue5_compiled
                )

                if matched_ue_pattern:
                    # Find all matches (spans) in the original text so we can decide whether
                    # the match covers the whole string or is an inline token to protect.
                    # We prefer positions in the original string to ensure exact-restoration.
                    matches = []
                    text_orig = text if text is not None else ''
                    for pc in ue5_compiled:
                        # try finditer in original text
                        for m in pc.finditer(text_orig):
                            matches.append((m.start(), m.end(), m.group(0)))
                        # fallback: if nothing found in original, try decoded and locate substring in original
                        if not any(pc.search(text_orig) for pc in [pc]):
                            for m in pc.finditer(text_decoded):
                                grp = m.group(0)
                                # locate grp in original text (first occurrence)
                                pos = text_orig.find(grp)
                                if pos != -1:
                                    matches.append((pos, pos + len(grp), grp))
                    # merge and sort matches
                    matches = sorted(matches, key=lambda x: (x[0], -x[1]))
                    # if any match spans the entire stripped text, skip translating the whole text
                    full_span = False
                    ts = text_stripped
                    if ts:
                        for a, b, grp in matches:
                            # decoded may include different newline chars; compare on stripped decoded
                            if a == 0 and b >= len(text_decoded.strip()):
                                full_span = True
                                break
                    if full_span:
                        translations.append(text)
                        continue

                    # Otherwise, mask the matched substrings with unique placeholders so the
                    # translator won't change them, then restore after translation.
                    mask_map = {}
                    masked = text_orig
                    # replace matches in reverse order to preserve indices
                    for idx_m, (a, b, grp) in enumerate(sorted(matches, key=lambda x: x[0], reverse=True)):
                        placeholder = f"__UE_TOKEN_{idx_m}__"
                        # use the exact substring from masked (a,b) to avoid mismatch
                        try:
                            orig_sub = masked[a:b]
                        except Exception:
                            orig_sub = grp
                        masked = masked[:a] + placeholder + masked[b:]
                        mask_map[placeholder] = orig_sub

                    # Use masked text for translation — decode literal escapes into real newlines
                    def _decode_escaped_sequences_for_translation(s: str) -> str:
                        # Convert literal escape sequences like "\\r\\n" or "\\r" into real newlines
                        if s is None:
                            return ''
                        out = s
                        # Replace \r\n first
                        out = out.replace('\\r\\n', '\r\n')
                        out = out.replace('\\r', '\r')
                        out = out.replace('\\n', '\n')
                        return out

                    text_for_translation = _decode_escaped_sequences_for_translation(masked)
                else:
                    # No masking required
                    def _decode_escaped_sequences_for_translation(s: str) -> str:
                        if s is None:
                            return ''
                        out = s
                        out = out.replace('\\r\\n', '\r\n')
                        out = out.replace('\\r', '\r')
                        out = out.replace('\\n', '\n')
                        return out

                    text_for_translation = _decode_escaped_sequences_for_translation(text)

                # Preprocess text for translation: apply spelling fixes, term overrides, and protect placeholders
                try:
                    processed, protected_map = preprocess_text_for_translation(text_for_translation, mask_map, lang_code)
                    text_for_translation = processed
                except Exception:
                    # If preprocessing fails, fall back to previous decoded text_for_translation
                    protected_map = {}

                # quick UI fallback for very short or common tokens
                ui_fb = get_ui_fallback(lang_name, text)
                if ui_fb is not None:
                    translations.append(ui_fb)
                    continue

                # Try translating with a limited number of retries and several strategies
                max_retries = 7
                attempt = 0
                backoff = 5
                translated_text = None
                while attempt < max_retries:
                    try:
                        # Try different strategies depending on attempt number
                        if attempt == 0:
                            # preferred: explicit source english
                            result = translator.translate(text_for_translation, src='en', dest=lang_code)
                        elif attempt == 1:
                            # try autodetect source
                            result = translator.translate(text_for_translation, dest=lang_code)
                        elif attempt == 2:
                            # try adding a trailing space / punctuation to avoid parser edge cases
                            result = translator.translate(text_for_translation + ' .', dest=lang_code)
                        elif attempt == 3:
                            # try with None src explicitly
                            result = translator.translate(text_for_translation, src=None, dest=lang_code)
                        elif attempt == 4:
                            # try simple batch call (some versions behave differently)
                            result = translator.translate([text_for_translation], dest=lang_code)
                            # when passing a list, result may be a list
                            if isinstance(result, list) and result:
                                res0 = result[0]
                                if getattr(res0, 'text', None):
                                    translated_text = res0.text
                                    break
                                else:
                                    raise ValueError('batch translator returned no text')
                            else:
                                raise ValueError('batch translator returned unexpected')
                        elif attempt == 5:
                            # try again with explicit english
                            result = translator.translate(text_for_translation, src='en', dest=lang_code)
                        else:
                            # attempt 6 (7th overall): try Gemini generative model
                            # call our Gemini fallback — requires GEMINI_API_KEY in env or local_secrets
                            gem = try_gemini_translate(text, lang_name, lang_code)
                            if gem is not None:
                                translated_text = gem
                                break
                            else:
                                raise ValueError('Gemini fallback returned None')

                        # Normalize result object
                        if result is None:
                            raise ValueError('translator returned None')
                        if isinstance(result, list):
                            # single-item list expected
                            if not result:
                                raise ValueError('translator returned empty list')
                            res = result[0]
                        else:
                            res = result

                        if not hasattr(res, 'text') or res.text is None:
                            raise ValueError('translator returned no text attribute')
                        translated_text = res.text
                        break
                    except Exception as e:
                        attempt += 1
                        print(f"Chyba při překladu: {text} (opakování {attempt}/{max_retries}) - {e}")
                        # log failure attempt
                        try:
                            res_repr = repr(locals().get('result', None))
                        except Exception:
                            res_repr = None
                        log_failure(lang_name, text, attempt, e, result_repr=res_repr)
                        # If configured, on the first failure just fall back to original text
                        if FAST_FAIL_ON_FIRST and attempt == 1:
                            print(f"FAST_FAIL_ON_FIRST enabled: používám originál pro: {text}")
                            translations.append(text)
                            # ensure we break out of the retry loop and outer handling
                            translated_text = text
                            break
                        # short backoff then exponential
                        time.sleep(backoff)
                        backoff = min(backoff * 2, 60)

                # If still None after these attempts, try Google Cloud Translate (if API key provided)
                if translated_text is None:
                    gct = try_google_cloud_translate(text, lang_code, lang_name=lang_name)
                    if gct is not None:
                        translated_text = gct
                        print(f"Používám Google Cloud Translate fallback pro: {text} -> {translated_text}")
                    else:
                        # log that GCT was attempted but not available/failed
                        if os.environ.get('GOOGLE_TRANSLATE_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
                            log_failure(lang_name, text, 'gct', Exception('Google Cloud Translate attempted but failed'), result_repr=None)

                # pokud se nepodařilo přeložit, zkúsíme UI fallback ještě jednou
                ui_fb2 = get_ui_fallback(lang_name, text)
                if ui_fb2 is not None:
                    print(f"Používám lokální překlad (UI fallback) pro: {text} -> {ui_fb2}")
                    translations.append(ui_fb2)
                else:
                    if translated_text is None:
                        print(f"Nepodařilo se přeložit po {max_retries} pokusech, použiji originál pro: {text}")
                        # log final failure
                        log_failure(lang_name, text, max_retries, Exception('max retries, fallback to original'), result_repr=repr(locals().get('result', None)))
                        translations.append(text)
                    else:
                        # If we used masking for UE tokens, restore protected placeholders and then original substrings
                        if translated_text is not None and mask_map:
                            try:
                                # first, restore any protected safe tokens back to original mask placeholders
                                for safe, orig_placeholder in (protected_map or {}).items():
                                    translated_text = translated_text.replace(safe, orig_placeholder)
                                # then, restore mask placeholders to their original substrings
                                for ph, orig_sub in mask_map.items():
                                    translated_text = translated_text.replace(ph, orig_sub)
                            except Exception:
                                # If restoring fails for any reason, fall back to untranslated original
                                log_failure(lang_name, text, 'restore', Exception('failed to restore UE tokens'), result_repr=None)
                                translations.append(text)
                                continue
                        translations.append(translated_text)
            def _escape_newlines_for_po(s: str) -> str:
                # Convert actual newlines into literal escape sequences suitable for PO/Unreal.
                if s is None:
                    return ''
                # Normalize CRLF first
                out = s.replace('\r\n', '\\r\\n')
                # Replace any remaining CR or LF with \r (Unreal often expects \r)
                out = out.replace('\r', '\\r')
                out = out.replace('\n', '\\r')
                return out

            def _escape_for_po_field(s: str) -> str:
                if s is None:
                    return ''
                # escape backslashes and double quotes
                out = s.replace('\\', '\\\\')
                out = out.replace('"', '\\"')
                # normalize CRLF first to literal escape sequences
                out = out.replace('\r\n', '\\r\\n')
                # then replace lone newlines with literal \n
                out = out.replace('\n', '\\n')
                out = out.replace('\r', '\\r')
                return out

            for h, orig, trans in zip(batch_hashes, batch_lines, translations):
                esc_trans = _escape_for_po_field(trans)
                esc_orig = _escape_for_po_field(orig)
                # write PO-like block with msgctxt, msgid (original), and msgstr (translation)
                f.write(f'msgctxt ",{h}"\n')
                f.write(f'msgid "{esc_orig}"\n')
                f.write(f'msgstr "{esc_trans}"\n\n')
            f.flush()
            batch_time = time.time() - batch_start
            batch_times.append(batch_time)
            # update global counters
            try:
                progress_counter['total_time'] += batch_time
                progress_counter['done'] += 1
            except Exception:
                pass
            # per-file averages
            avg_batch_time = sum(batch_times) / len(batch_times)
            avg_sleep = 3
            batches_done = (i // batch_size) + 1
            batches_left = total_batches - batches_done
            eta = batches_left * (avg_batch_time + avg_sleep)
            # overall averages and ETA
            done_overall = progress_counter.get('done', 0)
            total_time_overall = progress_counter.get('total_time', 0.0)
            global_avg = (total_time_overall / done_overall) if done_overall > 0 else avg_batch_time
            avg_inter_batch_sleep = 7.5
            batches_left_overall = max(total_batches_all - done_overall, 0)
            overall_eta = int(batches_left_overall * (global_avg + avg_inter_batch_sleep))
            # compute percentages safely
            try:
                per_pct = int((batches_done / total_batches) * 100) if total_batches > 0 else 100
            except Exception:
                per_pct = 0
            try:
                overall_pct = int((done_overall / total_batches_all) * 100) if total_batches_all > 0 else 100
            except Exception:
                overall_pct = 0
            print(f"{os.path.basename(input_path)}: Zpracováno dávek: {batches_done}/{total_batches} - {per_pct}% (ETA: {format_hms(int(eta))}) — Celkem dokončeno: {done_overall}/{total_batches_all} - {overall_pct}%, zbývá {batches_left_overall} dávek (ETA celkem: {format_hms(overall_eta)})")
            if i + batch_size < len(lines):
                # Delay between batches: random between 5 and 10 seconds
                time.sleep(random.uniform(5, 10))
    print(f"{os.path.basename(input_path)}: Hotovo! Přeloženo {len(lines)} řádků po dávkách.")

def get_user_lang_order():
    # Build a mapping from normalized filename stem -> actual filename
    files = os.listdir(input_dir)
    stem_to_filename = {}
    for fn in files:
        if not fn.lower().endswith('_to_translate.txt'):
            continue
        stem = fn[:-len('_to_translate.txt')].strip()
        stem_to_filename[stem.lower()] = fn

    # Some files may have minor typos or different casing (e.g., 'czech' or 'Portugase (Brazil)')
    # Create simple aliases to map common variants to LANG_MAP keys
    aliases = {
        'czech': 'Czech',
        'czech ': 'Czech',
        'chinese (simplified)': 'Chinese (Simplified)',
        'portugase (brazil)': 'Portuguese (Brazil)',
        'portugese (brazil)': 'Portuguese (Brazil)',
        'portuguese (brazil)': 'Portuguese (Brazil)',
        'portuguese': 'Portuguese (Brazil)'
    }

    available = []
    # First, try to match LANG_MAP keys against found files (case-insensitive)
    for lang_name in LANG_MAP:
        key = lang_name.lower()
        if key in stem_to_filename:
            available.append(lang_name)
        else:
            # check aliases
            for alias_stem, alias_name in aliases.items():
                if alias_name == lang_name and alias_stem in stem_to_filename:
                    available.append(lang_name)
                    break

    # Also include any remaining stems that look like language names but not in LANG_MAP
    for stem_lower, fn in stem_to_filename.items():
        if stem_lower in aliases:
            # already handled via alias mapping
            continue
        # try simple title-casing and see if that matches a LANG_MAP key
        candidate = stem_lower.title()
        # special-case parentheses which title() won't convert properly
        candidate = candidate.replace('To_Translate', '').strip()
        if candidate in LANG_MAP and candidate not in available:
            available.append(candidate)
    print("Dostupné jazyky k překladu:")
    for idx, lang in enumerate(available, 1):
        print(f"{idx}. {lang}")
    print("Zadej pořadí jazyků jako čísla oddělená čárkou (např. 2,1,3). Zadej 0 pro 'všechny' (např. 2,0,1 => 2, pak všechny ostatní, pak 1):")
    order = input().strip()

    def parse_language_order(order_str: str, available_list: list) -> list:
        """Parse user input like '2,1,3' or '2,0,1' where 0 means 'insert all remaining languages here'.
        Returns an ordered list of language names taken from available_list. Duplicates are ignored, and invalid
        indices are skipped. If parsing fails or input is empty, returns available_list.
        """
        if not order_str:
            return available_list
        parts = [p.strip() for p in order_str.split(',') if p.strip()]
        result = []
        used = set()
        # helper to append by index (1-based in user input)
        def append_index(idx1):
            try:
                i = int(idx1) - 1
            except Exception:
                return
            if 0 <= i < len(available_list):
                lang = available_list[i]
                if lang not in used:
                    result.append(lang)
                    used.add(lang)

        for part in parts:
            # special token '0' means append all remaining languages at this point
            if part == '0':
                for lang in available_list:
                    if lang not in used:
                        result.append(lang)
                        used.add(lang)
                # once 0 is processed, any subsequent numeric entries are still allowed but will be ignored if duplicate
                continue
            # otherwise try to treat as an index
            if part.isdigit():
                append_index(part)
                continue
            # ignore non-digits
        # if nothing selected, fall back to full available list
        if not result:
            return available_list
        return result

    try:
        ordered = parse_language_order(order, available)
        return ordered
    except Exception:
        print("Chyba ve vstupu, použije se výchozí pořadí.")
        return available

def main():
    # Interaktivní výběr pořadí jazyků
    global LANG_ORDER
    LANG_ORDER = get_user_lang_order()
    # Prevent the system from sleeping while we run translations (Windows only)
    prevent_sleep()

    # Vytvoř seznam souborů podle zvoleného pořadí (robustní match)
    def _normalize(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower() if s else '')

    ordered_files = []
    existing_files = os.listdir(input_dir)
    # build normalized stem -> filename map for files that look like *_to_translate.txt
    stem_map = {}
    for fn in existing_files:
        if not fn.lower().endswith('_to_translate.txt'):
            continue
        stem = fn[:-len('_to_translate.txt')].strip()
        stem_norm = _normalize(stem)
        stem_map[stem_norm] = fn

    for lang_name in LANG_ORDER:
        lang_norm = _normalize(lang_name)
        if not lang_norm:
            continue
        # direct normalized match
        if lang_norm in stem_map:
            ordered_files.append((lang_name, stem_map[lang_norm]))
            continue
        # partial or contained match (handles minor typos/spacing)
        matched = None
        for stem_norm, fn in stem_map.items():
            if lang_norm in stem_norm or stem_norm in lang_norm:
                matched = fn
                break
        if matched:
            ordered_files.append((lang_name, matched))
            continue
        # fallback: try matching by starting substring of filename (without normalization)
        for fn in existing_files:
            if fn.lower().startswith(lang_name.lower()) or lang_name.lower() in fn.lower():
                ordered_files.append((lang_name, fn))
                matched = fn
                break
        if matched:
            continue
        if not matched:
            # Try fuzzy match against normalized stems (handles small typos like 'Portugase')
            try:
                close = difflib.get_close_matches(lang_norm, list(stem_map.keys()), n=1, cutoff=0.6)
                if close:
                    matched_fn = stem_map.get(close[0])
                    if matched_fn:
                        ordered_files.append((lang_name, matched_fn))
                        continue
            except Exception:
                pass
            print(f"Varování: nenalezen vstupní soubor pro '{lang_name}', bude přeskočeno.")

    # Compute total batches across all files (subtract already translated items in outputs)
    total_batches_all = 0
    for lang_name, filename in ordered_files:
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, f"{lang_name}_translated.txt")
        # read already translated hashes from output (if exists)
        already_translated = set()
        if os.path.exists(output_path):
            try:
                with open(output_path, 'r', encoding='utf-8') as outf:
                    for ol in outf:
                        ol = ol.strip()
                        if len(ol) == 32 and all(c in '0123456789ABCDEF' for c in ol.upper()):
                            already_translated.add(ol)
            except Exception:
                already_translated = set()
        # count lines/hash pairs that still need translation (skip those in already_translated)
        try:
            with open(input_path, 'r', encoding='utf-8') as inf:
                data = inf.read().splitlines()
            # detect PO-like blocks (msgctxt/msgid/msgstr)
            has_msgctxt = any(l.strip().startswith('msgctxt') for l in data)
            count = 0
            if has_msgctxt:
                i2 = 0
                while i2 < len(data):
                    ln = data[i2].strip()
                    if ln.startswith('msgctxt'):
                        # extract hash from between quotes
                        m = re.match(r'msgctxt\s+"(.*)"', ln)
                        h = None
                        if m:
                            content = m.group(1)
                            if content.startswith(','):
                                h = content[1:]
                            else:
                                h = content
                        # find next msgid
                        j = i2 + 1
                        msgid = None
                        while j < len(data):
                            ln2 = data[j].strip()
                            if ln2.startswith('msgid'):
                                mm = re.match(r'msgid\s+"(.*)"', ln2)
                                if mm:
                                    msgid = mm.group(1)
                                break
                            j += 1
                        if h and (h not in already_translated):
                            count += 1
                        i2 = j + 1
                    else:
                        i2 += 1
            else:
                # fallback: old hash newline + text format
                cur_hash = None
                for line in data:
                    line = line.strip()
                    if not line:
                        continue
                    if len(line) == 32 and all(c in '0123456789ABCDEF' for c in line.upper()):
                        cur_hash = line
                        continue
                    if cur_hash:
                        if cur_hash not in already_translated:
                            count += 1
                        cur_hash = None
        except Exception:
            count = 0
        total_batches_all += (count + batch_size - 1) // batch_size

    # shared progress counter
    progress_counter = {'done': 0, 'total_time': 0.0}

    for lang_name, filename in ordered_files:
        lang_code = LANG_MAP.get(lang_name)
        if not lang_code:
            print(f"Jazyk '{lang_name}' není v mapování LANG_MAP, přeskočeno.")
            continue
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, f"{lang_name}_translated.txt")
        print(f"Překládám {filename} do {lang_code}...")
        process_file(input_path, output_path, lang_code, lang_name, total_batches_all, progress_counter)


if __name__ == '__main__':
    main()