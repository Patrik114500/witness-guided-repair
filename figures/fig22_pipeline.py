# fig22 v3: pipeline diagram with real (Tabler, MIT) icons + header-strip cards.
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

HERE = os.path.dirname(os.path.abspath(__file__))
ICO = os.path.join(HERE, "icons")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fig22_pipeline.png")
BLUE, ORANGE, GREEN, GRAY, RED, INK = "#0072B2", "#E69F00", "#009E73", "#8a8a8a", "#C0392B", "#222222"

fig, ax = plt.subplots(figsize=(11.2, 6.0))
ax.set_xlim(0, 112); ax.set_ylim(0, 60); ax.axis("off")
IMG = {n: mpimg.imread(os.path.join(ICO, n + ".png")) for n in
       ("doc", "cpu", "funnel", "shield", "award", "lens", "scale", "tool", "signal", "eye", "diff")}


def card(x, y, w, h, title, sub, accent, icon=None, hfrac=0.44, tfs=9.0, sfs=7.0, body="#FFFFFF"):
    ax.add_patch(FancyBboxPatch((x+0.45, y-0.45), w, h, boxstyle="round,pad=0.4,rounding_size=1.1",
                                fc="#00000020", ec="none", zorder=1))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.1",
                                fc=body, ec=accent, lw=1.5, zorder=2))
    hh = h * hfrac
    ax.add_patch(FancyBboxPatch((x, y + h - hh), w, hh, boxstyle="round,pad=0.4,rounding_size=1.1",
                                fc=accent, ec=accent, lw=1.5, zorder=3))
    ax.add_patch(Rectangle((x - 0.4, y + h - hh - 0.4), w + 0.8, hh * 0.55 + 0.4,
                           fc=accent, ec="none", zorder=3))
    ax.text(x + w/2, y + h - hh/2 + 0.1, title, ha="center", va="center", fontsize=tfs,
            fontweight="bold", color="white", zorder=5)
    bx = x + (4.6 if icon else 0)
    ax.text(bx + (w - (4.6 if icon else 0))/2, y + (h - hh)/2 - 0.1, sub, ha="center", va="center",
            fontsize=sfs, color="#444", zorder=5)
    if icon is not None:
        ab = AnnotationBbox(OffsetImage(IMG[icon], zoom=0.225), (x + 2.6, y + (h - hh)/2 - 0.55),
                            frameon=False, zorder=5)
        ax.add_artist(ab)


def arrow(p1, p2, color=INK, lw=1.8, style="-|>", z=4):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=14, shrinkA=2, shrinkB=2,
                                 color=color, lw=lw, zorder=z))


def elbow(pts, color, lw=2.0, label=None, lxy=None, lfs=7.8):
    for a, b in zip(pts[:-1], pts[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, lw=lw, zorder=3, solid_capstyle="round")
    arrow(pts[-2], pts[-1], color=color, lw=lw)
    if label:
        ax.text(lxy[0], lxy[1], label, fontsize=lfs, color=color, ha="left", va="center", zorder=5)


# lanes
ax.text(2, 58.7, "GENERATION LOOP", fontsize=10.5, fontweight="bold", color="#444")
ax.text(2, 28.2, "TRUST LAYER", fontsize=10.5, fontweight="bold", color=GREEN)
ax.plot([0, 112], [29.8, 29.8], color=GRAY, lw=0.9, ls=(0, (1, 2)))

# generation row
Y, H = 46, 9.0
card(1.5, Y, 13.5, H, "NL task", "description", "#666666", icon="doc")
card(20, Y, 17.5, H, "spec gen", "LLM postcondition", BLUE, icon="cpu")
card(42.5, Y, 16.5, H, "syntax gate", "Dafny parser", BLUE, icon="funnel")
card(64, Y, 17.5, H, "code gen", "LLM + invariants", BLUE, icon="cpu")
card(86.5, Y, 15.5, H, "verifier", "Dafny / Z3", BLUE, icon="shield")
for x1, x2 in ((15.5, 19.5), (38, 42), (59.5, 63.5), (82, 86)):
    arrow((x1, Y + H*0.28), (x2, Y + H*0.28))
elbow([(48, Y-0.6), (48, 41.4), (30, 41.4), (30, Y-0.6)], RED, lw=1.6,
      label="parse error  ($\\leq$2)", lxy=(32.5, 42.7))
elbow([(93, Y-0.6), (93, 39.8), (74, 39.8), (74, Y-0.6)], RED, lw=1.6,
      label="verifier error  ($\\leq$5)", lxy=(76.5, 41.1))
card(88, 31.2, 19, 7.0, "ACCEPTED", "verified program + spec", INK, icon="award", sfs=6.7)
arrow((100, Y-0.6), (100, 38.7))

# trust layer row
Yt, Ht = 17, 9.2
card(88, Yt, 19, Ht, "key-free signals", "determinacy · perturb\nmutation · invar · judge",
     GREEN, icon="signal", tfs=8.4, sfs=6.4)
arrow((101, 31.0), (99.5, Yt+Ht+0.7), color=GREEN)
card(62, Yt, 20, Ht, "witness", "input $x$: outputs $r_1{\\neq}r_2$\nboth admitted", GREEN,
     icon="lens", sfs=6.7)
arrow((91, 31.0), (76, Yt+Ht+0.7), color=GREEN, lw=2.0)
card(36, Yt, 20, Ht, "NL arbiter", "evidence vs intent:\nambiguity? wrong output?", GREEN, icon="scale", sfs=6.6)
arrow((61.5, Yt+Ht*0.3), (56.6, Yt+Ht*0.3), color=GREEN, lw=2.0)
card(6, Yt, 23.5, Ht, "guarded spec repair", "UNINT: strengthen (monotone)\nWRONG: rewrite from NL+cex",
     ORANGE, icon="tool", tfs=8.4, sfs=6.4)
arrow((35.5, Yt+Ht*0.3), (30.2, Yt+Ht*0.3), color=ORANGE, lw=2.0)
ax.text(32.8, Yt+Ht*0.3+2.0, "UNINT./\nWRONG", fontsize=5.8, color=ORANGE, ha="center", fontweight="bold")

# differential branch (no ambiguity witness -> behavioural check against NL-direct impls)
card(58, 3.6, 26, 7.4, "NL-direct differential", "impls from NL only; disagreement\n$(x,\\,o_{spec},\\,o_{direct})$",
     GREEN, icon="diff", tfs=8.2, sfs=6.4)
arrow((72, Yt-0.6), (72, 11.5), color=GREEN, lw=1.8)
ax.text(73.5, 14.0, "no witness", fontsize=6.2, color=GREEN, ha="left", style="italic")
arrow((58, 8.5), (44, Yt-0.6), color=GREEN, lw=1.8)
ax.text(46.5, 12.3, "disagreement", fontsize=6.2, color=GREEN, ha="left", style="italic")

# INTENDED branch
card(14, 3.6, 17, 6.8, "benign non-det", "keep spec unchanged", "#9a9a9a", sfs=6.8, tfs=8.2)
arrow((40, Yt-0.6), (24, 10.9), color=GRAY, lw=1.8)
ax.text(29.5, 12.0, "INTENDED", fontsize=6.4, color=GRAY, ha="left", fontweight="bold")

# NL intent grounding (dashed): routed along the lane divider into the arbiter's top
elbow([(3.8, Y-0.6), (3.8, 31.1), (46, 31.1), (46, Yt+Ht+0.6)], GREEN, lw=1.1,
      label="intent grounding (NL)", lxy=(20.5, 32.3), lfs=6.4)
for ln in ax.lines[-2:]:
    ln.set_linestyle((0, (3, 2)))

# return path over the top
elbow([(17.5, Yt+Ht+0.7), (17.5, 57.4), (72, 57.4), (72, Y+H+0.7)], ORANGE, lw=2.2,
      label="strengthened spec $\\to$ re-generate + re-verify   (on failure: keep previous accept)",
      lxy=(28, 58.7))

# oracles
card(88, 3.6, 20, 6.8, "eval oracles", "entailment · value-core\n· tests", "#9a9a9a",
     icon="eye", tfs=8.2, sfs=6.4)
ax.text(98, 1.4, "evaluation only — never seen", fontsize=6.4, color=GRAY,
        ha="center", style="italic")

fig.tight_layout(pad=0.3)
fig.savefig(OUT, dpi=200)
print("saved", OUT)
