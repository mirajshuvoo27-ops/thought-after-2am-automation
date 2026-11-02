import os
import json
import asyncio
import subprocess
import math
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(".")
OUTPUT = ROOT / "output"
ASSETS = ROOT / "assets"
OUTPUT.mkdir(exist_ok=True)

W, H = 720, 1280
FPS = 15
VOICE_OPTIONS = ["en-US-AndrewNeural", "en-US-AriaNeural"]
POSE_FILES = [
    "01_main_host.png", "02_thinking.png", "03_speaking_gesture.png",
    "04_adjusting_sunglasses.png", "05_relaxed_pose.png",
    "06_thumbs_up.png", "07_explaining.png", "08_phone_pose.png"
]


def run(command):
    subprocess.run(command, check=True)


def font(size, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    words, lines, current = str(text).split(), [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


async def make_audio(text, index):
    path = OUTPUT / f"audio_{index}.mp3"
    for voice in VOICE_OPTIONS:
        for attempt in range(3):
            try:
                await edge_tts.Communicate(text, voice).save(str(path))
                if path.exists() and path.stat().st_size > 1000:
                    return path
            except Exception as exc:
                print(f"TTS {voice}, attempt {attempt + 1}: {exc}")
            await asyncio.sleep(4 * (attempt + 1))
    raise RuntimeError(f"Could not generate audio for scene {index}")


def audio_duration(path):
    result = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ], text=True)
    return max(2.0, float(result.strip()))


def gradient_frame():
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        t = y / H
        c = (int(7 + 8*t), int(14 + 13*t), int(35 + 30*t))
        for x in range(W):
            px[x, y] = c
    return im


def draw_brain(draw, cx, cy, scale, color):
    # Friendly simplified brain icon made from vector-like bubbles.
    r = int(32 * scale)
    for dx, dy, rr in [(-1, 0, 1), (-.35, -.65, .9), (.45, -.6, .9),
                       (1, 0, 1), (-.45, .55, .85), (.45, .55, .85)]:
        x, y, rad = int(cx + dx*r), int(cy + dy*r), int(rr*r)
        draw.ellipse((x-rad, y-rad, x+rad, y+rad), outline=color, width=max(2, int(5*scale)))
    draw.line((cx, cy-r, cx, cy+r), fill=color, width=max(2, int(4*scale)))


def draw_topic_graphic(draw, text, t):
    low = text.lower()
    accent = (255, 197, 55)
    cx, cy = W//2, 560
    bob = int(18 * math.sin(t * 2.8))
    if any(k in low for k in ["brain", "mind", "memory", "song", "earworm", "scientist"]):
        draw_brain(draw, cx, cy + bob, 2.1, accent)
        # Floating music notes / sparks
        f = font(66)
        draw.text((105, 365 + bob), "♪", font=f, fill=(100, 190, 255))
        draw.text((520, 420 - bob), "♫", font=f, fill=(255, 120, 170))
        draw.ellipse((cx-190, cy-190+bob, cx+190, cy+190+bob),
                     outline=(65, 120, 220), width=5)
    elif any(k in low for k in ["light", "idea", "think", "question", "why"]):
        r = 115 + int(8 * math.sin(t*3))
        draw.ellipse((cx-r, cy-r+bob, cx+r, cy+r+bob),
                     outline=accent, width=10)
        draw.ellipse((cx-52, cy-52+bob, cx+52, cy+52+bob),
                     fill=accent)
        draw.line((cx-48, cy+135+bob, cx+48, cy+135+bob), fill=accent, width=12)
        draw.line((cx-38, cy+158+bob, cx+38, cy+158+bob), fill=accent, width=10)
        draw.text((cx+145, cy-160+bob), "?", font=font(100), fill=(100, 190, 255))
    else:
        # Generic explainer graphic: orbiting circles and a central glowing dot.
        for i in range(6):
            angle = t*1.2 + i*math.pi/3
            x = int(cx + 190*math.cos(angle))
            y = int(cy + 150*math.sin(angle))
            rr = 27 + int(5*math.sin(t*4+i))
            draw.ellipse((x-rr, y-rr, x+rr, y+rr),
                         fill=(60, 120, 220), outline=(160, 205, 255), width=3)
        draw.ellipse((cx-85, cy-85+bob, cx+85, cy+85+bob),
                     fill=(255, 197, 55), outline=(255, 235, 160), width=7)


def make_frame(text, index, frame_no, total_frames, pose_path=None):
    t = frame_no / FPS
    im = gradient_frame()
    d = ImageDraw.Draw(im)

    # Header
    d.rounded_rectangle((28, 28, W-28, 94), radius=22,
                        fill=(17, 32, 70), outline=(58, 104, 190), width=2)
    d.text((50, 43), "THOUGHT AFTER 2AM", font=font(25), fill=(230, 238, 255))
    d.ellipse((W-68, 49, W-48, 69), fill=(255, 197, 55))

    # Alternate host-led and graphics-only scenes.
    show_host = (index % 2 == 0) and pose_path is not None
    if show_host:
        pose = Image.open(pose_path).convert("RGB")
        pose.thumbnail((W-76, 640), Image.Resampling.LANCZOS)
        # Host artwork is shown as a framed editorial panel, not stretched.
        x = (W-pose.width)//2
        y = 125 + int(7*math.sin(t*2))
        d.rounded_rectangle((30, 112, W-30, 790), radius=28,
                            fill=(18, 30, 60), outline=(72, 118, 210), width=3)
        im.paste(pose, (x, y))
        d = ImageDraw.Draw(im)
    else:
        draw_topic_graphic(d, text, t)

    # Kinetic caption: words enter in small groups rather than one giant paragraph.
    words = str(text).split()
    visible_count = min(len(words), max(1, int((frame_no / max(1, total_frames-1)) * len(words)) + 1))
    visible = " ".join(words[:visible_count])
    fnt = font(38)
    lines = wrap(d, visible, fnt, W-100)
    if len(lines) > 4:
        fnt = font(32)
        lines = wrap(d, visible, fnt, W-100)

    top = 850 if show_host else 820
    box_bottom = 1195
    d.rounded_rectangle((34, top, W-34, box_bottom), radius=28,
                        fill=(10, 20, 46), outline=(67, 111, 205), width=3)
    line_h = 54
    y = top + (box_bottom-top-len(lines)*line_h)//2
    for line in lines:
        b = d.textbbox((0, 0), line, font=fnt)
        x = (W-(b[2]-b[0]))//2
        d.text((x+2, y+3), line, font=fnt, fill=(0, 0, 0))
        d.text((x, y), line, font=fnt, fill=(250, 250, 255))
        y += line_h

    # Progress indicator
    bar_w = int((W-70) * ((frame_no+1)/max(1, total_frames)))
    d.rounded_rectangle((35, 1230, W-35, 1242), radius=6, fill=(38, 54, 88))
    d.rounded_rectangle((35, 1230, 35+bar_w, 1242), radius=6, fill=(255, 197, 55))
    return im


def create_scene_clip(text, index, pose_path=None):
    audio = asyncio.run(make_audio(text, index))
    duration = audio_duration(audio)
    total_frames = max(30, int(math.ceil(duration * FPS)))
    frame_dir = OUTPUT / f"frames_{index}"
    frame_dir.mkdir(exist_ok=True)

    for n in range(total_frames):
        frame = make_frame(text, index, n, total_frames, pose_path)
        frame.save(frame_dir / f"frame_{n:05d}.jpg", quality=88)

    clip = OUTPUT / f"clip_{index}.mp4"
    run([
        "ffmpeg", "-y", "-framerate", str(FPS),
        "-i", str(frame_dir / "frame_%05d.jpg"),
        "-i", str(audio),
        "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart", str(clip)
    ])
    return clip


def create_video(scenes, scene_poses=None):
    clips = []
    scene_poses = scene_poses or []

    for i, text in enumerate(scenes):
        pose_name = scene_poses[i] if i < len(scene_poses) else POSE_FILES[i % len(POSE_FILES)]
        pose_path = ASSETS / pose_name
        if not pose_path.exists():
            raise FileNotFoundError(f"Missing {pose_path}; check assets/ folder.")
        clips.append(create_scene_clip(text, i, pose_path))

    concat_file = OUTPUT / "clips.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    final_video = OUTPUT / "thought_after_2am.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-c", "copy", str(final_video)])
    return final_video


def upload_video(video_path, data):
    credentials = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    credentials.refresh(
        __import__("google.auth.transport.requests",
                   fromlist=["Request"]).Request()
    )
    youtube = build("youtube", "v3", credentials=credentials)

    body = {
        "snippet": {
            "title": data["title"][:100],
            "description": data["description"],
            "tags": data.get("tags", []),
            "categoryId": "27"
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")
    print("Video uploaded:", response["id"])


def main():
    with open("video.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    scenes = data.get("scenes", [])
    if not scenes:
        raise ValueError("No scenes found in video.json")
    video = create_video(scenes, data.get("scene_poses"))
    upload_video(video, data)


if __name__ == "__main__":
    main()
