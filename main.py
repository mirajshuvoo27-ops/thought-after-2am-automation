import os
import json
import asyncio
import subprocess
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

WIDTH, HEIGHT = 1080, 1920
FPS = 30
POSE_FILES = [
    "01_main_host.png",
    "02_thinking.png",
    "03_speaking_gesture.png",
    "04_adjusting_sunglasses.png",
    "05_relaxed_pose.png",
    "06_thumbs_up.png",
    "07_explaining.png",
    "08_phone_pose.png",
]
VOICE_OPTIONS = ["en-US-AndrewNeural", "en-US-AriaNeural"]


def run(command):
    subprocess.run(command, check=True)


def get_font(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def make_scene(text, index, pose_name=None):
    # Vertical navy-to-blue gradient background.
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        color = (
            int(7 + 10 * t),
            int(13 + 17 * t),
            int(34 + 34 * t),
        )
        for x in range(WIDTH):
            pixels[x, y] = color

    draw = ImageDraw.Draw(image)
    title_font = get_font(42)
    label_font = get_font(28)
    text_font = get_font(57)

    # Header and subtle accent.
    draw.rounded_rectangle((54, 58, WIDTH - 54, 142), radius=28,
                           fill=(17, 31, 67), outline=(55, 100, 190), width=3)
    draw.text((82, 78), "THOUGHT AFTER 2AM", font=title_font,
              fill=(226, 235, 255))
    draw.ellipse((WIDTH - 125, 83, WIDTH - 91, 117), fill=(255, 194, 40))

    # Select a reusable character pose for this scene.
    selected = pose_name or POSE_FILES[index % len(POSE_FILES)]
    pose_path = ASSETS / selected
    if not pose_path.exists():
        raise FileNotFoundError(
            f"Missing character pose: {pose_path}. "
            "Check that all 8 PNG files are inside the assets/ folder."
        )

    pose = Image.open(pose_path).convert("RGB")
    pose.thumbnail((940, 1030), Image.Resampling.LANCZOS)

    # Place the pose inside a framed card, preserving its proportions.
    card = Image.new("RGB", (980, 1080), (19, 30, 59))
    card_draw = ImageDraw.Draw(card)
    card_draw.rounded_rectangle((0, 0, 979, 1079), radius=42,
                                fill=(19, 30, 59), outline=(67, 111, 205), width=5)
    px = (980 - pose.width) // 2
    py = (1080 - pose.height) // 2
    card.paste(pose, (px, py))
    image.paste(card, (50, 205))

    # Caption card.
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 1330, WIDTH - 55, 1775), radius=42,
                           fill=(12, 22, 48), outline=(64, 105, 190), width=4)

    lines = wrap_text(draw, text, text_font, 880)
    if len(lines) > 4:
        text_font = get_font(48)
        lines = wrap_text(draw, text, text_font, 880)

    line_height = 76
    total_height = len(lines) * line_height
    y = 1550 - total_height // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=text_font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        draw.text((x + 2, y + 3), line, font=text_font, fill=(2, 5, 15))
        draw.text((x, y), line, font=text_font, fill=(250, 250, 255))
        y += line_height

    draw.text((75, 1820), "THINK  •  LEARN  •  GROW",
              font=label_font, fill=(150, 184, 255))

    path = OUTPUT / f"scene_{index}.png"
    image.save(path)
    return path


async def make_audio(text, index):
    path = OUTPUT / f"audio_{index}.mp3"

    for voice in VOICE_OPTIONS:
        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(path))
                if path.exists() and path.stat().st_size > 1000:
                    return path
            except Exception as error:
                print(f"TTS attempt {attempt + 1} failed for {voice}: {error}")
            await asyncio.sleep(5 * (attempt + 1))

    raise RuntimeError(f"Could not generate audio for scene {index}")


def create_video(scenes, scene_poses=None):
    clips = []
    scene_poses = scene_poses or []

    for i, scene in enumerate(scenes):
        pose_name = scene_poses[i] if i < len(scene_poses) else None
        image = make_scene(scene, i, pose_name)

        audio = asyncio.run(make_audio(scene, i))
        clip = OUTPUT / f"clip_{i}.mp4"

        # Gentle Ken Burns zoom gives the still character artwork movement.
        # Different poses across scenes provide visual variety.
        run([
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(FPS), "-i", str(image),
            "-i", str(audio),
            "-vf",
            "zoompan=z='min(zoom+0.0007,1.045)':"
            "d=180:s=1080x1920:fps=30,"
            "fade=t=in:st=0:d=0.35,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            str(clip)
        ])
        clips.append(clip)

    concat_file = OUTPUT / "clips.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    final_video = OUTPUT / "thought_after_2am.mp4"
    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(final_video)
    ])
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
