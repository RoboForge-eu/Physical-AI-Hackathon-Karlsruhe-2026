"""Druckvorlage: 12 grosse ArUco-Marker (DICT_4X4_50), schwarz 60 mm, Zuschnitt 70 mm - wie ID 11 der Basis.
2 A4-Seiten mit je 6 Markern. Standard: je 4x ID 11, 12, 13 (ID 11 = bisheriges Muster, 12/13 = neue Muster).
A4, 600 dpi -> bei 100 % / 'Tatsaechliche Groesse' drucken, matt.

  python vision/druck/marker_bogen.py            -> vision/druck/marker_bogen.pdf
  python vision/druck/marker_bogen.py 11 12 13 14  (eigene IDs, werden reihum auf 12 Plaetze verteilt)
"""
import os, sys
import cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DPI, SCHWARZ, SCHNITT, ANZAHL = 600, 60.0, 70.0, 12


def px(mm):
    return int(round(mm / 25.4 * DPI))


def bogen(ids):
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    try:
        font = ImageFont.truetype("arial.ttf", px(3.2))
    except OSError:
        font = ImageFont.load_default()
    liste = [ids[k % len(ids)] for k in range(ANZAHL)]
    seiten = []
    for s in range(0, ANZAHL, 6):
        page = Image.new("L", (px(210), px(297)), 255)
        dr = ImageDraw.Draw(page)
        dr.text((px(15), px(10)), f"RoboForge - ArUco DICT_4X4_50, schwarz {SCHWARZ:.0f} mm, Zuschnitt {SCHNITT:.0f} mm. "
                f"Seite {s // 6 + 1}/2. Bei 100 % drucken.", font=font, fill=0)
        for k, mid in enumerate(liste[s:s + 6]):
            x0 = px(25 + (k % 2) * (SCHNITT + 20))
            y0 = px(22 + (k // 2) * (SCHNITT + 15))
            dr.rectangle([x0, y0, x0 + px(SCHNITT), y0 + px(SCHNITT)], outline=170, width=2)
            r = px((SCHNITT - SCHWARZ) / 2)
            page.paste(Image.fromarray(cv2.aruco.generateImageMarker(d, int(mid), px(SCHWARZ))), (x0 + r, y0 + r))
            dr.text((x0, y0 + px(SCHNITT) + px(1.5)), f"ID {mid} · 60 mm", font=font, fill=0)
        ly = px(285)
        dr.line([px(25), ly, px(125), ly], fill=0, width=4)
        for t in range(11):
            dr.line([px(25 + 10 * t), ly - px(2), px(25 + 10 * t), ly + px(2)], fill=0, width=3)
        dr.text((px(130), ly - px(2)), "<- muss genau 100 mm sein", font=font, fill=0)
        seiten.append(page)
    out = os.path.join(HERE, "marker_bogen.pdf")
    seiten[0].save(out, resolution=DPI, save_all=True, append_images=seiten[1:])
    return out


if __name__ == "__main__":
    print(bogen([int(a) for a in sys.argv[1:]] or [11, 12, 13]))
