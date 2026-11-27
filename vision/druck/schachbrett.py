"""Druckvorlage: Schachbrett fuer die Kamera-Kalibrierung (9 x 6 innere Ecken = 10 x 7 Felder, 25 mm).
A4 quer, 600 dpi -> bei 100 % drucken, flach auf Pappe kleben.

  python vision/druck/schachbrett.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DPI, FELD, NX, NY = 600, 25.0, 10, 7


def px(mm):
    return int(round(mm / 25.4 * DPI))


page = Image.new("L", (px(297), px(210)), 255)
dr = ImageDraw.Draw(page)
x0, y0 = px((297 - NX * FELD) / 2), px(22)
for i in range(NX):
    for j in range(NY):
        if (i + j) % 2 == 0:
            dr.rectangle([x0 + px(i * FELD), y0 + px(j * FELD), x0 + px((i + 1) * FELD) - 1, y0 + px((j + 1) * FELD) - 1],
                         fill=0)
try:
    font = ImageFont.truetype("arial.ttf", px(3.5))
except OSError:
    font = ImageFont.load_default()
dr.text((x0, px(8)), "RoboForge - Kamera-Kalibrierung: 10 x 7 Felder je 25 mm. Bei 100 % drucken, flach auf Pappe kleben.",
        font=font, fill=0)
dr.text((x0, y0 + px(NY * FELD) + px(4)),
        "Pruefen: ein Feld muss genau 25 mm breit sein (die ganze Reihe 250 mm).", font=font, fill=0)
out = os.path.join(HERE, "schachbrett.pdf")
page.save(out, resolution=DPI)
print(out)
