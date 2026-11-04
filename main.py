import os, json, math, asyncio, subprocess, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import edge_tts
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(".")
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)
W, H, FPS = 720, 1280, 24
VOICE = "en-US-AndrewNeural"
FALLBACK_VOICE = "en-US-AriaNeural"

def run(cmd):
    subprocess.run(cmd, check=True)

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
    b = draw.textbbox((0,0), s, font=f, stroke_width=0)
    return b[2]-b[0]

def wrap(draw, text, f, maxw):
    lines, line = [], ""
    for word in str(text).split():
        test = (line+" "+word).strip()
        if text_width(draw, test, f) <= maxw:
            line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines or [""]

def topic_kind(text):
    s = text.lower()
    if any(k in s for k in ("brain","mind","memory","psycholog","thought","think","dream")): return "brain"
    if any(k in s for k in ("time","clock","night","sleep","hour","minute","late")): return "time"
    if any(k in s for k in ("music","song","sound","hear","earworm","noise")): return "sound"
    if any(k in s for k in ("light","idea","learn","discover","why","fact","science")): return "idea"
    if any(k in s for k in ("heart","feel","emotion","love","stress","fear","happy")): return "emotion"
    if any(k in s for k in ("phone","screen","social","internet","digital")): return "digital"
    return "concept"

def palette(kind):
    return {
      "brain": ((9,17,45),(73,116,255),(165,111,255)),
      "time": ((10,23,48),(255,185,70),(255,105,105)),
      "sound": ((8,24,48),(54,211,208),(105,126,255)),
      "idea": ((12,21,48),(255,213,91),(72,188,255)),
      "emotion": ((30,14,43),(255,112,153),(255,190,111)),
      "digital": ((7,22,43),(62,206,255),(130,120,255)),
      "concept": ((10,18,42),(90,160,255),(255,193,85)),
    }[kind]

def gradient_bg(kind, t):
    c1, accent, accent2 = palette(kind)
    im = Image.new("RGB",(W,H))
    p=im.load()
    for y in range(H):
        q=y/(H-1)
        for x in range(W):
            glow=max(0,1-math.sqrt(((x-W*.52)/(W*.9))**2+((y-H*.39)/(H*.8))**2))
            wave=(math.sin(x*.012+t*.7)+math.cos(y*.009-t*.5))*.5
            p[x,y]=tuple(max(0,min(255,int(c1[i]+glow*(accent[i]-c1[i])*.18+max(0,wave)*4))) for i in range(3))
    return im

def draw_icon(d, kind, cx, cy, t, a, b):
    pulse=1+.045*math.sin(t*2.7)
    r=int(128*pulse)
    # Halo rings move continuously, avoiding static slide-show imagery.
    for j in range(3):
        rr=r+28+j*34
        phase=t*(.45+j*.11)+j*2
        ox=math.cos(phase)*18
        oy=math.sin(phase)*13
        d.ellipse((cx-rr+ox,cy-rr+oy,cx+rr+ox,cy+rr+oy),outline=(*a,75+j*25),width=3)
    if kind=="brain":
        # stylized brain made from connected rounded lobes
        for dx,dy,rx,ry in [(-45,-8,43,48),(-10,-42,48,43),(35,-20,43,48),(48,25,35,38),(0,35,48,43),(-45,30,35,38)]:
            d.ellipse((cx+dx-rx,cy+dy-ry,cx+dx+rx,cy+dy+ry),fill=(*a,245),outline=(245,248,255,255),width=4)
        d.line((cx,cy-60,cx-3,cy+72),fill=(15,24,55,255),width=5)
        d.arc((cx-48,cy-35,cx+5,cy+28),190,350,fill=(*b,255),width=5)
        d.arc((cx-4,cy-55,cx+52,cy+12),20,170,fill=(*b,255),width=5)
    elif kind=="time":
        d.ellipse((cx-r//2,cy-r//2,cx+r//2,cy+r//2),fill=(18,34,68,255),outline=(*a,255),width=12)
        for i in range(12):
            an=i*math.tau/12
            x1=cx+math.cos(an)*r*.39; y1=cy+math.sin(an)*r*.39
            x2=cx+math.cos(an)*r*.44; y2=cy+math.sin(an)*r*.44
            d.line((x1,y1,x2,y2),fill=(245,248,255,255),width=5)
        d.line((cx,cy,cx-4,cy-r*.27),fill=(255,255,255,255),width=9)
        d.line((cx,cy,cx+r*.22,cy+r*.12),fill=(*b,255),width=8)
        d.ellipse((cx-8,cy-8,cx+8,cy+8),fill=(*a,255))
    elif kind=="sound":
        d.rounded_rectangle((cx-28,cy-65,cx+28,cy+65),radius=25,fill=(*a,255))
        for k in range(1,4):
            off=48*k
            d.arc((cx-off,cy-off*.8,cx+off,cy+off*.8),-65,65,fill=(*b,255),width=8)
            d.arc((cx-off,cy-off*.8,cx+off,cy+off*.8),115,245,fill=(*b,255),width=8)
    elif kind=="idea":
        d.ellipse((cx-65,cy-90,cx+65,cy+40),fill=(*a,255),outline=(255,255,255,255),width=5)
        d.rounded_rectangle((cx-38,cy+22,cx+38,cy+80),radius=12,fill=(*b,255))
        d.line((cx-25,cy+48,cx+25,cy+48),fill=(20,30,60,255),width=5)
        for i in range(8):
            an=i*math.tau/8+t*.15
            x1=cx+math.cos(an)*100; y1=cy+math.sin(an)*120
            x2=cx+math.cos(an)*135; y2=cy+math.sin(an)*155
            d.line((x1,y1,x2,y2),fill=(*a,220),width=6)
    elif kind=="emotion":
        pts=[]
        for i in range(120):
            q=i/119*math.tau
            x=16*math.sin(q)**3
            y=13*math.cos(q)-5*math.cos(2*q)-2*math.cos(3*q)-math.cos(4*q)
            pts.append((cx+x*7,cy-y*7))
        d.polygon(pts,fill=(*a,255),outline=(255,245,255,255))
    elif kind=="digital":
        d.rounded_rectangle((cx-75,cy-125,cx+75,cy+125),radius=24,fill=(17,35,68,255),outline=(*a,255),width=9)
        d.rounded_rectangle((cx-57,cy-102,cx+57,cy+91),radius=12,fill=(*b,180))
        d.ellipse((cx-9,cy+102,cx+9,cy+120),fill=(245,245,255,255))
        for i in range(3):
            yy=cy-50+i*42
            d.rounded_rectangle((cx-35,yy,cx+35,yy+13),radius=6,fill=(255,255,255,230))
    else:
        # rotating geometric concept mark
        for i in range(6):
            an=t*.55+i*math.tau/6
            x=cx+math.cos(an)*82; y=cy+math.sin(an)*82
            rr=24+5*math.sin(t*2+i)
            d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(*a,245),outline=(255,255,255,230),width=3)
        d.ellipse((cx-42,cy-42,cx+42,cy+42),fill=(*b,255),outline=(255,255,255,255),width=5)

def draw_frame(text, kind, frame, total, scene_no):
    t=frame/FPS
    bg=gradient_bg(kind,t).convert("RGBA")
    d=ImageDraw.Draw(bg,"RGBA")
    c1, accent, accent2=palette(kind)
    # Continuous floating particles
    for i in range(38):
        x=(i*97+int(t*(13+i%5)*7))%W
        y=(i*173+int(math.sin(t*.7+i)*35))%H
        rr=2+(i%4)
        d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(*accent,80+(i%3)*35))
    # Top label
    d.rounded_rectangle((34,38,W-34,100),radius=22,fill=(5,12,30,175),outline=(*accent,150),width=2)
    d.text((W//2,69),"THOUGHT AFTER 2AM",font=font(23),fill=(239,244,255,255),anchor="mm")
    # Large animated visual in upper-middle
    draw_icon(d,kind,W//2,410,t,accent,accent2)
    # Topic label above subtitle
    label={"brain":"MIND & BRAIN","time":"TIME & HABITS","sound":"SOUND & MEMORY",
           "idea":"DISCOVER SOMETHING NEW","emotion":"HUMAN EMOTIONS",
           "digital":"DIGITAL LIFE","concept":"THINK ABOUT IT"}[kind]
    d.text((W//2,650),label,font=font(20),fill=(*accent,255),anchor="mm")
    # Centered subtitle block; words reveal progressively with narration.
    words=str(text).split()
    progress=min(1,(frame+1)/max(1,total))
    count=min(len(words),max(1,int(progress*len(words))+1))
    shown=" ".join(words[:count])
    f=font(34)
    lines=wrap(d,shown,f,W-100)
    if len(lines)>4:
        f=font(29); lines=wrap(d,shown,f,W-100)
    line_h=48
    block_h=len(lines)*line_h+54
    top=H//2+95
    # Centered subtitle card with high contrast and safe margins
    d.rounded_rectangle((35,top,W-35,top+block_h),radius=26,
                        fill=(3,9,24,220),outline=(*accent,230),width=3)
    y=top+27+(block_h-54-len(lines)*line_h)//2
    for line in lines:
        d.text((W//2+2,y+3),line,font=f,fill=(0,0,0,255),anchor="mm",stroke_width=2,stroke_fill=(0,0,0,255))
        d.text((W//2,y),line,font=f,fill=(255,255,255,255),anchor="mm",
               stroke_width=1,stroke_fill=(15,20,40,255))
        y+=line_h
    # animated progress line
    prog_w=int((W-70)*progress)
    d.rounded_rectangle((35,H-82,W-35,H-68),radius=7,fill=(70,80,110,130))
    d.rounded_rectangle((35,H-82,35+prog_w,H-68),radius=7,fill=(*accent,255))
    return bg.convert("RGB")

async def tts(text, path):
    for voice in (VOICE,FALLBACK_VOICE):
        try:
            await edge_tts.Communicate(text,voice,rate="+2%").save(str(path))
            if path.exists() and path.stat().st_size>1000: return
        except Exception as e:
            print("TTS retry:",e)
    raise RuntimeError("Text-to-speech failed")

def duration(path):
    v=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration",
      "-of","default=noprint_wrappers=1:nokey=1",str(path)],text=True)
    return max(2,float(v.strip()))

def render_scene(scene,i):
    text=scene.get("text","") if isinstance(scene,dict) else str(scene)
    if not text.strip(): return None
    audio=OUTPUT/f"audio_{i}.mp3"
    asyncio.run(tts(text,audio))
    seconds=duration(audio)
    frames=max(48,math.ceil(seconds*FPS))
    kind=topic_kind(text)
    folder=OUTPUT/f"frames_{i}"
    folder.mkdir(exist_ok=True)
    for n in range(frames):
        draw_frame(text,kind,n,frames,i).save(folder/f"f_{n:05d}.jpg",quality=94,subsampling=0)
    clip=OUTPUT/f"scene_{i}.mp4"
    run(["ffmpeg","-y","-framerate",str(FPS),"-i",str(folder/"f_%05d.jpg"),
         "-i",str(audio),"-vf","scale=1080:1920:flags=lanczos,format=yuv420p",
         "-c:v","libx264","-preset","ultrafast","-crf","18","-c:a","aac","-b:a","192k",
         "-shortest","-movflags","+faststart",str(clip)])
    return clip

def upload(path,data):
    creds=Credentials(token=None,refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
      token_uri="https://oauth2.googleapis.com/token",client_id=os.environ["YOUTUBE_CLIENT_ID"],
      client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
      scopes=["https://www.googleapis.com/auth/youtube.upload"])
    from google.auth.transport.requests import Request
    creds.refresh(Request())
    yt=build("youtube","v3",credentials=creds)
    body={"snippet":{"title":data["title"][:100],"description":data.get("description",""),
      "tags":data.get("tags",[]),"categoryId":"27"},
      "status":{"privacyStatus":"private","selfDeclaredMadeForKids":False}}
    media=MediaFileUpload(str(path),mimetype="video/mp4",resumable=True)
    req=yt.videos().insert(part="snippet,status",body=body,media_body=media)
    resp=None
    while resp is None:
        status,resp=req.next_chunk()
        if status: print("Upload",int(status.progress()*100),"%")
    print("Uploaded video id:",resp["id"])

def main():
    with open("video.json",encoding="utf-8") as f: data=json.load(f)
    scenes=data.get("scenes",[])
    if not scenes: raise ValueError("video.json has no scenes")
    clips=[]
    for i,s in enumerate(scenes):
        c=render_scene(s,i)
        if c: clips.append(c)
    listing=OUTPUT/"concat.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips),encoding="utf-8")
    final=OUTPUT/"thought_after_2am.mp4"
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(listing),"-c","copy",str(final)])
    upload(final,data)

if __name__=="__main__": main()
