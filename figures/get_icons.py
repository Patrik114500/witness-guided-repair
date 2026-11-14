"""Download Tabler icons (MIT) as colored SVGs from the Iconify API, convert to transparent PNGs."""
import os, urllib.request
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ICO = os.path.join(HERE, "icons")
os.makedirs(ICO, exist_ok=True)

PROXY = os.environ.get("HTTP_PROXY", "")  # optional
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))

ICONS = {
    "doc":     ("file-description", "444444"),
    "cpu":     ("cpu",              "0072B2"),
    "funnel":  ("filter",           "0072B2"),
    "shield":  ("shield-check",     "0072B2"),
    "award":   ("award",            "1a1a1a"),
    "lens":    ("zoom-check",       "009E73"),
    "scale":   ("scale",            "009E73"),
    "tool":    ("tool",             "E69F00"),
    "signal":  ("antenna-bars-5",   "009E73"),
    "eye":     ("eye",              "777777"),
    "diff":    ("git-compare",      "009E73"),
}

for name, (tabler, color) in ICONS.items():
    svgp = os.path.join(ICO, name + ".svg")
    pngp = os.path.join(ICO, name + ".png")
    url = "https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline/%s.svg" % tabler
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = opener.open(req, timeout=30).read()
        if b"<svg" not in data:
            print(name, "FAILED (no svg)"); continue
        txt = data.decode("utf-8").replace("currentColor", "#" + color)
        open(svgp, "w", encoding="utf-8").write(txt)
        d = svg2rlg(svgp)
        s = 8.0
        d.width, d.height = d.width * s, d.height * s
        d.scale(s, s)
        renderPM.drawToFile(d, pngp, fmt="PNG")
        # white -> transparent
        im = Image.open(pngp).convert("RGBA")
        px = im.getdata()
        im.putdata([(r, g, b, 0) if r > 245 and g > 245 and b > 245 else (r, g, b, a) for (r, g, b, a) in px])
        im.save(pngp)
        print(name, "OK", im.size)
    except Exception as e:
        print(name, "FAILED:", str(e)[:90])
