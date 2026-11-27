"""Amboss-Logo (RoboForge) fuer den Physical AI Harness: in Gold, scharf in allen Groessen.

  python icons/amboss.py

Quelle: icons/amboss_quelle.jpg (weisser Amboss auf schwarzem Quadrat). Erzeugt:
  icons/plattform.ico            Icon fuer Verknuepfung/Taskleiste (16..256 px, jede Groesse einzeln gerechnet)
  icons/plattform.png            256 px Vorschau
  plattform/static/logo.png      Amboss freigestellt (Gold auf transparent) fuer die Kopfzeile
  plattform/static/icon-*.png    Favicons 32/192/512 + favicon.ico fuer das App-Fenster
"""
import os
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), "plattform", "static")
QUELLE = os.path.join(HERE, "amboss_quelle.jpg")
GOLD_HELL, GOLD_DUNKEL = (246, 201, 82), (201, 143, 32)
GOLD = (232, 178, 48)
KACHEL = (17, 18, 20)
GROSS = 4096                                     # Arbeitsaufloesung (glatte Kanten)


def maske():
    """Weisser Amboss als saubere Maske, eng zugeschnitten, in hoher Aufloesung."""
    im = Image.open(QUELLE).convert("L")
    w, h = im.size
    innen = im.crop((int(w * .16), int(h * .16), int(w * .84), int(h * .84)))   # nur im schwarzen Quadrat
    m = innen.resize((innen.width * 6, innen.height * 6), Image.LANCZOS)
    m = m.filter(ImageFilter.GaussianBlur(3))                                  # JPEG-Kanten glaetten
    m = m.point(lambda v: 255 if v > 128 else 0)                               # harte Kante ...
    m = m.filter(ImageFilter.GaussianBlur(1.2))                                # ... minimal weich
    return m.crop(m.getbbox())


def gold(m, verlauf=True):
    """Maske in Gold einfaerben (leichter Verlauf von oben hell nach unten dunkel)."""
    w, h = m.size
    if verlauf:
        f = Image.new("RGB", (1, h))
        for y in range(h):
            t = y / max(1, h - 1)
            f.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(GOLD_HELL, GOLD_DUNKEL)))
        f = f.resize((w, h))
    else:
        f = Image.new("RGB", (w, h), GOLD)
    out = f.convert("RGBA")
    out.putalpha(m)
    return out


def einpassen(m, groesse, anteil):
    """Maske proportional so skalieren, dass sie 'anteil' der Kachelbreite fuellt."""
    w, h = m.size
    s = groesse * anteil / max(w, h)
    return m.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


def kachel(m, n):
    """App-Icon in n px: dunkle abgerundete Kachel, goldener Amboss. Kleine Groessen: Amboss groesser, kein Rand."""
    k = GROSS // 4                                # 1024 px rechnen, dann auf n verkleinern
    im = Image.new("RGBA", (k, k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rand = 0 if n <= 32 else 24
    d.rounded_rectangle((rand, rand, k - 1 - rand, k - 1 - rand), radius=int(k * .2), fill=KACHEL + (255,))
    if n >= 48:
        d.rounded_rectangle((rand, rand, k - 1 - rand, k - 1 - rand), radius=int(k * .2),
                            outline=GOLD_DUNKEL + (255,), width=max(10, k // 60))
    anteil = .86 if n <= 32 else .74
    a = gold(einpassen(m, k, anteil), verlauf=n >= 48)
    im.alpha_composite(a, ((k - a.width) // 2, (k - a.height) // 2 + k // 40))
    out = im.resize((n, n), Image.LANCZOS)
    if n <= 32:                                   # kleine Groessen etwas nachschaerfen
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=0))
    return out


def main():
    m = maske()
    groessen = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    bilder = [kachel(m, n) for n in groessen]
    bilder[-1].save(os.path.join(HERE, "plattform.ico"), format="ICO",
                    sizes=[(n, n) for n in groessen], append_images=bilder[:-1])
    bilder[-1].save(os.path.join(HERE, "plattform.png"))
    os.makedirs(STATIC, exist_ok=True)
    bilder[-1].save(os.path.join(STATIC, "favicon.ico"), format="ICO",
                    sizes=[(n, n) for n in (16, 24, 32, 48, 64, 256)],
                    append_images=[b for n, b in zip(groessen, bilder) if n in (16, 24, 32, 48, 64)])
    for n in (32, 192, 512):
        kachel(m, n).save(os.path.join(STATIC, f"icon-{n}.png"))
    logo = gold(einpassen(m, 256, 1.0), verlauf=True)      # Kopfzeile: freigestellt, 256 px breit
    logo.save(os.path.join(STATIC, "logo.png"))
    alt = os.path.join(STATIC, "icon.png")
    if os.path.exists(alt):
        os.remove(alt)
    print("ok")


if __name__ == "__main__":
    main()
