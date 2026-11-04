"""Thought After 2AM sprite-based mascot compositor.

Uses the user's individual animation PNGs when present. It is a layered sprite
compositor with expression/gesture swaps and independent head/hand transforms;
it is not a mesh-weighted skeletal rig.
"""
from pathlib import Path
import math
from PIL import Image

class MascotMotion:
    def __init__(self, root="."):
        self.root = Path(root)
        self.search_roots = [
            self.root / "assets",
            self.root / "assets" / "rig",
            self.root / "assets" / "rig_reference",
        ]

    def find(self, *names):
        for folder in self.search_roots:
            for name in names:
                p = folder / name
                if p.exists():
                    return p
        return None

    def open_rgba(self, *names):
        p = self.find(*names)
        if not p:
            return None
        try:
            return Image.open(p).convert("RGBA")
        except Exception:
            return None

    @staticmethod
    def fit(img, max_w, max_h):
        if img is None:
            return None
        img = img.copy()
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        return img

    @staticmethod
    def paste_center(canvas, img, cx, cy):
        if img is not None:
            canvas.alpha_composite(img, (int(cx-img.width/2), int(cy-img.height/2)))

    def render(self, size, t, pose_name="speaking", expression="talking",
               gesture="presenting"):
        W,H=size
        canvas=Image.new("RGBA",(W,H),(0,0,0,0))

        # Use the user's full-body presenting artwork as the base character.
        base=self.open_rgba("full_body_presenting.png","mascot_apose_fullbody.png",
                            "01_main_host.png","full_body_front_reference.png")
        if base is None:
            return None
        base=self.fit(base,int(W*.74),int(H*.94))
        bob=math.sin(t*2.4)*5
        base=base.rotate(math.sin(t*1.5)*0.7,resample=Image.Resampling.BICUBIC,expand=True)
        self.paste_center(canvas,base,W*.50,H*.52+bob)

        # Independent expression/head sprite overlay. Head crops include shoulders,
        # so keep them modest and centered over the base head region.
        face_map={
            "normal":("expression_normal.png","head_normal.png","head_neutral.png"),
            "talking":("expression_talking.png","head_talking.png","head_talking_1.png"),
            "happy":("expression_happy.png","head_happy.png","head_smile.png"),
            "excited":("expression_excited.png","head_happy.png"),
            "surprised":("expression_surprised.png","head_surprised.png","head_open_mouth.png"),
            "shocked":("expression_shocked.png","head_surprised.png"),
            "thinking":("expression_thinking.png","head_thinking.png"),
            "confused":("expression_confused.png","head_anger.png"),
            "sad":("expression_sad.png","head_normal.png"),
            "cool":("expression_cool.png","head_normal.png"),
        }
        face_names=face_map.get(expression,face_map["talking"])
        face=self.open_rgba(*face_names)
        if face:
            face=self.fit(face,int(W*.40),int(H*.31))
            # Small independent head tilt/bob; visual swap is driven by scene expression.
            face=face.rotate(math.sin(t*2.0)*1.8,resample=Image.Resampling.BICUBIC,expand=True)
            self.paste_center(canvas,face,W*.50,H*.245+bob*.45)

        # Gesture sprite overlay: files are standalone illustrated arm/hand cutouts.
        gesture_map={
            "presenting":("arm_gesture_1.png","arm_gesture_2.png"),
            "point":("arm_gesture_2.png","arm_gesture_4.png"),
            "open":("arm_gesture_5.png",),
            "thumbs_up":("expression_cool.png",),
            "phone":("arm_gesture_6.png",),
        }
        gnames=gesture_map.get(gesture,gesture_map["presenting"])
        arm=self.open_rgba(*gnames)
        if arm:
            arm=self.fit(arm,int(W*.42),int(H*.35))
            sway=math.sin(t*3.0)*5
            self.paste_center(canvas,arm,W*.77+sway,H*.49)

        return canvas

    @staticmethod
    def expression_for(text, explicit=None):
        if explicit:
            return str(explicit).lower()
        s=str(text).lower()
        rules=[
            (("surpris","shock","unexpected","wow"),"surprised"),
            (("confus","unclear","strange"),"confused"),
            (("sad","lonely","miss"),"sad"),
            (("think","why","wonder","question","mind"),"thinking"),
            (("amazing","incredible","excited","great"),"excited"),
            (("happy","smile","good news"),"happy"),
        ]
        for words,value in rules:
            if any(w in s for w in words):
                return value
        return "talking"

    @staticmethod
    def gesture_for(text, explicit=None):
        if explicit:
            return str(explicit).lower()
        s=str(text).lower()
        if any(w in s for w in ("point","first","look at","this")):
            return "point"
        if any(w in s for w in ("hello","welcome","open","share")):
            return "open"
        if any(w in s for w in ("phone","call","message")):
            return "phone"
        if any(w in s for w in ("like","subscribe","follow","great")):
            return "thumbs_up"
        return "presenting"
