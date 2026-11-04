import os
import json
import math
import asyncio
import subprocess
from pathlib import Path

import edge_tts
from mascot_motion import MascotMotion
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(".")
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)

W, H, FPS = 720, 1280, 15
MASCOT_MOTION = MascotMotion(ROOT)

VOICE_OPTIONS = ["en-US-AndrewNeural", "en-US-AriaNeural"]

# Uses the eight pose files already uploaded in assets/.
POSES = [
    "01_main_host.png",
    "02_thinking.png",
    "03_speaking_gesture.png",
    "04_adjusting_sunglasses.png",
    "05_relaxed_pose.png",
    "06_thumbs_up.png",
    "07_explaining.png",
    "08_phone_pose.png",
]

def run(cmd):
    subprocess.run(cmd, check=True)

def get_font(size, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def wrap_text(draw, text, font, max_width):
    lines, current = [], ""
    for word in str(text).split():
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

def asset_path(filename):
    p = ASSETS / filename
    return p if p.exists() else None

def choose_pose(scene, index):
    requested = scene.get("pose") if isinstance(scene, dict) else None
    aliases = {
        "host": "01_main_host.png", "main": "01_main_host.png",
        "thinking": "02_thinking.png", "think": "02_thinking.png",
        "speaking": "03_speaking_gesture.png", "talking": "03_speaking_gesture.png",
        "sunglasses": "04_adjusting_sunglasses.png",
        "relaxed": "05_relaxed_pose.png", "thumbs_up": "06_thumbs_up.png",
        "explaining": "07_explaining.png", "phone": "08_phone_pose.png",
    }
    if requested:
        requested = aliases.get(str(requested).lower(), str(requested))
        if asset_path(requested):
            return requested
    text = str(scene.get("text", "") if isinstance(scene, dict) else scene).lower()
    if any(k in text for k in ("why", "think", "wonder", "question", "mind")):
        candidate = "02_thinking.png"
    elif any(k in text for k in ("tip", "remember", "explain", "because", "first")):
        candidate = "07_explaining.png"
    elif any(k in text for k in ("subscribe", "follow", "like", "thanks")):
        candidate = "06_thumbs_up.png"
    else:
        candidate = POSES[index % len(POSES)]
    return candidate if asset_path(candidate) else "01_main_host.png"

def scene_expression(scene, index):
    if isinstance(scene, dict) and scene.get("expression"):
        return str(scene["expression"]).lower()
    text = str(scene.get("text", "") if isinstance(scene, dict) else scene).lower()
    for keys, value in [
        (("surpris", "unexpected", "shock"), "surprised"),
        (("amazing", "incredible", "excited"), "excited"),
        (("sad", "lonely", "loss"), "sad"),
        (("confus", "unclear"), "confused"),
        (("think", "why", "wonder"), "thinking"),
    ]:
        if any(k in text for k in keys):
            return value
    return "talking" if index % 2 == 0 else "normal"

def draw_background(t):
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        q = y / H
        col = (int(7 + 9*q), int(14 + 14*q), int(35 + 30*q))
        for x in range(W):
            px[x, y] = col
    d = ImageDraw.Draw(im)
    # Moving soft orbital accents.
    for i in range(4):
        x = int(W/2 + math.cos(t*0.55+i*math.pi/2)*300)
        y = int(410 + math.sin(t*0.7+i*math.pi/2)*210)
        r = 8 + int(3*math.sin(t*2+i))
        d.ellipse((x-r,y-r,x+r,y+r), fill=(30,75,135))
    return im

def draw_topic_graphic(draw, text, t):
    low = text.lower()
    if any(k in low for k in ("brain", "mind", "memory", "thought", "think")):
        label, symbol = "THE MIND", "✦"
    elif any(k in low for k in ("time", "night", "sleep", "hour")):
        label, symbol = "TIME", "◷"
    elif any(k in low for k in ("music", "song", "sound", "hear")):
        label, symbol = "SOUND", "♫"
    elif any(k in low for k in ("idea", "learn", "fact", "why")):
        label, symbol = "NEW IDEA", "?"
    else:
        label, symbol = "DID YOU KNOW?", "!"
    cx, cy = W//2, 470
    pulse = 1 + 0.07*math.sin(t*3.0)
    r = int(100*pulse)
    draw.ellipse((cx-r,cy-r,cx+r,cy+r), fill=(19,43,88),
                 outline=(255,194,55), width=7)
    sf = get_font(100)
    bb = draw.textbbox((0,0), symbol, font=sf)
    draw.text((cx-(bb[2]-bb[0])/2,cy-(bb[3]-bb[1])/2-8),
              symbol,font=sf,fill=(255,205,80))
    for i in range(6):
        a = t*0.8 + i*math.tau/6
        x, y = int(cx+160*math.cos(a)), int(cy+135*math.sin(a))
        rr = 11 + int(4*math.sin(t*3+i))
        draw.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(73,145,240))
    f = get_font(30)
    bb = draw.textbbox((0,0),label,font=f)
    draw.text((cx-(bb[2]-bb[0])/2,cy+135),label,font=f,fill=(232,240,255))

def make_frame(text, scene_index, frame_no, total_frames, scene):
    t = frame_no / FPS
    im = draw_background(t)
    d = ImageDraw.Draw(im)

    d.rounded_rectangle((28,25,W-28,91), radius=20,
                        fill=(17,32,70), outline=(66,112,200), width=2)
    d.text((48,42),"THOUGHT AFTER 2AM",font=get_font(24),fill=(235,241,255))
    d.ellipse((W-70,46,W-50,66),fill=(255,197,55))

    # Alternate mascot and motion-graphic scenes unless explicitly overridden.
    scene_type = scene.get("scene_type") if isinstance(scene, dict) else None
    show_mascot = (scene_type == "mascot") if scene_type else (scene_index % 2 == 0)
    if show_mascot:
        pose_file = choose_pose(scene, scene_index)
        p = asset_path(pose_file)
        if p:
            d.rounded_rectangle((35,120,W-35,710),radius=28,
                                fill=(18,30,60),outline=(72,118,210),width=3)
            expression = MASCOT_MOTION.expression_for(
                text, scene.get("expression") if isinstance(scene, dict) else None)
            gesture = MASCOT_MOTION.gesture_for(
                text, scene.get("gesture") if isinstance(scene, dict) else None)
            layered = MASCOT_MOTION.render(
                (W-90,570), t,
                pose_name=scene.get("pose","speaking") if isinstance(scene,dict) else "speaking",
                expression=expression, gesture=gesture)
            if layered is not None:
                im.paste(layered,(45,125),layered)
            else:
                mascot = Image.open(p).convert("RGBA")
                mascot.thumbnail((W-105, 555), Image.Resampling.LANCZOS)
                bob = int(13*math.sin(t*2.5))
                scale = 1 + 0.018*math.sin(t*2.0)
                mascot = mascot.resize((int(mascot.width*scale),int(mascot.height*scale)),
                                       Image.Resampling.LANCZOS)
                mascot = mascot.rotate(1.2*math.sin(t*1.8),
                                       resample=Image.Resampling.BICUBIC, expand=True)
                x = (W-mascot.width)//2
                im.paste(mascot,(x,125+bob),mascot)
            d = ImageDraw.Draw(im)
    else:
        draw_topic_graphic(d, text, t)

    words = str(text).split()
    progress = min(1.0,(frame_no+1)/max(1,total_frames))
    visible_n = min(len(words),max(1,int(progress*len(words))+1))
    visible = " ".join(words[:visible_n])
    f = get_font(34)
    lines = wrap_text(d,visible,f,W-100)
    if len(lines)>4:
        f=get_font(29)
        lines=wrap_text(d,visible,f,W-100)
    top,bottom=825,1195
    d.rounded_rectangle((32,top,W-32,bottom),radius=27,
                        fill=(10,20,46),outline=(67,111,205),width=3)
    line_h=49
    y=top+(bottom-top-len(lines)*line_h)//2
    for line in lines:
        bb=d.textbbox((0,0),line,font=f)
        x=(W-(bb[2]-bb[0]))//2
        d.text((x+2,y+3),line,font=f,fill=(0,0,0))
        d.text((x,y),line,font=f,fill=(250,250,255))
        y+=line_h
    bw=int((W-70)*progress)
    d.rounded_rectangle((35,1230,W-35,1242),radius=6,fill=(38,54,88))
    d.rounded_rectangle((35,1230,35+bw,1242),radius=6,fill=(255,197,55))
    return im

async def make_audio(text,index):
    path=OUTPUT/f"audio_{index}.mp3"
    for voice in VOICE_OPTIONS:
        try:
            await edge_tts.Communicate(text,voice).save(str(path))
            if path.exists() and path.stat().st_size>1000:
                return path
        except Exception as exc:
            print(f"TTS {voice} failed: {exc}")
    raise RuntimeError(f"TTS failed for scene {index}")

def audio_duration(path):
    out=subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",str(path)
    ],text=True)
    return max(2.0,float(out.strip()))

def render_scene(scene,index):
    text=scene.get("text","") if isinstance(scene,dict) else str(scene)
    if not text.strip():
        return None
    audio=asyncio.run(make_audio(text,index))
    duration=audio_duration(audio)
    count=max(30,int(math.ceil(duration*FPS)))
    frame_dir=OUTPUT/f"frames_{index}"
    frame_dir.mkdir(exist_ok=True)
    for n in range(count):
        make_frame(text,index,n,count,scene).save(frame_dir/f"frame_{n:05d}.jpg",quality=88)
    clip=OUTPUT/f"clip_{index}.mp4"
    run([
        "ffmpeg","-y","-framerate",str(FPS),"-i",str(frame_dir/"frame_%05d.jpg"),
        "-i",str(audio),"-vf","scale=1080:1920:flags=lanczos,format=yuv420p",
        "-c:v","libx264","-preset","ultrafast","-c:a","aac","-b:a","128k",
        "-shortest","-movflags","+faststart",str(clip)
    ])
    return clip

def create_video(scenes):
    clips=[]
    for i,scene in enumerate(scenes):
        clip=render_scene(scene,i)
        if clip: clips.append(clip)
    if not clips: raise ValueError("No usable scenes in video.json")
    concat=OUTPUT/"clips.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clips),encoding="utf-8")
    final=OUTPUT/"thought_after_2am.mp4"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(final)])
    return final

def upload_video(video_path,data):
    credentials=Credentials(
        token=None,refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    credentials.refresh(__import__("google.auth.transport.requests",
        fromlist=["Request"]).Request())
    youtube=build("youtube","v3",credentials=credentials)
    body={"snippet":{"title":data["title"][:100],
        "description":data.get("description",""),
        "tags":data.get("tags",[]),"categoryId":"27"},
        "status":{"privacyStatus":"private","selfDeclaredMadeForKids":False}}
    media=MediaFileUpload(str(video_path),mimetype="video/mp4",resumable=True)
    request=youtube.videos().insert(part="snippet,status",body=body,media_body=media)
    response=None
    while response is None:
        status,response=request.next_chunk()
        if status: print(f"Upload progress: {int(status.progress()*100)}%")
    print("Video uploaded:",response["id"])

def main():
    with open("video.json","r",encoding="utf-8") as f: data=json.load(f)
    scenes=data.get("scenes",[])
    if not scenes: raise ValueError("No scenes found in video.json")
    video=create_video(scenes)
    upload_video(video,data)

if __name__=="__main__":
    main()
