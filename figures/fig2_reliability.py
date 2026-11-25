"""Fig. 2 of the paper: the accepts of each model, split into correct and not shown correct.

Reads results/bigrun_v7_described.json (written by pipeline/fix_table5.py), view "before": the audited accepts of
the 176 described tasks before any repair. An accept is correct when the generated specification provably implies
the reference. Models are sorted by their number of accepts.

    python fig2_reliability.py         # the figure of the paper
    python fig2_reliability.py all     # the same on all 378 tasks (results/bigrun_v7.json)
"""
import sys

import fig_common as F

ALL = "all" in sys.argv[1:]
d = F.load("bigrun_v7.json" if ALL else "bigrun_v7_described.json")
VIEW = "before"
N = 378 if ALL else 176
models = sorted(d["models"], key=lambda m: -d["models"][m][VIEW]["acc"])
units = len(models) + 0.2

fig, ax = F.bar_figure(units, 0.80, pitch=0.105, right_in=0.12)
h = F.bar_height(fig, units, bar_in=0.078)
for i, m in enumerate(models):
    s = d["models"][m][VIEW]
    F.stack(ax, i, [(s["rel"], F.GOOD), (s["weak"], F.OPEN)], h)
    F.num_in(ax, s["rel"] - N * 0.012, i, "%d" % s["rel"])
ax.set_yticks(range(len(models)))
ax.set_yticklabels([F.SHORT[m] for m in models], fontsize=F.FS_TICK)
ax.set_ylim(len(models) - 0.4, -0.6)
ax.set_xlim(0, N)
ax.set_xticks([0, 100, 200, 300] if ALL else [0, 50, 100, 150])
ax.set_xlabel("tasks (of %d)" % N, fontsize=F.FS_LAB)
F.legend(fig, [(F.GOOD, "correct"), (F.OPEN, "not shown correct")])

F.save(fig, "fig2_reliability%s.png" % ("_all" if ALL else ""))
for m in models:
    s = d["models"][m][VIEW]
    print("  %-16s accepts %3d, correct %3d" % (F.SHORT[m], s["acc"], s["rel"]))
