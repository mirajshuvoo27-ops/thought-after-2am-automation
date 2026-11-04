#!/usr/bin/env python3
"""Generate the daily Thought After 2AM script(s) with the Anthropic API.

Usage:
    python generate_script.py --slot morning        # writes video_morning.json
    python generate_script.py --slot evening        # writes video_evening.json
    python generate_script.py --slot both           # writes both (second avoids the first)

Requires the ANTHROPIC_API_KEY environment variable (a GitHub Secret in the workflow).
Topic order: vetted entries in topics_bank.json first, then topics chosen by Claude under strict accuracy rules.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import history

DEFAULT_MODEL = "claude-sonnet-5-5"
MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
BANK_PATH = Path("topics_bank.json")
MAX_ATTEMPTS = 3
VALID_SLOTS = ("morning", "evening")

MIN_WORDS, MAX_WORDS = 80, 112          # ~30-40 s at the channel's narration pace
MIN_SCENES, MAX_SCENES = 6, 10
MAX_HOOK_WORDS = 14
MAX_SCENE_WORDS = 30
BANNED = re.compile(r"\b(cures?|cured|guarantee[ds]?|prov(?:e[sd]?|en|ing)|miracle|shocking|doctors hate)\b|100\s?%", re.I)

SLOT_STYLE = {
    "morning": "Morning slot: curious, upbeat, a surprising fact to start someone's day.",
    "evening": "Evening slot: calm, reflective, a late-night 'thought after 2AM' feel (never scary or alarming).",
}

SYSTEM_PROMPT = """You write scripts for "Thought After 2AM", a YouTube Shorts channel about psychology, brain facts, science, and mysteries, for English-speaking viewers in the USA.
Reply with ONE JSON object and nothing else: no markdown fences, no commentary.

ACCURACY RULES (most important):
- State only facts that are well established in peer-reviewed research or standard reference works. If something is debated or unknown, say so plainly ("scientists aren't sure").
- Never invent studies, statistics, quotes, names, or dates. If you are not certain of a number, leave the number out and describe the finding in general terms.
- Use careful wording for small or correlational studies ("in one study", "researchers found", "can", "tends to").
- Do not use the words: prove, proved, proves, proven, guaranteed, cure, miracle, shocking.
- No medical, diagnostic, or treatment advice. No supplements or drugs.
- No myths (10% of the brain, left-brain/right-brain types, learning styles, etc.).
- Only name a study or researcher in the narration if you are certain it is correct.

STYLE RULES:
- Simple, natural American English meant to be spoken aloud: short sentences, contractions are fine, explain any technical word in the same sentence.
- Scene 1 is the hook: at most 12 words, grabs attention in the first 2 seconds, and is true.
- Total narration: 85 to 105 words (about 30-40 seconds). 7 to 9 scenes, each 1-2 short sentences (max 22 words).
- The last scene is a calm takeaway or a question for the viewer. No "like and subscribe".
- Narration text is plain words only: no emojis, hashtags, stage directions, markdown, or parentheses.

JSON SCHEMA:
{
  "topic": "short-kebab-case-id",
  "title": "Under 70 characters, specific, no false promises",
  "summary": "1-2 plain sentences describing the video for the YouTube description",
  "hashtags": ["psychology", "brainfacts", "sleep"],
  "tags": ["8 to 12 search tags"],
  "source": "Full citation of the main study or reference the facts come from",
  "claims": ["Each factual claim made in the narration, one per item"],
  "scenes": [{"text": "Narration for scene 1 (the hook)"}, {"text": "..."}]
}"""


def log(msg):
    print(f"[generate] {msg}", flush=True)


# --------------------------------------------------------------------------- topics

def load_bank():
    if not BANK_PATH.exists():
        return []
    try:
        return json.loads(BANK_PATH.read_text(encoding="utf-8")).get("topics", [])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{BANK_PATH} is not valid JSON: {e}") from e


def pick_bank_topic(entries):
    used = history.used_topics(entries)
    for t in load_bank():
        if history.slugify(t["id"]) not in used:
            return t
    return None


def build_user_prompt(slot, bank_topic, entries, feedback):
    recent = entries[-60:]
    avoid = "\n".join(f"- {e.get('title', '')} [{e.get('topic', '')}]" for e in recent) or "- (nothing published yet)"
    parts = [SLOT_STYLE[slot], f"Today's date: {datetime.now(timezone.utc):%Y-%m-%d}.", ""]
    if bank_topic:
        parts += [
            "TOPIC (use this one): " + bank_topic["topic"],
            "FACT (the ONLY factual claims you may build the script on): " + bank_topic["fact"],
            "SOURCE (copy into the 'source' field): " + bank_topic["source"],
            "CAUTION (obey strictly): " + bank_topic["caution"],
            f'Set "topic" to exactly "{bank_topic["id"]}".',
        ]
    else:
        parts += [
            "Choose a NEW topic in psychology, brain facts, sleep, perception, memory, behavior, or a well-documented scientific mystery.",
            "Pick a finding you are highly confident about and can cite. Prefer classic, well-replicated findings.",
        ]
    parts += ["", "ALREADY PUBLISHED OR USED (do NOT repeat these topics, titles, or angles):", avoid]
    if feedback:
        parts += ["", "YOUR PREVIOUS ATTEMPT WAS REJECTED. Fix every problem below and reply with the full corrected JSON:"]
        parts += [f"- {p}" for p in feedback]
    return "\n".join(parts)


# --------------------------------------------------------------------------- Anthropic call

def call_claude(system, user):
    """Single Messages API call. Raises RuntimeError with an actionable message on failure."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it in GitHub: Settings > Secrets and variables > Actions > New repository secret.")
    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=90.0)
    try:
        msg = client.messages.create(model=MODEL, max_tokens=2000, system=system,
                                     messages=[{"role": "user", "content": user}])
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Anthropic rejected the API key (401). Re-create ANTHROPIC_API_KEY in the Anthropic Console and update the GitHub Secret.") from e
    except anthropic.PermissionDeniedError as e:
        raise RuntimeError(f"Anthropic API key lacks permission for model {MODEL!r} (403): {e}") from e
    except anthropic.NotFoundError as e:
        raise RuntimeError(f"Model {MODEL!r} was not found. Set the ANTHROPIC_MODEL environment variable (workflow env) to a model your key can use.") from e
    except anthropic.BadRequestError as e:
        raise RuntimeError(f"Anthropic rejected the request (400). If this mentions credit balance, add credits in the Anthropic Console. Details: {e}") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError(f"Anthropic rate limit hit even after automatic retries: {e}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Could not reach the Anthropic API: {e}") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error {getattr(e, 'status_code', '?')}: {e}") from e

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    usage = getattr(msg, "usage", None)
    if usage:
        log(f"model={MODEL} input_tokens={usage.input_tokens} output_tokens={usage.output_tokens}")
    if not text:
        raise ValueError("Claude returned an empty response")
    return text


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("response contained no JSON object")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"response was not valid JSON ({e})") from e


# --------------------------------------------------------------------------- validation / assembly

def _clean_list(items, limit):
    out, seen = [], set()
    for x in items if isinstance(items, list) else []:
        s = re.sub(r"[<>]", "", str(x)).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def _fit_tags(tags, budget=450):
    out, used = [], 0
    for t in tags:
        if used + len(t) + 1 > budget:
            break
        out.append(t)
        used += len(t) + 1
    return out


def build_video(raw, slot, bank_topic, entries, model):
    """Turn Claude's JSON into the final video JSON. Returns (video_or_None, problems)."""
    problems = []
    if not isinstance(raw, dict):
        return None, ["top-level JSON must be an object"]

    title = re.sub(r"[<>]", "", str(raw.get("title", ""))).strip()
    if not (10 <= len(title) <= 100):
        problems.append("title must be 10-100 characters (aim for under 70)")

    scenes = []
    for s in raw.get("scenes", []) if isinstance(raw.get("scenes"), list) else []:
        text = (s.get("text", "") if isinstance(s, dict) else str(s)).strip()
        if text:
            scenes.append({"text": re.sub(r"\s+", " ", text)})
    if not (MIN_SCENES <= len(scenes) <= MAX_SCENES):
        problems.append(f"need {MIN_SCENES}-{MAX_SCENES} scenes, got {len(scenes)}")

    total = sum(len(s["text"].split()) for s in scenes)
    if not (MIN_WORDS <= total <= MAX_WORDS):
        problems.append(f"total narration must be 85-105 words (accepted {MIN_WORDS}-{MAX_WORDS}), got {total}")
    if scenes and len(scenes[0]["text"].split()) > MAX_HOOK_WORDS:
        problems.append(f"hook (scene 1) must be at most 12 words, got {len(scenes[0]['text'].split())}")
    for i, s in enumerate(scenes, 1):
        n = len(s["text"].split())
        if n > MAX_SCENE_WORDS:
            problems.append(f"scene {i} has {n} words; keep each scene under 22")
        if re.search(r"[#*_\[\]{}<>]|\(", s["text"]):
            problems.append(f"scene {i} contains markup or parentheses; use plain words only")
        m = BANNED.search(s["text"])
        if m:
            problems.append(f"scene {i} uses the banned word/phrase {m.group(0)!r}")

    source = str(raw.get("source", "")).strip()
    if len(source) < 10:
        problems.append("'source' must be a real citation of the study or reference")
    claims = _clean_list(raw.get("claims"), 12)
    if not claims:
        problems.append("'claims' must list the factual claims made in the narration")
    summary = re.sub(r"\s+", " ", str(raw.get("summary", ""))).strip()
    if len(summary) < 20:
        problems.append("'summary' must be 1-2 sentences")

    topic = bank_topic["id"] if bank_topic else history.slugify(raw.get("topic", "") or title)
    if not topic:
        problems.append("'topic' is missing")

    hashtags = []
    for h in raw.get("hashtags", []) if isinstance(raw.get("hashtags"), list) else []:
        h = re.sub(r"[^a-z0-9]", "", str(h).lower())
        if h and h != "shorts" and h not in hashtags:
            hashtags.append(h)
    hashtags = ["#" + h for h in hashtags[:3]] + ["#shorts"]

    tags = _fit_tags(_clean_list(raw.get("tags"), 15))
    for extra in ("psychology facts", "brain facts", "shorts"):
        if extra not in [t.lower() for t in tags]:
            tags.append(extra)
    if len(tags) < 5:
        problems.append("need at least 5 tags")

    if problems:
        return None, problems

    description = (
        f"{summary}\n\n"
        f"Source: {source}\n\n"
        "For education only, not medical advice.\n\n"
        "New psychology and brain facts every day. Subscribe to Thought After 2AM.\n\n"
        + " ".join(hashtags)
    )
    video = {
        "title": title[:100],
        "description": description,
        "tags": _fit_tags(tags),
        "scenes": scenes,
        "slot": slot,
        "topic": topic,
        "topic_origin": "bank" if bank_topic else "model",
        "source": source,
        "claims": claims,
        "word_count": total,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    dup = history.find_duplicate(video, entries)
    if dup:
        return None, [f"duplicate content: {dup}. Choose a clearly different topic and title."]
    return video, []


# --------------------------------------------------------------------------- orchestration

def generate(slot, entries, use_bank=True):
    bank_topic = pick_bank_topic(entries) if use_bank else None
    if bank_topic:
        log(f"slot={slot} topic from vetted bank: {bank_topic['id']}")
    else:
        log(f"slot={slot} vetted bank exhausted or disabled; asking Claude to choose a new topic")
    feedback = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"slot={slot} attempt {attempt}/{MAX_ATTEMPTS}: calling Claude ({MODEL})")
        started = time.monotonic()
        try:
            raw = parse_json(call_claude(SYSTEM_PROMPT, build_user_prompt(slot, bank_topic, entries, feedback)))
            video, problems = build_video(raw, slot, bank_topic, entries, MODEL)
        except ValueError as e:                      # unparseable / empty reply: retry with feedback
            video, problems = None, [str(e)]
        log(f"attempt {attempt} finished in {time.monotonic() - started:.1f}s")
        if video:
            log(f"OK title={video['title']!r} topic={video['topic']} scenes={len(video['scenes'])} words={video['word_count']}")
            return video
        for p in problems:
            log(f"REJECTED: {p}")
        feedback = problems
    raise RuntimeError(f"Could not produce a valid, non-duplicate script for the {slot} slot after {MAX_ATTEMPTS} attempts.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slot", required=True, choices=list(VALID_SLOTS) + ["both"])
    ap.add_argument("--out", help="output path (single slot only); default video_<slot>.json")
    ap.add_argument("--no-bank", action="store_true", help="skip topics_bank.json and let Claude choose the topic")
    args = ap.parse_args(argv)

    slots = list(VALID_SLOTS) if args.slot == "both" else [args.slot]
    if args.out and len(slots) > 1:
        ap.error("--out can only be used with a single slot")
    entries = list(history.load()["videos"])
    log(f"history has {len(entries)} published videos")
    for slot in slots:
        video = generate(slot, entries, use_bank=not args.no_bank)
        out = Path(args.out) if args.out else Path(f"video_{slot}.json")
        out.write_text(json.dumps(video, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"wrote {out}")
        entries.append({"title": video["title"], "topic": video["topic"], "script_sha256": history.script_hash(video)})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - top-level reporter for CI logs
        print(f"::error title=Script generation failed::{e}", flush=True)
        print(f"[generate] FAILED: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
