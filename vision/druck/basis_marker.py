"""Druckvorlage: ArUco-Marker fuer die Roboterbasis (DICT_4X4_50).
ID 10: schwarz 40 mm, Zuschnitt 45 mm  - oben auf die feste Basis kleben.
ID 11: schwarz 60 mm, Zuschnitt 70 mm  - senkrecht hinten auf die Basis (robuster bei wenig Licht).
A4, 600 dpi -> bei 100 % drucken.

  python vision/druck/basis_marker.py
"""
import os, sys
import cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
DPI, ID, SCHWARZ_MM, SCHNITT_MM = 600, 10, 40.0, 45.0


def px(mm):
    return int(round(mm / 25.4 * DPI))


d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
page = Image.new("L", (px(210), px(297)), 255)
dr = ImageDraw.Draw(page)
try:
    font = ImageFont.truetype("arial.ttf", px(3.5))
except OSError:
    font = ImageFont.load_default()

def marker(mid, schwarz, schnitt, x0, y0, zeilen):
    """Marker mit Schnittlinie; Beschriftung RECHTS daneben (nichts im weissen Rand)."""
    m = Image.fromarray(cv2.aruco.generateImageMarker(d, mid, px(schwarz)))
    dr.rectangle([x0, y0, x0 + px(schnitt), y0 + px(schnitt)], outline=170, width=2)
    r = px((schnitt - schwarz) / 2)
    page.paste(m, (x0 + r, y0 + r))
    for k, t in enumerate(zeilen + [f"DICT_4X4_50 · ID {mid}", f"schwarz {schwarz:.0f} mm · Zuschnitt {schnitt:.0f} mm"]):
        dr.text((x0 + px(schnitt) + px(8), y0 + px(2) + k * px(6)), t, font=font, fill=0)
    page.crop((x0 + r, y0 + r, x0 + r + px(schwarz), y0 + r + px(schwarz))).save(
        os.path.join(HERE, f"basis_marker_id{mid}.png"), dpi=(DPI, DPI))

dr.text((px(20), px(15)), "RoboForge - Marker Roboterbasis (Follower). An der grauen Linie ausschneiden, matt drucken.",
        font=font, fill=0)
marker(10, 40, 45, px(25), px(35), ["ID 10: oben auf die feste Basis"])
marker(11, 60, 70, px(25), px(100), ["ID 11: senkrecht hinten auf die Basis"])
ly = px(200)
dr.line([px(25), ly, px(125), ly], fill=0, width=4)
for k in range(11):
    dr.line([px(25 + 10 * k), ly - px(2), px(25 + 10 * k), ly + px(2)], fill=0, width=3)
dr.text((px(25), ly + px(4)), "Pruefen: diese Linie muss genau 100 mm lang sein (Druck auf 100 % / 'Tatsaechliche Groesse')",
        font=font, fill=0)
out = os.path.join(HERE, "basis_marker.pdf")
page.save(out, resolution=DPI)
print(out)
