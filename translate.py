
"""
translate.py — simple interactive REPL to chat with gemini-2.5-flash

Usage: python translate.py

The script will try to find a GEMINI API key in environment variables or
`local_secrets.json`. If none is found, it will prompt you to paste one and
optionally save it.

It prefers the `google.genai` Python client if installed; otherwise it falls
back to a minimal REST call to the Generative API.
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SECRETS_PATH = BASE / 'local_secrets.json'

# helpers
def load_local_secrets():
    if SECRETS_PATH.exists():
        try:
            return json.loads(SECRETS_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def save_local_secrets(d):
    try:
        with open(SECRETS_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

def discover_key():
    # env
    for k, v in os.environ.items():
        if 'GEMINI' in k.upper() and v:
            return v
    # local secrets
    ls = load_local_secrets()
    for k, v in ls.items():
        if 'gemini' in k.lower() and v:
            return v
    return None

def rest_call(prompt, api_key, model='gemini-2.5-flash'):
    import urllib.request, urllib.parse, urllib.error
    base_host = 'https://generative.googleapis.com'
    # Try the v1 endpoint first, then fall back to v1beta2 for older projects
    paths = [f'/v1/models/{model}:generate', f'/v1beta2/models/{model}:generate']
    is_api_key = isinstance(api_key, str) and api_key.startswith('AIza')
    body = {'prompt': {'text': prompt}, 'maxOutputTokens': 512, 'temperature': 0.2}
    data = json.dumps(body).encode('utf-8')
    last_err = None
    for path in paths:
        try:
            if is_api_key:
                url = base_host + path + '?key=' + urllib.parse.quote(api_key, safe='')
                headers = {'Content-Type': 'application/json'}
            else:
                url = base_host + path
                headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as he:
            try:
                resp_body = he.read().decode('utf-8')
            except Exception:
                resp_body = None
            last_err = Exception(f'HTTP {he.code} {he.reason} for path {path}: {resp_body or he}')
            # try next path
            continue
        except Exception as e:
            last_err = e
            continue
    # if we reach here, all endpoints failed
    if last_err:
        raise last_err
    raise Exception('REST call failed for unknown reasons')

def call_model(prompt, api_key, model='gemini-2.5-flash'):
    # prefer genai client
    try:
        from google import genai
    except Exception:
        genai = None

    if genai is not None:
        # allow the client to pick up the api key via env
        prev = os.environ.get('GENAI_API_KEY')
        if api_key:
            os.environ['GENAI_API_KEY'] = api_key
        try:
            client = genai.Client()
            resp = client.models.generate_content(model=model, contents=prompt)
            if hasattr(resp, 'text') and resp.text:
                return resp.text
            if hasattr(resp, 'response') and isinstance(resp.response, str):
                return resp.response
            try:
                j = dict(resp)
                for k in ('text', 'response', 'content'):
                    if k in j and isinstance(j[k], str):
                        return j[k]
            except Exception:
                pass
        finally:
            if prev is None:
                os.environ.pop('GENAI_API_KEY', None)
            else:
                os.environ['GENAI_API_KEY'] = prev
    # fallback to REST
    parsed = rest_call(prompt, api_key, model=model)
    # try extracting text
    cand = parsed.get('candidates') or parsed.get('outputs') or parsed.get('output') or parsed.get('responses')
    if isinstance(cand, list) and cand:
        first = cand[0]
        if isinstance(first, dict):
            content = first.get('content') or first.get('text')
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and 'text' in item:
                        return item['text']
                if all(isinstance(x, str) for x in content):
                    return '\n'.join(content)
            elif isinstance(content, str):
                return content
    if 'text' in parsed and isinstance(parsed['text'], str):
        return parsed['text']
    return str(parsed)

def list_available_models(api_key):
    """Try to list available models for diagnostics (genai client preferred)."""
    out = {}
    try:
        from google import genai
    except Exception:
        genai = None
    if genai is not None:
        try:
            client = genai.Client()
            # try a few ways the client might expose listing
            if hasattr(client, 'list_models'):
                m = client.list_models()
                out['client_models'] = m
                return out
            if hasattr(client, 'models') and hasattr(client.models, 'list'):
                m = client.models.list()
                out['client_models'] = m
                return out
        except Exception as e:
            out['client_error'] = str(e)
    # REST fallback: try GET /v1/models
    try:
        import urllib.request, urllib.parse
        base = 'https://generative.googleapis.com'
        url = base + '/v1/models'
        if isinstance(api_key, str) and api_key.startswith('AIza'):
            url = url + '?key=' + urllib.parse.quote(api_key, safe='')
            req = urllib.request.Request(url, headers={'Content-Type':'application/json'})
        else:
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {api_key}'} )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode('utf-8')
            out['rest_models'] = json.loads(body)
            return out
    except Exception as e:
        out['rest_error'] = str(e)
    return out

def main():
    print('translate.py — interactive Gemini REPL. Type /exit to quit, /save to save key.')
    api_key = discover_key()
    if not api_key:
        print('No GEMINI key found. You can paste one now or press Enter to use interactive prompt each run.')
        v = input('Paste GEMINI API key (or leave blank): ').strip()
        if v:
            api_key = v
            print('Save key to local_secrets.json? (y/N)')
            ok = input().strip().lower()
            if ok == 'y':
                ls = load_local_secrets()
                ls['GEMINI_API_KEY'] = api_key
                if save_local_secrets(ls):
                    print('Saved key.')
                else:
                    print('Failed to save key.')
        # Default desired model
        model = 'gemini-2.5-flash'

        # Try to detect available models for this key/project and auto-select a gemini model if present
        if api_key:
            try:
                diag = list_available_models(api_key)
                # look for client_models or rest_models entries
                candidates = []
                if 'client_models' in diag and diag['client_models']:
                    # client_models might be many shapes; try extracting names
                    cm = diag['client_models']
                    # if it's a list-like
                    try:
                        for item in cm:
                            if isinstance(item, dict):
                                for k in ('name', 'id', 'model', 'displayName'):
                                    if k in item and isinstance(item[k], str):
                                        candidates.append(item[k])
                            elif isinstance(item, str):
                                candidates.append(item)
                    except Exception:
                        pass
                if 'rest_models' in diag and diag['rest_models']:
                    try:
                        rm = diag['rest_models']
                        # common structure: {'models': [{'name': 'models/gemini-2.1', ...}, ...]}
                        if isinstance(rm, dict) and 'models' in rm and isinstance(rm['models'], list):
                            for m in rm['models']:
                                if isinstance(m, dict) and 'name' in m:
                                    candidates.append(m['name'])
                        else:
                            # other shapes
                            if isinstance(rm, list):
                                for x in rm:
                                    if isinstance(x, str):
                                        candidates.append(x)
                    except Exception:
                        pass

                # Normalize candidate names and find gemini matches
                gemini_found = None
                for c in candidates:
                    if not c:
                        continue
                    s = str(c)
                    # if form 'models/gemini-2.1' extract last segment
                    if '/' in s:
                        s_last = s.split('/')[-1]
                    else:
                        s_last = s
                    if 'gemini' in s_last.lower():
                        gemini_found = s_last
                        break

                if gemini_found and gemini_found != model:
                    print(f"Note: requested model '{model}' not necessarily available; auto-selecting available model '{gemini_found}' for this key/project.")
                    model = gemini_found
                else:
                    # If listing failed or no gemini model found, print short guidance
                    if not candidates:
                        print('\nWarning: Could not list models for this API key (server returned 404).')
                        print('This commonly means the Generative API is not enabled for the Google Cloud project tied to your key, or the key lacks access to Gemini models.')
                        print('Please ensure:')
                        print('- Generative AI (or Vertex AI Generative) API is enabled in the Google Cloud project for this key')
                        print("- The key belongs to the project with billing enabled and has appropriate permissions")
                        print("- If you expect a model name other than 'gemini-2.5-flash', check available models with the official client or in the Cloud Console")
                        print('Continuing with default model name; if it fails, try running the script again after enabling the API or using a different key.')
            except Exception as e:
                print('Failed to detect available models:', e)
                print('Continuing with default model name; you can try /save to store a different key or enable the Generative API in your project.')
    while True:
        try:
            prompt = input('\nYou: ')
        except EOFError:
            print('\nExiting.')
            break
        if not prompt:
            continue
        if prompt.strip().lower() in ('/exit', '/quit'):
            print('Bye.')
            break
        if prompt.strip().lower() == '/save':
            if api_key:
                ls = load_local_secrets()
                ls['GEMINI_API_KEY'] = api_key
                if save_local_secrets(ls):
                    print('Saved key to local_secrets.json')
                else:
                    print('Failed to save')
            else:
                print('No key to save')
            continue
        if not api_key:
            print('No API key available; cannot send request. Use /exit or paste a key.')
            continue
        print('Sending...')
        try:
            resp = call_model(prompt, api_key, model=model)
        except Exception as e:
            print('Error from model call:', e)
            print('\nAttempting to list available models for diagnostics...')
            try:
                diag = list_available_models(api_key)
                print('Diagnostics:')
                print(json.dumps(diag, indent=2, ensure_ascii=False))
            except Exception as e2:
                print('Failed to list models for diagnostics:', e2)
            continue
        print('\nGemini:', resp)

if __name__ == '__main__':
    main()
