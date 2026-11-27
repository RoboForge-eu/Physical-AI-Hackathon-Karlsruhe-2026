"""Erzeugt die App-Icons: harness.ico (blau, RF) und fernsteuerung.ico (orange, RF + Funkwellen).

  python icons/make_icons.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = r"C:\Windows\Fonts\bahnschrift.ttf"
S = 1024


def icon(bg, waves):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=bg)
    f = ImageFont.truetype(FONT, 560)
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        pass
    text_y = 610 if waves else 520
    d.text((S // 2, text_y), "RF", font=f, fill="white", anchor="mm")
    if waves:                                   # Funkwellen oben: Fernsteuerung
        cx, cy = S // 2, 330
        d.ellipse((cx - 38, cy - 38, cx + 38, cy + 38), fill="white")
        for r in (120, 210):
            d.arc((cx - r, cy - r, cx + r, cy + r), 220, 320, fill="white", width=48)
    else:                                       # Balken unten: Harness (Werkbank)
        d.rounded_rectangle((250, 800, S - 250, 850), radius=25, fill="white")
    return im


def plattform_icon():
    """Physical AI Harness: dunkle Kachel, gelber Rahmen, 'AI' in Gelb."""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill="#16181b", outline="#e8b230", width=56)
    f = ImageFont.truetype(FONT, 500)
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        pass
    d.text((S // 2, 500), "AI", font=f, fill="#e8b230", anchor="mm")
    d.rounded_rectangle((250, 800, S - 250, 850), radius=25, fill="#e8b230")
    return im


for name, bg, waves in (("harness", "#003399", False), ("fernsteuerung", "#ff6a00", True), ("plattform", None, None)):
    im = plattform_icon() if name == "plattform" else icon(bg, waves)
    im.save(os.path.join(HERE, name + ".ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, name + ".png"))
print("ok")
