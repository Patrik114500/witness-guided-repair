"""Shared style of the paper's figures.

Grey-scale and hatching only, so the figures survive black-and-white print. All sizes are in inches and all fonts
in points at the printed size (the text width of the ESANN template is 4.8 in); images are saved at 600 dpi.
One meaning per fill in every figure:
    GOOD       dark solid   correct, repaired, ours
    OPEN       white        accepted but not shown correct
    BAD        hatched      a correct specification that a repair broke
    PUBLISHED  mid-grey     the published pipeline in a side-by-side comparison
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, os.pardir, "results")

INK = "#111111"      # primary text and marks
INK2 = "#555555"     # secondary text
GRID = "#e6e6e6"
DARK = "#2b2b2b"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 7.2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.7, "axes.axisbelow": True, "axes.edgecolor": "#333333",
    "xtick.major.width": 0.7, "ytick.major.width": 0.7, "xtick.labelsize": 6.8, "ytick.labelsize": 6.8,
    "hatch.linewidth": 0.6, "legend.frameon": False, "legend.fontsize": 6.4,
    "savefig.dpi": 600, "figure.dpi": 150,
})

GOOD = dict(facecolor=DARK, edgecolor=DARK, linewidth=0.6)
OPEN = dict(facecolor="white", edgecolor=INK, linewidth=0.7)
BAD = dict(facecolor="white", edgecolor=INK, linewidth=0.7, hatch="////")
PUBLISHED = dict(facecolor="#a3a3a3", edgecolor="#a3a3a3", linewidth=0.6)
FS_TITLE, FS_LEG, FS_TICK, FS_LAB, FS_NUM = 7.0, 5.8, 6.4, 6.6, 6.0

# model ids of the experiment scripts -> names printed in the figures
SHORT = {
    "claude:claude-opus-5-5": "opus-5-5", "aoai:gpt-6-astra": "gpt-6-astra", "claude:claude-sonnet-4-6": "sonnet-4-6",
    "grok:grok-4.3": "grok-4.3", "qwen2.5-coder:32b": "qwen-coder-32B", "claude:claude-opus-4-6": "opus-4-6",
    "aoai:gpt-5": "gpt-5", "aoai:gpt-5-mini": "gpt-5-mini", "gpt-oss:20b": "gpt-oss-20B",
    "claude:claude-haiku-4-5": "haiku-4-5", "aoai:gpt-4o": "gpt-4o",
}

HALF_WIDTH = 2.35                # width of Fig. 2 and Fig. 3, which stand side by side in the paper
BAR_IN = 0.105                   # default thickness of a bar
BOT_IN, PITCH_IN = 0.42, 0.152   # margin below the axes and default row pitch


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def save(fig, name):
    path = os.path.join(HERE, name)
    fig.savefig(path)
    print("saved", name)
    return path


def bar_figure(n_units, label_in, legend=True, pitch=PITCH_IN, right_in=0.24):
    """A half-width figure with one axes of horizontal bars: the axes are n_units * pitch inches high and the label
    column is label_in inches wide, so rows and bars have a fixed size whatever the number of rows."""
    top = 0.26 if legend else 0.08
    axes_h = n_units * pitch
    height = top + BOT_IN + axes_h
    fig = plt.figure(figsize=(HALF_WIDTH, height))
    fig.height_in, fig.axes_h_in = height, axes_h
    ax = fig.add_axes([label_in / HALF_WIDTH, BOT_IN / height, (HALF_WIDTH - label_in - right_in) / HALF_WIDTH,
                       axes_h / height])
    ax.tick_params(labelsize=FS_TICK)
    ax.tick_params(axis="y", length=0)
    ax.grid(True, axis="x", color=GRID, lw=0.5)
    return fig, ax


def style_axes(ax):
    """Ticks and grid of a bar chart."""
    ax.tick_params(labelsize=FS_TICK)
    ax.tick_params(axis="y", length=0)
    ax.grid(True, axis="x", color=GRID, lw=0.5)


def bar_height(fig, n_units, bar_in=BAR_IN):
    """Height in data units of a bar that is bar_in inches thick."""
    return bar_in / (fig.axes_h_in / float(n_units))


def legend(fig, items):
    """One-line legend at the top left; items = [(style, label), ...]."""
    fig.legend([plt.Rectangle((0, 0), 1, 1, **s) for s, _ in items], [l for _, l in items], loc="upper left",
               bbox_to_anchor=(0.05 / HALF_WIDTH, 1 - 0.04 / fig.height_in), ncol=len(items), fontsize=FS_LEG,
               handlelength=1.2, handletextpad=0.4, columnspacing=1.1, borderaxespad=0.0, borderpad=0.0)


def stack(ax, y, parts, h):
    """Stacked horizontal bar from 0; parts = [(value, style), ...]."""
    left = 0.0
    for v, st in parts:
        if v > 0:
            ax.barh(y, v, h, left=left, zorder=3, **st)
            left += v
    return left


def num_in(ax, x, y, text):
    """Size of a dark bar, printed inside it."""
    ax.text(x, y, text, ha="right", va="center", fontsize=FS_NUM, color="white", fontweight="bold", zorder=5)


def num_out(ax, x, y, text, ha="left", bold=False):
    """Size of a bar, printed next to it."""
    ax.text(x, y, text, ha=ha, va="center", fontsize=FS_NUM + 0.2, color=INK,
            fontweight="bold" if bold else "normal", zorder=5)
