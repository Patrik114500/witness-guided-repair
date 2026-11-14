# fig23 split: two full-width strips sized to the ESANN column (12.2 cm = 4.8 in)
# so LaTeX does NOT downscale (fonts stay at their point size, unlike a wide canvas).
import os, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIGD = os.environ.get("FIGD", os.path.dirname(os.path.abspath(__file__)))
GREEN, GRAY, RED, ORANGE, BLUE = "#009E73", "#8a8a8a", "#B2182B", "#E69F00", "#0072B2"
plt.rcParams.update({"font.size": 6.4, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 7.4, "axes.titleweight": "bold"})

cells = json.load(open(os.path.join(HERE, "cells.json")))["cells"]
MODELS = [
    ("claude:claude-opus-5-5", "opus-5-5", "opus", "#D55E00", ""),
    ("aoai:gpt-6-astra", "gpt-6-astra", "astra", "#0072B2", ""),
    ("claude:claude-sonnet-4-6", "sonnet-4-6", "sonnet", "#E69F00", ""),
    ("grok:grok-4.3", "grok-4.3", "grok", "#CC79A7", ""),
    ("claude:claude-opus-4-6", "opus-4-6", "opus-4-6", "#994455", "†"),
    ("aoai:gpt-5", "gpt-5", "gpt-5", "#56B4E9", "†"),
    ("aoai:gpt-5-mini", "gpt-5-mini", "5-mini", "#332288", "†"),
    ("qwen2.5-coder:32b", "qwen-coder-32B", "qwen-32B", "#009E73", ""),
    ("gpt-oss:20b", "gpt-oss-20B", "oss-20B", "#555555", "†"),
]
SRC_MARK = {"numpy_simple": "o", "verina": "s", "verified_cogen": "D"}

# ================= figure A: a-c strip (taller, refined) =================
figA = plt.figure(figsize=(4.8, 2.3))
gsA = figA.add_gridspec(1, 3, width_ratios=[1.12, 1.02, 0.96], wspace=0.5,
                        left=0.1, right=0.99, top=0.88, bottom=0.28)

# (a) scatter
ax = figA.add_subplot(gsA[0])
for c in (20, 40, 60):
    xs = np.linspace(max(c, 14), 100, 120)
    ax.plot(xs, 100 * c / xs, ls=":", color="#cccccc", lw=0.8, zorder=1)
for key, lab, sh, col, dag in MODELS:
    for src, mk in SRC_MARK.items():
        d = cells.get("%s|%s" % (key, src))
        if not d or d["relk"] < 8:
            continue
        x = 100 * d["acc"] / d["tot"]; y = 100 * d["rel"] / d["relk"]
        ax.scatter(x, y, s=8 + d["acc"] * 0.4, color=col, marker=mk, alpha=0.78,
                   edgecolor="white", linewidth=0.45, zorder=3)
ax.annotate("", xy=(95, 45), xytext=(76, 61),
            arrowprops=dict(arrowstyle="->", color=RED, lw=0.9))
ax.text(54, 38, "high acc.,\nlow trust", fontsize=5.6, color=RED, ha="center", style="italic")
ax.set_xlabel("acceptance (%)", fontsize=6.8)
ax.set_ylabel("reliable (%)", fontsize=6.8)
ax.set_xlim(10, 102); ax.set_ylim(30, 92)
ax.set_xticks([25, 50, 75, 100]); ax.tick_params(labelsize=5.8)
ax.set_title("(a) acceptance vs trust", fontsize=7.6)

# (b) dumbbell
ax = figA.add_subplot(gsA[1])
drows = []
for key, lab, sh, col, dag in MODELS:
    T = A = RK = RL = 0
    for src in ("numpy_simple", "verina", "verified_cogen"):
        d = cells.get("%s|%s" % (key, src))
        if d:
            T += d["tot"]; A += d["acc"]; RK += d["relk"]; RL += d["rel"]
    if RK < 10:
        continue
    raw = 100 * A / T; corr = raw * (RL / RK)
    drows.append((sh + dag, raw, corr, col))
drows.sort(key=lambda r: r[1])
for i, (lab, raw, corr, col) in enumerate(drows):
    ax.plot([corr, raw], [i, i], color=col, lw=1.7, alpha=0.55, zorder=2)
    ax.scatter([raw], [i], s=20, color=col, zorder=3)
    ax.scatter([corr], [i], s=20, facecolor="white", edgecolor=col, linewidth=1.0, zorder=3)
    ax.text(raw + 3, i, "−%d" % round(raw - corr), fontsize=5.6, va="center", color=RED)
ax.set_yticks(range(len(drows))); ax.set_yticklabels([r[0] for r in drows], fontsize=6.0)
ax.set_xlim(0, 122); ax.set_xlabel("verified-of-attempted (%)", fontsize=6.8)
ax.set_xticks([0, 50, 100]); ax.tick_params(axis="x", labelsize=5.8)
ax.set_title("(b) overstatement", fontsize=7.6)

# (c) heatmap (reliability large, acceptance small)
ax = figA.add_subplot(gsA[2])
SRCS = [("numpy_simple", "np"), ("verina", "ver"), ("verified_cogen", "cog")]
hrows = []
for key, lab, sh, col, dag in MODELS:
    T = A = 0; vals = []
    for sk, _ in SRCS:
        d = cells.get("%s|%s" % (key, sk))
        if d and d["relk"] >= 5:
            vals.append((100 * d["rel"] / d["relk"], 100 * d["acc"] / d["tot"]))
        else:
            vals.append(None)
        if d:
            T += d["tot"]; A += d["acc"]
    if T and any(vals):
        hrows.append((sh + dag, 100 * A / T, vals))
hrows.sort(key=lambda r: -r[1])
cmap = plt.get_cmap("Greens"); norm = mcolors.Normalize(vmin=35, vmax=95)
for i, (lab, accall, vals) in enumerate(hrows):
    for j, v in enumerate(vals):
        if v is None:
            ax.add_patch(plt.Rectangle((j, i), 1, 1, fc="#f2f2f2", ec="white", lw=1.4))
            ax.text(j + 0.5, i + 0.5, "–", ha="center", va="center", fontsize=7, color="#bbb")
        else:
            rel, acc = v
            ax.add_patch(plt.Rectangle((j, i), 1, 1, fc=cmap(norm(rel)), ec="white", lw=1.2))
            ax.text(j + 0.5, i + 0.40, "%.0f" % rel, ha="center", va="center", fontsize=6.4,
                    fontweight="bold", color=("white" if rel > 72 else "#1a4731"))
            ax.text(j + 0.5, i + 0.75, "a%.0f" % acc, ha="center", va="center", fontsize=4.4,
                    color=("#dff0e6" if rel > 72 else "#557a64"))
ax.set_xlim(0, 3); ax.set_ylim(len(hrows), 0)
ax.set_xticks([0.5, 1.5, 2.5]); ax.set_xticklabels([s[1] for s in SRCS], fontsize=5.8)
ax.set_yticks([i + 0.5 for i in range(len(hrows))])
ax.set_yticklabels([r[0] for r in hrows], fontsize=5.8)
ax.tick_params(length=0)
for sp in ax.spines.values():
    sp.set_visible(False)
ax.set_title("(c) reliability %", fontsize=7.6)

handles = [plt.Line2D([], [], marker="o", ls="", ms=4.4, color=col, label=lab + dag)
           for _, lab, sh, col, dag in MODELS]
figA.legend(handles=handles, loc="lower center", ncol=5, fontsize=5.4, frameon=False,
            bbox_to_anchor=(0.5, 0.0), columnspacing=0.55, handletextpad=0.15,
            labelspacing=0.25)
figA.savefig(os.path.join(FIGD, "fig23a_results.png"), dpi=240)
print("saved fig23a_results.png")

# ================= figure B: external pipelines, each at its own gate =======
figB = plt.figure(figsize=(3.7, 2.35))
ax = figB.add_axes([0.13, 0.17, 0.85, 0.72])
xs = [0, 1, 2.6, 3.6]
bw = 0.8
ax.bar(xs[0], 17, bw, color=GREEN); ax.bar(xs[0], 1, bw, bottom=17, color=ORANGE)
ax.bar(xs[1], 19, bw, color=GREEN); ax.bar(xs[1], 1, bw, bottom=19, color=ORANGE)
ax.bar(xs[1], 7, bw, bottom=20, color="#d8d8d8")
ax.bar(xs[2], 103, bw, color="#b9b9b9", hatch="///", edgecolor="white")
ax.bar(xs[3], 80, bw, color=GREEN); ax.bar(xs[3], 33, bw, bottom=80, color=ORANGE)
ax.bar(xs[3], 5, bw, bottom=113, color="#d8d8d8")
for x, tot in ((xs[0], 18), (xs[1], 27), (xs[2], 103), (xs[3], 118)):
    ax.text(x, tot + 3, "%d" % tot, ha="center", fontsize=8.0, fontweight="bold")
ax.text(xs[0], 9, "94%", ha="center", va="center", fontsize=6.8, color="white", fontweight="bold")
ax.text(xs[1], 10, "95%", ha="center", va="center", fontsize=6.8, color="white", fontweight="bold")
ax.text(xs[2], 52, "?", ha="center", va="center", fontsize=12, color="#666", fontweight="bold")
ax.text(xs[3], 40, "71%", ha="center", va="center", fontsize=6.8, color="white", fontweight="bold")
ax.set_xticks(xs)
ax.set_xticklabels(["Clover\ngpt-4o", "ours\ngpt-4o", "Misu\nGPT-4", "ours\nhaiku"],
                   fontsize=7.0)
ax.set_ylim(0, 152); ax.set_xlim(-0.65, 4.25)
ax.set_ylabel("tasks solved", fontsize=7.8); ax.tick_params(axis="y", labelsize=6.8)
ax.text(0.5, 140, "CloverBench (62)", ha="center", fontsize=6.6, color="#666")
ax.text(3.1, 140, "MBPP-DFY (159)", ha="center", fontsize=6.6, color="#666")
hs = [plt.Rectangle((0, 0), 1, 1, color=GREEN), plt.Rectangle((0, 0), 1, 1, color=ORANGE),
      plt.Rectangle((0, 0), 1, 1, color="#b9b9b9", hatch="///")]
ax.legend(hs, ["reliable", "unreliable", "not measured"], fontsize=6.0, frameon=False,
          loc="center left", bbox_to_anchor=(0.30, 0.62), handletextpad=0.3,
          labelspacing=0.3, borderaxespad=0)
figB.savefig(os.path.join(FIGD, "fig23b_results.png"), dpi=240)
print("saved fig23b_results.png")
