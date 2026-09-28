"""Generate every UI language from English.

English is the only thing anyone edits:
  - frontend/public/locales/en/translation.json   interface text
  - frontend/src/data/statutes.json                library document titles
    (written to en/documents.json by this script)

This script translates whatever is new, changed or still untranslated into the
ten Indic locales with the project's LLM, checks every result, and writes the
files in the same key order as English. A translation is rejected, and asked
for again with the reason, if it:
  - drops or alters a {{placeholder}},
  - leaves any Latin letters or 0-9 digits outside placeholders,
  - isn't written in the target script, or is implausibly long.

A lock file records a hash of the English each translation was made from, so
editing one English sentence retranslates just that sentence.

    python scripts/translate_locales.py              # translate what's needed
    python scripts/translate_locales.py --check      # report only; exit 1 if anything is out of date
    python scripts/translate_locales.py --lang hi,bn # limit to some languages
    python scripts/translate_locales.py --force      # retranslate everything

Standard library only. Talks to Ollama at OLLAMA_LLM_BASE_URL
(default http://localhost:11434) with LLM_MODEL (default gemma4:31b-cloud).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "frontend/public/locales"
STATUTES = ROOT / "frontend/src/data/statutes.json"
LOCK = ROOT / "frontend/locales.lock.json"

# code: (language name, first codepoint of its Unicode block, how "Vidhi" is written)
LANGS = {
    "hi": ("Hindi", 0x0900, "विधि"),
    "bn": ("Bengali", 0x0980, "বিধি"),
    "pa": ("Punjabi (Gurmukhi script)", 0x0A00, "ਵਿਧੀ"),
    "gu": ("Gujarati", 0x0A80, "વિધિ"),
    "mr": ("Marathi", 0x0900, "विधी"),
    "ta": ("Tamil", 0x0B80, "விதி"),
    "te": ("Telugu", 0x0C00, "విధి"),
    "kn": ("Kannada", 0x0C80, "ವಿಧಿ"),
    "ml": ("Malayalam", 0x0D00, "വിധി"),
    "or": ("Odia", 0x0B00, "ବିଧି"),
}

BATCH = 30
PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")

COMMON_RULES = """Write every word in {language} script. That includes the product name, which is always written "{brand}"; abbreviations such as FIR, RTI, RERA, PDF or NALSA; and names such as Google, Ollama Cloud, Vercel or Tailscale. Write those the way {language} newspapers and government websites spell them. Write every number with {language} digits ({digits}), keeping commas and decimal points where the English has them. The only text to copy unchanged is anything inside double curly braces, such as {{{{name}}}}.

The input is a JSON object of key -> English text. Reply with a JSON object with exactly the same keys, each mapped to its {language} version. No comments, no extra keys."""

PROMPTS = {
    "translation": """You are translating the interface of {brand}, a free website that explains Indian law in plain language, from English into {language}.

Write the way a careful, friendly person speaks {language} today: clear everyday words that a non-lawyer understands, the respectful "you" form, and natural sentence order. Avoid stiff or archaic vocabulary. For legal ideas (a section of an act, a source, a court, a complaint, a right) use the standard {language} terms found on Indian government and news websites. Name Indian acts by their official {language} titles where they exist. Match the length and tone of the English; short labels stay short.

""" + COMMON_RULES,
    "documents": """You are translating the titles of Indian legal documents (acts, rules, regulations, notifications, government guidelines and court judgments) from English into {language}, for a library page.

Use the official {language} title of an act or rule where one exists, as published by the Government of India. Otherwise translate the title faithfully and formally. For court judgments ("X vs State of Y 2010"), transliterate the party names and translate "vs" and "State of". Keep years and dates, written in {language} digits. Keep each title a title: no explanations.

""" + COMMON_RULES,
}


# ── JSON helpers ──────────────────────────────────────────────────────────


def flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def unflatten_like(template: dict, values: dict[str, str], prefix: str = "") -> dict:
    """Rebuild a nested dict in the template's key order, skipping missing keys."""
    out = {}
    for key, value in template.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            child = unflatten_like(value, values, path)
            if child:
                out[key] = child
        elif path in values:
            out[key] = values[path]
    return out


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def document_key(filename: str) -> str:
    # Must match docKey() in frontend/src/lib/documents.js.
    return re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"(\.pdf)?\.txt$", "", filename, flags=re.I))


def build_documents_source() -> dict:
    """en/documents.json: one entry per library document, keyed by file name."""
    docs = sorted(json.loads(STATUTES.read_text(encoding="utf-8")), key=lambda d: d["title"])
    tree = {document_key(d["filename"]): d["title"] for d in docs}
    save(LOCALES / "en/documents.json", tree)
    return tree


# ── Validation ────────────────────────────────────────────────────────────


def problem(english: str, translated, code: str) -> str | None:
    """Why a translation can't be used, or None if it's fine."""
    if not isinstance(translated, str) or not translated.strip():
        return "it was empty"
    if sorted(PLACEHOLDER.findall(english)) != sorted(PLACEHOLDER.findall(translated)):
        return "the {{placeholders}} were changed; copy them exactly"
    outside = PLACEHOLDER.sub("", translated)
    latin = re.findall(r"[A-Za-z]+", outside)
    if latin:
        return f"it still contains Latin letters ({', '.join(sorted(set(latin))[:5])}); write them in the target script"
    if re.search(r"[0-9]", outside):
        return "it contains 0-9 digits; use the target script's digits"
    start = LANGS[code][1]
    if re.search(r"[A-Za-z]", PLACEHOLDER.sub("", english)) and not any(start <= ord(c) < start + 128 for c in outside):
        return "it isn't written in the target script"
    if len(translated) > max(40, len(english) * 4):
        return "it is far longer than the English"
    return None


# ── Model ─────────────────────────────────────────────────────────────────


def ask_model(prompt: str, base_url: str, model: str) -> dict:
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "format": "json",
            # Cap the reply: in JSON mode a model occasionally runs on forever.
            "options": {"temperature": 0.2, "num_predict": 6000},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    request = urllib.request.Request(f"{base_url}/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=150) as response:
        content = json.load(response)["message"]["content"]
    start = content.find("{")
    if start < 0:
        return {}
    # raw_decode stops at the end of the first object, so a reply that
    # repeats itself ("{...}\n{...}") still parses.
    obj, _ = json.JSONDecoder().raw_decode(content[start:])
    return obj if isinstance(obj, dict) else {}


def translate(ns: str, code: str, todo: dict[str, str], base_url: str, model: str) -> tuple[dict, dict]:
    language, block, brand = LANGS[code]
    digits = "".join(chr(block + 0x66 + i) for i in range(10))
    template = PROMPTS[ns].format(language=language, brand=brand, digits=digits)
    done, failed = {}, {}

    last: dict[str, str] = {}

    def attempt(items: dict[str, str], note: str = "") -> dict[str, str]:
        prompt = template
        if note:
            prompt += f"\n\nA previous attempt was rejected because {note}. Fix that."
        prompt += "\n\n" + json.dumps(items, ensure_ascii=False, indent=1)
        try:
            result = ask_model(prompt, base_url, model)
        except Exception as exc:  # network, timeout, bad JSON
            return {k: f"the request failed ({exc})" for k in items}
        errors = {}
        for k in items:
            if isinstance(result.get(k), str):
                last[k] = result[k].strip()
            issue = problem(todo[k], result.get(k), code)
            if issue:
                errors[k] = issue
            else:
                done[k] = result[k].strip()
        return errors

    def respell(k: str) -> str | None:
        """Last resort for a translation that is fine apart from a few English
        words the model keeps (FIR, PDF, Google): ask only for their spellings
        in the target script and substitute them."""
        text = last.get(k)
        if not text:
            return "no usable translation came back"
        words = sorted(set(re.findall(r"[A-Za-z][A-Za-z.'-]*", PLACEHOLDER.sub("", text))), key=len, reverse=True)
        if not words:
            return problem(todo[k], text, code)
        prompt = (
            f"Write each of these English words or names in {language} script, the way {language} "
            f"newspapers spell them. Reply with a JSON object mapping each word to its spelling, "
            f"using no Latin letters.\n\n" + json.dumps(words, ensure_ascii=False)
        )
        try:
            spellings = ask_model(prompt, base_url, model)
        except Exception as exc:
            return f"the request failed ({exc})"
        for word in words:
            spelled = spellings.get(word)
            if isinstance(spelled, str) and spelled.strip() and not re.search(r"[A-Za-z]", spelled):
                text = re.sub(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", spelled.strip(), text)
        issue = problem(todo[k], text, code)
        if not issue:
            done[k] = text
        return issue

    keys = list(todo)
    for start in range(0, len(keys), BATCH):
        errors = attempt({k: todo[k] for k in keys[start : start + BATCH]})
        # Retry each rejected string alone, telling the model what was wrong.
        for k, issue in errors.items():
            for _ in range(2):
                issue = attempt({k: todo[k]}, issue).get(k)
                if not issue:
                    break
            if issue and "Latin letters" in issue:
                issue = respell(k)
            if issue:
                failed[k] = issue
        print(f"  {code}/{ns}: {min(start + BATCH, len(keys))}/{len(keys)}", flush=True)
    return done, failed


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report only; exit 1 if any locale is out of date")
    parser.add_argument("--lang", help="comma-separated language codes (default: all)")
    parser.add_argument("--force", action="store_true", help="retranslate every string")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gemma4:31b-cloud"))
    parser.add_argument("--base-url", default=os.environ.get("OLLAMA_LLM_BASE_URL", "http://localhost:11434"))
    args = parser.parse_args()

    codes = args.lang.split(",") if args.lang else list(LANGS)
    unknown = [c for c in codes if c not in LANGS]
    if unknown:
        parser.error(f"unknown language code(s): {', '.join(unknown)}")

    sources = {
        "translation": load(LOCALES / "en/translation.json"),
        "documents": build_documents_source(),
    }
    lock = load(LOCK)
    if lock and not all(ns in sources for ns in lock):
        lock = {}  # older single-namespace format

    plan = {}
    for ns, tree in sources.items():
        english = flatten(tree)
        hashes = {k: digest(v) for k, v in english.items()}
        for code in codes:
            current = flatten(load(LOCALES / code / f"{ns}.json"))
            made_from = lock.get(ns, {}).get(code, {})
            todo = {k: v for k, v in english.items() if args.force or k not in current or made_from.get(k) != hashes[k]}
            extra = [k for k in current if k not in english]
            plan[(ns, code)] = (tree, english, hashes, current, todo, extra)
            print(f"{code}/{ns}: {len(todo)} to translate, {len(extra)} obsolete")

    if args.check:
        return 1 if any(p[4] or p[5] for p in plan.values()) else 0

    def run(job):
        ns, code = job
        tree, english, hashes, current, todo, _ = plan[job]
        done, failed = translate(ns, code, todo, args.base_url, args.model) if todo else ({}, {})
        values = {k: v for k, v in current.items() if k in english and k not in todo}
        values.update(done)
        save(LOCALES / code / f"{ns}.json", unflatten_like(tree, values))
        lock.setdefault(ns, {})[code] = {k: hashes[k] for k in values}
        return job, failed

    failures = {}
    jobs = [job for job, p in plan.items() if p[4] or p[5]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for job, failed in pool.map(run, jobs):
            if failed:
                failures[job] = failed

    save(LOCK, {ns: {c: lock[ns][c] for c in sorted(lock[ns])} for ns in sorted(lock)})

    if failures:
        print("\nLeft in English (the app falls back to English for these):")
        for (ns, code), failed in failures.items():
            for key, why in failed.items():
                print(f"  {code}/{ns} {key}: {why}")
        return 1
    print("\nAll locales up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
