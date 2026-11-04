"""Tracks every published Short so the channel never repeats a topic, title, or script."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HISTORY_PATH = Path(os.environ.get("HISTORY_FILE", "content_history.json"))
_STOP = {"the", "a", "an", "of", "to", "and", "in", "on", "is", "are", "your", "you", "why", "how", "what", "this", "that", "it", "for", "with"}


def load():
    if not HISTORY_PATH.exists():
        return {"videos": []}
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{HISTORY_PATH} is not valid JSON ({e}). Fix or reset it to {{\"videos\": []}}.") from e
    if not isinstance(data, dict) or not isinstance(data.get("videos"), list):
        raise RuntimeError(f"{HISTORY_PATH} must look like {{\"videos\": [...]}}.")
    return data


def save(data):
    # Write to a temp file first so a crash never leaves a half-written history file.
    fd, tmp = tempfile.mkstemp(dir=str(HISTORY_PATH.resolve().parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, HISTORY_PATH)


def _tokens(title):
    return {w for w in re.findall(r"[a-z0-9]+", str(title).lower()) if w not in _STOP}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60]


def script_hash(data):
    narration = " ".join(s.get("text", "") if isinstance(s, dict) else str(s) for s in data.get("scenes", []))
    return hashlib.sha256(re.sub(r"\W+", " ", narration.lower()).strip().encode("utf-8")).hexdigest()


def find_duplicate(data, entries=None):
    """Return a human-readable reason if this script repeats an earlier one, else None."""
    entries = load()["videos"] if entries is None else entries
    h = script_hash(data)
    topic = slugify(data.get("topic", ""))
    title_tokens = _tokens(data.get("title", ""))
    for e in entries:
        if e.get("script_sha256") == h:
            return f"identical narration already published ({e.get('title')!r})"
        if topic and slugify(e.get("topic", "")) == topic:
            return f"topic {topic!r} already published ({e.get('title')!r})"
        other = _tokens(e.get("title", ""))
        if title_tokens and other:
            overlap = len(title_tokens & other) / len(title_tokens | other)
            if overlap >= 0.6:
                return f"title too similar to {e.get('title')!r}"
    return None


def used_topics(entries=None):
    entries = load()["videos"] if entries is None else entries
    return {slugify(e.get("topic", "")) for e in entries if e.get("topic")}


def record(entry):
    data = load()
    data["videos"].append(entry)
    save(data)
