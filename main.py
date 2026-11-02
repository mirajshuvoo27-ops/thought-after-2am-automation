
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
OUTPUT.mkdir(exist_ok=True)

WIDTH, HEIGHT = 1080, 1920
VOICE = "en-US-AndrewNeural"


def run(command):
    subprocess.run(command, check=True)


def make_scene(text, index):
    image = Image.new("RGB", (WIDTH, HEIGHT), (12, 17, 35))
    draw = ImageDraw.Draw(image)

    # Background decoration
    for y in range(HEIGHT):
        shade = int(18 + 20 * y / HEIGHT)
        draw.line((0, y, WIDTH, y), fill=(shade, shade + 3, shade + 22))

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 68)
    small = ImageFont.truetype(font_path, 32)

    draw.text((75, 100), "THOUGHT AFTER 2AM",
              font=small, fill=(130, 170, 255))

    words = text.split()
    lines = []
    line = ""

    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] > 900:
            lines.append(line)
            line = word
        else:
            line = test

    if line:
        lines.append(line)

    line_height = 100
    total_height = len(lines) * line_height
    y = (HEIGHT - total_height) // 2

    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (box[2] - box[0])) // 2
        draw.text((x, y), line, font=font, fill="white")
        y += line_height

    draw.text((75, 1770), "FOLLOW FOR MORE",
              font=small, fill=(130, 170, 255))

    path = OUTPUT / f"scene_{index}.png"
    image.save(path)
    return path


async def make_audio(text, index):
    path = OUTPUT / f"audio_{index}.mp3"
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(path))
    return path


def create_video(scenes):
    clips = []

    for i, scene in enumerate(scenes):
        image = make_scene(scene, i)
        audio = OUTPUT / f"audio_{i}.mp3"

        asyncio.run(make_audio(scene, i))

        clip = OUTPUT / f"clip_{i}.mp4"

        run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image),
            "-i", str(audio),
            "-vf",
            "scale=1080:1920,format=yuv420p,fade=t=in:st=0:d=0.4",
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

    with open(concat_file, "w") as f:
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

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
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

    scenes = data["scenes"]

    if not scenes:
        raise ValueError("No scenes found in video.json")

    video = create_video(scenes)
    upload_video(video, data)


if __name__ == "__main__":
    main()

