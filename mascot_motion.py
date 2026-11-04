"""Stable whole-sprite mascot motion.

Important: the uploaded expression/arm/leg PNGs are independent crops without
shared registration coordinates. They must NOT be overlaid on the full-body
mascot. This module therefore animates only complete, aligned character images.
"""
from pathlib import Path
import math
from PIL import Image

class MascotMotion:
    def __init__(self, root="."):
        self.root = Path(root)
        self.asset_dirs = [
            self.root / "assets",
            self.root / "assets" / "rig",
            self.root / "assets" / "rig_reference",
        ]

    def find(self, filename):
        for folder in self.asset_dirs:
            path = folder / filename
            if path.is_file():
                return path
        return None

    def render(self, size, t, pose_file=None, pose_name="speaking",
               expression=None, gesture=None):
        W, H = size
        # Prefer the exact complete pose chosen by main.py.
        candidates = []
        if pose_file:
            candidates.append(pose_file)
        candidates += [
            "full_body_presenting.png",
            "mascot_apose_fullbody.png",
            "01_main_host.png",
            "full_body_front_reference.png",
        ]
        source = next((self.find(n) for n in candidates if self.find(n)), None)
        if source is None:
            return None

        try:
            character = Image.open(source).convert("RGBA")
        except Exception:
            return None

        # Fit the whole character to a consistent stage; no independent crop
        # is placed at arbitrary screen coordinates.
        character.thumbnail((int(W * .84), int(H * .94)), Image.Resampling.LANCZOS)

        # Gentle whole-character idle motion only. The limbs remain in the
        # pose depicted by the source artwork.
        bob = math.sin(t * 2.4) * 5.0
        scale = 1.0 + 0.012 * math.sin(t * 1.8)
        nw, nh = max(1, int(character.width * scale)), max(1, int(character.height * scale))
        character = character.resize((nw, nh), Image.Resampling.LANCZOS)
        angle = math.sin(t * 1.25) * 0.45
        character = character.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        x = (W - character.width) // 2
        y = int((H - character.height) / 2 + bob)
        canvas.alpha_composite(character, (x, y))
        return canvas

    @staticmethod
    def expression_for(text, explicit=None):
        if explicit:
            return str(explicit).lower()
        s = str(text).lower()
        for words, value in [
            (("surpris", "shock", "unexpected", "wow"), "surprised"),
            (("confus", "unclear", "strange"), "confused"),
            (("sad", "lonely", "miss"), "sad"),
            (("think", "why", "wonder", "question", "mind"), "thinking"),
            (("amazing", "incredible", "excited", "great"), "excited"),
            (("happy", "smile", "good news"), "happy"),
        ]:
            if any(word in s for word in words):
                return value
        return "talking"

    @staticmethod
    def gesture_for(text, explicit=None):
        return str(explicit).lower() if explicit else "presenting"
