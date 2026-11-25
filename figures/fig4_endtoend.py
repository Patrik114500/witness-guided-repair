"""Fig. 4 of the paper: tasks on which the published pipeline and ours are correct, with the same model.

Reads results/e2e_fig3.json (written by pipeline/e2e_fig3.py). Both bars count correct tasks, that is accepted
programs whose specification provably implies the reference: the published pipeline mid-grey, ours dark. Ours is
the full pipeline, steps 1 to 3.
    CloverBench (62 tasks)   Clover's generators and soundness check against ours, three runs each. A bar counts
                             the tasks that are correct in at least two of the three runs, the thin line spans
                             the three runs.
    MBPP-DFY (159 tasks)     dafny-synthesis, re-run, against ours, one run each. A program of dafny-synthesis
                             with another interface than the task's does not count as correct.
"""
import fig_common as F
plt = F.plt

E3 = F.load("e2e_fig3.json")
MODELS = ["gpt-4o", "gpt-5-mini", "haiku-4-5", "sonnet-4-6"]
CB, MB = E3["CloverBench"], E3["MBPP-DFY"]
RUNS = {m: (CB[m]["clover_before"]["runs"], CB[m]["ours_after"]["runs"]) for m in MODELS}
PANELS = [("CloverBench, 62 tasks", [0, 20, 40, 60], 75,
           [(len(CB[m]["clover_before"]["majority"]), len(CB[m]["ours_after"]["majority"])) for m in MODELS]),
          ("MBPP-DFY, 159 tasks", [0, 50, 100, 150], 188,
           [(MB[m]["baseline_before"]["n"], MB[m]["ours_after"]["n"]) for m in MODELS])]

BAR, INNER, GROUP = 0.075, 0.012, 0.075          # inches: bar thickness, gap inside a pair, gap between pairs
PITCH = 2 * BAR + INNER + GROUP
n = len(MODELS)
LAB, PW, GAP, RIGHT = 0.66, 1.02, 0.20, 0.14     # inches: label column, panel width, gap between panels, right margin
W = LAB + PW + GAP + PW + RIGHT
TOP, BOT = 0.44, 0.42
AH = n * PITCH
H = TOP + BOT + AH
fig = plt.figure(figsize=(W, H))
axs = [fig.add_axes([LAB / W, BOT / H, PW / W, AH / H]), fig.add_axes([(LAB + PW + GAP) / W, BOT / H, PW / W, AH / H])]
h = BAR / PITCH
off = (BAR + INNER) / 2 / PITCH


def number(v):
    return ("%d" % round(v)) if abs(v - round(v)) < 0.05 else ("%.1f" % v)


for pi, (ax, (title, ticks, xmax, vals), x0) in enumerate(zip(axs, PANELS, (LAB, LAB + PW + GAP))):
    F.style_axes(ax)
    for i, (p, o) in enumerate(vals):
        ax.barh(i - off, p, h, zorder=3, **F.PUBLISHED)
        ax.barh(i + off, o, h, zorder=3, **F.GOOD)
        ends = [p, o]
        if pi == 0:
            # range of the three runs: white where the line runs inside the dark bar
            for k, (y, runs) in enumerate(((i - off, RUNS[MODELS[i]][0]), (i + off, RUNS[MODELS[i]][1]))):
                lo, hi = min(runs), max(runs)
                bar = (p, o)[k]
                inner = "white" if k == 1 else F.INK
                col = lambda xv: inner if xv < bar else F.INK
                if lo < bar:
                    ax.plot([lo, min(hi, bar)], [y, y], color=inner, lw=0.7, zorder=4, solid_capstyle="butt")
                if hi > bar:
                    ax.plot([max(lo, bar), hi], [y, y], color=F.INK, lw=0.7, zorder=4, solid_capstyle="butt")
                for xv in (lo, hi):
                    ax.plot([xv, xv], [y - h * 0.32, y + h * 0.32], color=col(xv), lw=0.7, zorder=4)
                ends[k] = max(ends[k], hi)
        ax.text(ends[0] + xmax * 0.018, i - off, number(p), va="center", ha="left", fontsize=F.FS_NUM, color=F.INK2)
        ax.text(ends[1] + xmax * 0.018, i + off, number(o), va="center", ha="left", fontsize=F.FS_NUM, color=F.INK,
                fontweight="bold")
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_xlim(0, xmax)
    ax.set_xticks(ticks)
    ax.set_xlabel("correct tasks", fontsize=F.FS_LAB)
    ax.set_yticks(range(n))
    fig.text(x0 / W, (BOT + AH + 0.06) / H, title, fontsize=F.FS_TITLE, color=F.INK, ha="left", va="bottom")
axs[0].set_yticklabels(MODELS, fontsize=F.FS_TICK)
axs[1].set_yticklabels([])
fig.legend([plt.Rectangle((0, 0), 1, 1, **F.PUBLISHED), plt.Rectangle((0, 0), 1, 1, **F.GOOD)],
           ["published (Clover, dafny-synthesis)", "ours"], loc="upper left", bbox_to_anchor=(0.05 / W, 1 - 0.04 / H),
           ncol=2, fontsize=F.FS_LEG, handlelength=1.2, handletextpad=0.4, columnspacing=1.1, borderaxespad=0.0,
           borderpad=0.0)

F.save(fig, "fig4_endtoend.png")
for title, ticks, xmax, vals in PANELS:
    print("  %s: %s" % (title, ", ".join("%s %s against %s" % (m, number(p), number(o)) for m, (p, o) in zip(MODELS, vals))))
