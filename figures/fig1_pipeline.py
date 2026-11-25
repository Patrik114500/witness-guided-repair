"""Fig. 1 of the paper: the pipeline in three steps.

    1 specification     the model writes K postconditions from the description, the parser checks them (errors are
                        fed back, at most three times), one determinacy query per candidate ranks them
    2 code loop         the model writes a body for the top-ranked specification with verifier feedback, at most
                        five rounds, strict acceptance without a bypass; if no body verifies, the next candidate
    3 repair by adding  a clause C from one of four proposers; S' = S and C is kept only if a body verifies under
                        it; one S' per accept, a provably determinate one first, otherwise (S, P) stays
Box fills: dark grey is a model call, white is the verifier on a program, light grey is a solver query on the
specification alone. Solid arrows are the flow, dashed ones feedback, dotted ones a retry. No arrow goes back to
the generation of step 1: that would replace S, and only adding keeps a correct specification correct.
The drawing has no data input.
"""
import fig_common as F
from matplotlib.patches import FancyBboxPatch
plt = F.plt

W, H = 4.8, 1.92
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
LLM = dict(facecolor="#bdbdbd", edgecolor=F.INK, linewidth=0.7)
VER = dict(facecolor="white", edgecolor=F.INK, linewidth=0.7)
SOL = dict(facecolor="#ebebeb", edgecolor=F.INK, linewidth=0.7)
FT, FS, FA = 6.4, 5.6, 5.4            # box title, box subtitle, arrow label
CW, GAP, X0 = 1.16, 0.64, 0.02        # column width, gap between columns, left margin
VG = 0.14                             # vertical gap between boxes
TOP = H - 0.25
cols = [X0 + i * (CW + GAP) for i in range(3)]
DASH = (0, (2.6, 1.6))               # feedback: an error message goes back to the model
DOT = (0, (0.7, 1.3))                # retry: the next attempt, without feedback
LW = 0.8


def box(x, ytop, title, sub, style):
    h = 0.30 if not sub else 0.40
    ax.add_patch(FancyBboxPatch((x, ytop - h), CW, h, boxstyle="round,pad=0,rounding_size=0.04", **style))
    if sub:
        ax.text(x + CW / 2, ytop - 0.145, title, ha="center", va="center", fontsize=FT, fontweight="bold", color=F.INK)
        ax.text(x + CW / 2, ytop - 0.285, sub, ha="center", va="center", fontsize=FS, color=F.INK)
    else:
        ax.text(x + CW / 2, ytop - h / 2, title, ha="center", va="center", fontsize=FT, fontweight="bold", color=F.INK)
    return ytop - h


def path(pts, dashed=False, style=None):
    """orthogonal polyline with rounded joints, arrowhead at the end"""
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=F.INK, lw=LW, linestyle=style or (DASH if dashed else "-"),
            solid_joinstyle="round", dash_joinstyle="round", solid_capstyle="butt")
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    ax.annotate("", xy=(x2, y2), xytext=(x2 - (x2 - x1) * 1e-3, y2 - (y2 - y1) * 1e-3),
                arrowprops=dict(arrowstyle="-|>", color=F.INK, lw=LW, mutation_scale=7, shrinkA=0, shrinkB=0))


def label(x, y, text, ha="left", va="center"):
    ax.text(x, y, text, ha=ha, va=va, fontsize=FA, color=F.INK2)


def pair(x, ybot, ytop2, text, style=DASH):
    """forward arrow down and the dashed feedback arrow up between two boxes of one column"""
    xc = x + CW / 2
    path([(xc - 0.16, ybot), (xc - 0.16, ytop2)])
    path([(xc + 0.08, ytop2), (xc + 0.08, ybot)], style=style)
    label(xc + 0.13, (ybot + ytop2) / 2, text)


for x, t in zip(cols, ("1  Specification", "2  Code loop", "3  Repair by adding")):
    ax.text(x, H - 0.04, t, ha="left", va="top", fontsize=F.FS_TITLE, fontweight="bold", color=F.INK)

# 1 specification
x = cols[0]
a1 = box(x, TOP, "write K specs", "from description d", LLM)
a2 = box(x, a1 - VG, "parse", None, VER)
a3 = box(x, a2 - VG, "rank by determinacy", None, SOL)
pair(x, a1, a1 - VG, "errors, ≤ 3")
path([(x + CW / 2, a2), (x + CW / 2, a2 - VG)])
# 2 code loop
x = cols[1]
b1 = box(x, TOP, "write body P", "for the top-ranked S", LLM)
b2 = box(x, b1 - VG, "verify {pre} P {S}", "strict, no bypass", VER)
pair(x, b1, b1 - VG, "≤ 5 rounds")
# 3 repair by adding
x = cols[2]
c1 = box(x, TOP, "propose clause C", "4 proposers, if flagged", LLM)
c2 = box(x, c1 - VG, "S' = S ∧ C", "a body must verify", VER)
c3 = box(x, c2 - VG, "keep one S'", "determinate first, else S", SOL)
pair(x, c1, c1 - VG, "≤ 3 rounds", style=DOT)
path([(x + CW / 2, c2), (x + CW / 2, c2 - VG)])

# between 1 and 2: forward from the ranking to the body; dashed return "no body: next S" into the ranking
r1, l2 = cols[0] + CW, cols[1]
ya3 = (a3 + (a2 - VG)) / 2
path([(r1, ya3 + 0.06), (r1 + 0.22, ya3 + 0.06), (r1 + 0.22, (TOP + b1) / 2), (l2, (TOP + b1) / 2)])
path([(l2, (b1 - VG + b2) / 2), (r1 + 0.42, (b1 - VG + b2) / 2), (r1 + 0.42, ya3 - 0.07), (r1, ya3 - 0.07)], style=DOT)
label(r1 + 0.06, ya3 - 0.155, "next S", ha="left", va="center")
# between 2 and 3: forward "accept (S, P)" from the verifier; dashed return of S' to the verifier (re-verify, else rewrite)
r2, l3 = cols[1] + CW, cols[2]
yb2 = (b1 - VG + b2) / 2
path([(r2, yb2 + 0.07), (r2 + 0.30, yb2 + 0.07), (r2 + 0.30, (TOP + c1) / 2), (l3, (TOP + c1) / 2)])
label(r2 + 0.03, yb2 + 0.145, "accept", ha="left", va="center")
yc2 = (c1 - VG + c2) / 2
path([(l3, yc2), (r2 + 0.46, yc2), (r2 + 0.46, yb2 - 0.07), (r2, yb2 - 0.07)], style=DOT)
label(r2 + 0.03, yb2 - 0.155, "re-verify S'", ha="left", va="center")

# legend
ly = min(a3, b2, c3) - 0.13
items = ((LLM, "model call"), (VER, "verifier (program)"), (SOL, "solver (specification)"))
for xi, (st, lab) in zip((cols[0], cols[0] + 0.83, cols[0] + 2.0), items):
    ax.add_patch(FancyBboxPatch((xi, ly - 0.04), 0.16, 0.08, boxstyle="round,pad=0,rounding_size=0.015", **st))
    ax.text(xi + 0.21, ly, lab, ha="left", va="center", fontsize=FS, color=F.INK)
for xl, st, lab in ((3.38, DASH, "feedback"), (4.12, DOT, "retry")):
    ax.plot([cols[0] + xl, cols[0] + xl + 0.2], [ly, ly], color=F.INK, lw=LW, linestyle=st)
    ax.text(cols[0] + xl + 0.25, ly, lab, ha="left", va="center", fontsize=FS, color=F.INK)

F.save(fig, "fig1_pipeline.png")
