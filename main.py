#!/usr/bin/env python3
"""Thought After 2AM - render one Short and upload it privately for manual scheduling.
 
Run by the GitHub workflow after generate_script.py has written video_<slot>.json.
    VIDEO_SLOT = morning | evening      (or --slot)
    DRY_RUN    = true  -> render only; no upload, no history entry   (or --dry-run)
 
Rendering pipeline (same look as before, faster):
  * all scene narration is synthesized concurrently,
  * frames are drawn with identical drawing code but piped as raw pixels straight into ONE FFmpeg encode
    (no per-frame JPEG files, no per-scene clips, no lossy concat),
  * the expensive gradient is vectorised with NumPy and cached; fonts are cached.
"""
import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
 
import numpy as np
from PIL import Image, ImageDraw, ImageFont
 
import history
 
ROOT = Path(".")
OUTPUT = ROOT / "output"
W, H, FPS = 720, 1280, 24
OUT_W, OUT_H = 1080, 1920
VOICE = "en-US-AndrewNeural"
FALLBACK_VOICE = "en-US-AriaNeural"
TTS_TIMEOUT = 25            # seconds per attempt
TTS_CONCURRENCY = int(os.environ.get("TTS_CONCURRENCY", "3"))
SCENE_PAD = 0.2             # seconds of breathing room after each scene's narration
MIN_SCENE_FRAMES = 48       # 2 seconds, same floor as before
X264_PRESET = os.environ.get("X264_PRESET", "veryfast")
X264_CRF = os.environ.get("X264_CRF", "19")
# The previous engine placed subtitle text ~24 px above the middle of its card. True = vertically center it
# in the card (matches the "centered subtitles" look); False = reproduce the old placement pixel-for-pixel.
CENTER_SUBTITLE_IN_CARD = True
SLOT_FILES = {"morning": "video_morning.json", "evening": "video_evening.json"}
 
_T0 = time.monotonic()
 
 
def log(msg):
    print(f"[+{time.monotonic() - _T0:6.1f}s] {msg}", flush=True)
 
 
def stage(name):
    print(f"::group::{name}" if os.environ.get("GITHUB_ACTIONS") else f"--- {name} ---", flush=True)
    log(f"STAGE START: {name}")
 
 
def end_stage():
    if os.environ.get("GITHUB_ACTIONS"):
        print("::endgroup::", flush=True)
 
 
def run(cmd):
    subprocess.run(cmd, check=True)
 
 
# ----------------------------------------------------------------------------------------------
# Visual style (unchanged from the previous engine)
# ----------------------------------------------------------------------------------------------
 
@lru_cache(maxsize=8)
def font(size, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()
 
 
def text_width(draw, s, f):
    b = draw.textbbox((0, 0), s, font=f, stroke_width=0)
    return b[2] - b[0]
 
 
def wrap(draw, text, f, maxw):
    lines, line = [], ""
    for word in str(text).split():
        test = (line + " " + word).strip()
        if text_width(draw, test, f) <= maxw:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]
 
 
def topic_kind(text):
    s = text.lower()
    if any(k in s for k in ("brain", "mind", "memory", "psycholog", "thought", "think", "dream")): return "brain"
    if any(k in s for k in ("time", "clock", "night", "sleep", "hour", "minute", "late")): return "time"
    if any(k in s for k in ("music", "song", "sound", "hear", "earworm", "noise")): return "sound"
    if any(k in s for k in ("light", "idea", "learn", "discover", "why", "fact", "science")): return "idea"
    if any(k in s for k in ("heart", "feel", "emotion", "love", "stress", "fear", "happy")): return "emotion"
    if any(k in s for k in ("phone", "screen", "social", "internet", "digital")): return "digital"
    return "concept"
 
 
def palette(kind):
    return {
        "brain": ((9, 17, 45), (73, 116, 255), (165, 111, 255)),
        "time": ((10, 23, 48), (255, 185, 70), (255, 105, 105)),
        "sound": ((8, 24, 48), (54, 211, 208), (105, 126, 255)),
        "idea": ((12, 21, 48), (255, 213, 91), (72, 188, 255)),
        "emotion": ((30, 14, 43), (255, 112, 153), (255, 190, 111)),
        "digital": ((7, 22, 43), (62, 206, 255), (130, 120, 255)),
        "concept": ((10, 18, 42), (90, 160, 255), (255, 193, 85)),
    }[kind]
 
 
LABELS = {"brain": "MIND & BRAIN", "time": "TIME & HABITS", "sound": "SOUND & MEMORY",
          "idea": "DISCOVER SOMETHING NEW", "emotion": "HUMAN EMOTIONS",
          "digital": "DIGITAL LIFE", "concept": "THINK ABOUT IT"}
 
 
@lru_cache(maxsize=8)
def gradient_bg(kind):
    """Same radial glow as before, computed with NumPy (about 100x faster than the per-pixel Python loop)."""
    c1, accent, _ = palette(kind)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    glow = np.maximum(0.0, 1.0 - np.sqrt(((xs - W * .52) / (W * .9)) ** 2 + ((ys - H * .39) / (H * .8)) ** 2))
    arr = np.empty((H, W, 3), np.float64)
    for i in range(3):
        arr[..., i] = c1[i] + glow * (accent[i] - c1[i]) * .18
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
 
 
def draw_icon(d, kind, cx, cy, t, a, b):
    pulse = 1 + .045 * math.sin(t * 2.7)
    r = int(128 * pulse)
    # Halo rings move continuously, avoiding static slide-show imagery.
    for j in range(3):
        rr = r + 28 + j * 34
        phase = t * (.45 + j * .11) + j * 2
        ox = math.cos(phase) * 18
        oy = math.sin(phase) * 13
        d.ellipse((cx - rr + ox, cy - rr + oy, cx + rr + ox, cy + rr + oy), outline=(*a, 75 + j * 25), width=3)
    if kind == "brain":
        # stylized brain made from connected rounded lobes
        for dx, dy, rx, ry in [(-45, -8, 43, 48), (-10, -42, 48, 43), (35, -20, 43, 48), (48, 25, 35, 38), (0, 35, 48, 43), (-45, 30, 35, 38)]:
            d.ellipse((cx + dx - rx, cy + dy - ry, cx + dx + rx, cy + dy + ry), fill=(*a, 245), outline=(245, 248, 255, 255), width=4)
        d.line((cx, cy - 60, cx - 3, cy + 72), fill=(15, 24, 55, 255), width=5)
        d.arc((cx - 48, cy - 35, cx + 5, cy + 28), 190, 350, fill=(*b, 255), width=5)
        d.arc((cx - 4, cy - 55, cx + 52, cy + 12), 20, 170, fill=(*b, 255), width=5)
    elif kind == "time":
        d.ellipse((cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2), fill=(18, 34, 68, 255), outline=(*a, 255), width=12)
        for i in range(12):
            an = i * math.tau / 12
            x1 = cx + math.cos(an) * r * .39; y1 = cy + math.sin(an) * r * .39
            x2 = cx + math.cos(an) * r * .44; y2 = cy + math.sin(an) * r * .44
            d.line((x1, y1, x2, y2), fill=(245, 248, 255, 255), width=5)
        d.line((cx, cy, cx - 4, cy - r * .27), fill=(255, 255, 255, 255), width=9)
        d.line((cx, cy, cx + r * .22, cy + r * .12), fill=(*b, 255), width=8)
        d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=(*a, 255))
    elif kind == "sound":
        d.rounded_rectangle((cx - 28, cy - 65, cx + 28, cy + 65), radius=25, fill=(*a, 255))
        for k in range(1, 4):
            off = 48 * k
            d.arc((cx - off, cy - off * .8, cx + off, cy + off * .8), -65, 65, fill=(*b, 255), width=8)
            d.arc((cx - off, cy - off * .8, cx + off, cy + off * .8), 115, 245, fill=(*b, 255), width=8)
    elif kind == "idea":
        d.ellipse((cx - 65, cy - 90, cx + 65, cy + 40), fill=(*a, 255), outline=(255, 255, 255, 255), width=5)
        d.rounded_rectangle((cx - 38, cy + 22, cx + 38, cy + 80), radius=12, fill=(*b, 255))
        d.line((cx - 25, cy + 48, cx + 25, cy + 48), fill=(20, 30, 60, 255), width=5)
        for i in range(8):
            an = i * math.tau / 8 + t * .15
            x1 = cx + math.cos(an) * 100; y1 = cy + math.sin(an) * 120
            x2 = cx + math.cos(an) * 135; y2 = cy + math.sin(an) * 155
            d.line((x1, y1, x2, y2), fill=(*a, 220), width=6)
    elif kind == "emotion":
        pts = []
        for i in range(120):
            q = i / 119 * math.tau
            x = 16 * math.sin(q) ** 3
            y = 13 * math.cos(q) - 5 * math.cos(2 * q) - 2 * math.cos(3 * q) - math.cos(4 * q)
            pts.append((cx + x * 7, cy - y * 7))
        d.polygon(pts, fill=(*a, 255), outline=(255, 245, 255, 255))
    elif kind == "digital":
        d.rounded_rectangle((cx - 75, cy - 125, cx + 75, cy + 125), radius=24, fill=(17, 35, 68, 255), outline=(*a, 255), width=9)
        d.rounded_rectangle((cx - 57, cy - 102, cx + 57, cy + 91), radius=12, fill=(*b, 180))
        d.ellipse((cx - 9, cy + 102, cx + 9, cy + 120), fill=(245, 245, 255, 255))
        for i in range(3):
            yy = cy - 50 + i * 42
            d.rounded_rectangle((cx - 35, yy, cx + 35, yy + 13), radius=6, fill=(255, 255, 255, 230))
    else:
        # rotating geometric concept mark
        for i in range(6):
            an = t * .55 + i * math.tau / 6
            x = cx + math.cos(an) * 82; y = cy + math.sin(an) * 82
            rr = 24 + 5 * math.sin(t * 2 + i)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(*a, 245), outline=(255, 255, 255, 230), width=3)
        d.ellipse((cx - 42, cy - 42, cx + 42, cy + 42), fill=(*b, 255), outline=(255, 255, 255, 255), width=5)
 
 
class SceneRenderer:
    """Draws the frames of one scene. Drawing order and parameters match the previous draw_frame()."""
 
    def __init__(self, text, frames):
        self.text, self.frames = text, frames
        self.kind = topic_kind(text)
        self.bg = gradient_bg(self.kind)
        _, self.accent, self.accent2 = palette(self.kind)
        self.words = text.split()
        self.label = LABELS[self.kind]
        self._measure = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        self._layouts = {}
 
    def _layout(self):
        """Lay out the complete scene caption once; keep it readable for the full narration."""
        if "full" not in self._layouts:
            shown = " ".join(self.words)
            f = font(34)
            lines = wrap(self._measure, shown, f, W - 112)
            if len(lines) > 3:
                f = font(30)
                lines = wrap(self._measure, shown, f, W - 112)
            if len(lines) > 4:
                f = font(26)
                lines = wrap(self._measure, shown, f, W - 112)
            if len(lines) > 5:
                raise ValueError(f"Subtitle needs {len(lines)} lines; shorten this scene to keep captions comfortably readable.")
            self._layouts["full"] = (f, lines)
        return self._layouts["full"]
 
    def frame(self, n):
        t = n / FPS
        accent, accent2 = self.accent, self.accent2
        im = self.bg.copy()
        d = ImageDraw.Draw(im, "RGBA")
        # Continuous floating particles
        for i in range(38):
            x = (i * 97 + int(t * (13 + i % 5) * 7)) % W
            y = (i * 173 + int(math.sin(t * .7 + i) * 35)) % H
            rr = 2 + (i % 4)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(*accent, 80 + (i % 3) * 35))
        # Top label
        d.rounded_rectangle((34, 38, W - 34, 100), radius=22, fill=(5, 12, 30, 175), outline=(*accent, 150), width=2)
        d.text((W // 2, 69), "THOUGHT AFTER 2AM", font=font(23), fill=(239, 244, 255, 255), anchor="mm")
        # Large animated visual in upper-middle
        draw_icon(d, self.kind, W // 2, 410, t, accent, accent2)
        # Topic label above subtitle
        d.text((W // 2, 650), self.label, font=font(20), fill=(*accent, 255), anchor="mm")
        # Full-sentence subtitles: show the complete phrase immediately and hold it
        # on screen for the entire spoken scene, instead of making viewers chase words.
        progress = min(1, (n + 1) / max(1, self.frames))
        f, lines = self._layout()
        line_h = 44 if len(lines) >= 5 else 50
        block_h = len(lines) * line_h + 64
        top = H // 2 + 95
        d.rounded_rectangle((28, top, W - 28, top + block_h), radius=28, fill=(3, 9, 24, 232), outline=(*accent, 245), width=3)
        y = top + 32 + (block_h - 64 - len(lines) * line_h) // 2
        for line in lines:
            d.text((W // 2 + 2, y + 3), line, font=f, fill=(0, 0, 0, 255), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0, 255))
            d.text((W // 2, y), line, font=f, fill=(255, 255, 255, 255), anchor="mm", stroke_width=1, stroke_fill=(15, 20, 40, 255))
            y += line_h
        # animated progress line
        prog_w = int((W - 70) * progress)
        d.rounded_rectangle((35, H - 82, W - 35, H - 68), radius=7, fill=(70, 80, 110, 130))
        d.rounded_rectangle((35, H - 82, 35 + prog_w, H - 68), radius=7, fill=(*accent, 255))
        return im.convert("RGB").tobytes()
 
 
# ----------------------------------------------------------------------------------------------
# Narration
# ----------------------------------------------------------------------------------------------
 
async def _tts_one(index, text, path, sem):
    import edge_tts
    async with sem:
        last_error = None
        for voice in (VOICE, FALLBACK_VOICE):
            for attempt in range(1, 3):
                try:
                    path.unlink(missing_ok=True)
                    await asyncio.wait_for(edge_tts.Communicate(text, voice, rate="+2%").save(str(path)), timeout=TTS_TIMEOUT)
                    if path.exists() and path.stat().st_size > 1000:
                        log(f"TTS ok  scene={index} voice={voice} attempt={attempt}")
                        if voice != VOICE:
                            log(f"WARNING: scene {index} used fallback voice {voice}; the voice will change mid-video")
                        return
                    raise RuntimeError("TTS returned an empty audio file")
                except Exception as e:  # noqa: BLE001 - retry any TTS failure
                    last_error = e
                    log(f"TTS retry scene={index} voice={voice} attempt={attempt}: {type(e).__name__}: {e}")
                    await asyncio.sleep(2 * attempt)
        raise RuntimeError(f"Text-to-speech failed for scene {index} after bounded retries: {last_error}")
 
 
async def synthesize_all(texts, paths):
    sem = asyncio.Semaphore(max(1, TTS_CONCURRENCY))
    await asyncio.gather(*[_tts_one(i, t, p, sem) for i, (t, p) in enumerate(zip(texts, paths))])
 
 
def probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True)
    return float(out.strip())
 
 
def build_narration(audio_paths, frames_per_scene, out_path):
    """Concatenate scene audio, padding each scene to exactly its video length so picture and voice stay in sync."""
    n = len(audio_paths)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in audio_paths:
        cmd += ["-i", str(p)]
    parts = [f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,apad=whole_dur={fr / FPS:.4f}[a{i}]"
             for i, fr in enumerate(frames_per_scene)]
    parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[aout]", "-c:a", "aac", "-b:a", "160k", str(out_path)]
    run(cmd)
 
 
# ----------------------------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------------------------
 
def scene_text(scene):
    return (scene.get("text", "") if isinstance(scene, dict) else str(scene)).strip()
 
 
def render_video(scenes, slot, final_path):
    texts = [t for t in (scene_text(s) for s in scenes) if t]
    if not texts:
        raise ValueError("The script has no scenes with text")
 
    stage(f"1/4 Text-to-speech ({len(texts)} scenes)")
    audio = [OUTPUT / f"audio_{slot}_{i}.mp3" for i in range(len(texts))]
    asyncio.run(synthesize_all(texts, audio))
    durations = [probe_duration(p) for p in audio]
    log(f"narration lengths: {', '.join(f'{d:.1f}s' for d in durations)} (total {sum(durations):.1f}s)")
    end_stage()
 
    frames_per = [max(MIN_SCENE_FRAMES, math.ceil((d + SCENE_PAD) * FPS)) for d in durations]
    total_frames = sum(frames_per)
 
    stage("2/4 Building narration track")
    narration = OUTPUT / f"narration_{slot}.m4a"
    build_narration(audio, frames_per, narration)
    log(f"narration track {probe_duration(narration):.2f}s for {total_frames / FPS:.2f}s of video")
    end_stage()
 
    stage(f"3/4 Rendering {total_frames} frames at {FPS} fps and encoding")
    cmd = ["ffmpeg", "-y", "-loglevel", "warning", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-framerate", str(FPS), "-i", "pipe:0", "-i", str(narration), "-map", "0:v:0", "-map", "1:a:0",
           "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos,format=yuv420p",
           "-c:v", "libx264", "-preset", X264_PRESET, "-crf", X264_CRF, "-g", str(FPS * 2),
           "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(final_path)]
    ffmpeg_log = OUTPUT / f"ffmpeg_{slot}.log"
    done, render_start = 0, time.monotonic()
    with open(ffmpeg_log, "wb") as lf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=lf)
        try:
            for si, (text, frames) in enumerate(zip(texts, frames_per), 1):
                scene_start = time.monotonic()
                renderer = SceneRenderer(text, frames)
                for n in range(frames):
                    proc.stdin.write(renderer.frame(n))
                done += frames
                elapsed = time.monotonic() - scene_start
                log(f"scene {si}/{len(texts)} drawn: {frames} frames in {elapsed:.1f}s ({frames / max(elapsed, 1e-6):.0f} fps) | total {done}/{total_frames} ({done * 100 // total_frames}%)")
            proc.stdin.close()
        except BrokenPipeError:
            log("ffmpeg closed its input early; see its log below")
        finally:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
            rc = proc.wait()
    if rc != 0:
        tail = ffmpeg_log.read_text(errors="replace")[-1500:]
        raise RuntimeError(f"ffmpeg exited with code {rc}:\n{tail}")
    log(f"frames drawn and encoded in {time.monotonic() - render_start:.1f}s")
    end_stage()
 
    stage("4/4 Checking output")
    seconds = probe_duration(final_path)
    size_mb = final_path.stat().st_size / 1e6
    log(f"final video: {final_path} | {seconds:.1f}s | {size_mb:.1f} MB | {OUT_W}x{OUT_H}")
    if seconds > 60:
        log("WARNING: video is longer than 60 seconds; the channel target is 30-40 seconds")
    elif seconds < 15:
        log("WARNING: video is shorter than 15 seconds")
    end_stage()
    return seconds
 
 
# ----------------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------------
 
def clean_slot_files(slot):
    """Remove only temp files this script creates for this slot; never touches other repo files."""
    for pattern in (f"audio_{slot}_*.mp3", f"narration_{slot}.m4a", f"thought_after_2am_{slot}.mp4", f"ffmpeg_{slot}.log"):
        for p in OUTPUT.glob(pattern):
            p.unlink(missing_ok=True)
 
 
def write_step_summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
 
 
def main(argv=None):
    ap = argparse.ArgumentParser(description="Render and schedule one Thought After 2AM Short.")
    ap.add_argument("--slot", default=os.environ.get("VIDEO_SLOT", ""), help="morning or evening (default: $VIDEO_SLOT)")
    ap.add_argument("--json", help="script file (default: video_<slot>.json)")
    ap.add_argument("--dry-run", action="store_true", default=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
                    help="render only; no upload and no history entry")
    args = ap.parse_args(argv)
 
    slot = args.slot.strip().lower()
    if slot not in SLOT_FILES:
        raise ValueError(f"VIDEO_SLOT must be 'morning' or 'evening', got {slot!r}")
    OUTPUT.mkdir(exist_ok=True)
    clean_slot_files(slot)
 
    script_path = Path(args.json or SLOT_FILES[slot])
    if not script_path.exists():
        raise FileNotFoundError(f"{script_path} not found. generate_script.py must run before main.py.")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    if not data.get("scenes"):
        raise ValueError(f"{script_path} has no scenes")
    if not str(data.get("title", "")).strip():
        raise ValueError(f"{script_path} has no title")
 
    duplicate = history.find_duplicate(data)
    if duplicate:
        raise RuntimeError(f"Refusing to publish a repeat: {duplicate}")
 
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    log(f"SLOT={slot} EVENT={event} DRY_RUN={args.dry_run} SCRIPT={script_path}")
    log(f"TITLE: {data['title']}")
 
    final = OUTPUT / f"thought_after_2am_{slot}.mp4"
    seconds = render_video(data["scenes"], slot, final)
 
    if args.dry_run:
        log("DRY RUN: skipping YouTube upload and history update")
        write_step_summary([f"### Dry run: {slot}", f"**{data['title']}** rendered ({seconds:.0f}s). Nothing was uploaded."])
        return
 
    stage("Upload to YouTube (PRIVATE; schedule manually in Studio)")
    from youtube_upload import upload_private
    video_id = upload_private(final, data)
    log(f"Uploaded private video id: {video_id}  https://youtu.be/{video_id}")
    end_stage()

    try:
        history.record({
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slot": slot,
            "title": data["title"],
            "topic": data.get("topic", history.slugify(data["title"])),
            "source": data.get("source", ""),
            "video_id": video_id,
            "publish_at": None,
            "manual_schedule": True,
            "script_sha256": history.script_hash(data),
        })
        log("history updated")
    except Exception as e:  # noqa: BLE001 - upload already succeeded; do not fail the job over bookkeeping
        log(f"WARNING: video uploaded but history was not updated: {e}")
        print(f"::warning title=History not updated::{e}", flush=True)
 
    write_step_summary([
        f"### Private {slot} Short",
        f"- **{data['title']}**",
        f"- Video: https://youtu.be/{video_id} (uploaded as Private)",
        "- Next step: schedule the video manually in YouTube Studio.",
    ])
    log("DONE")
 
 
if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - top-level reporter for CI logs
        traceback.print_exc()
        print(f"::error title=Short pipeline failed::{type(e).__name__}: {e}", flush=True)
        sys.exit(1)
 
