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
