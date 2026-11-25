"""Fig. 3 of the paper: what the four repairs do to the 4500 accepts.

Reads results/repair_funnel_ext.json (written by pipeline/e2e_repair.py on top of pipeline/repair_full.py): the 2625
accepts of the first experiment and the 1875 accepts of the end-to-end runs. Left of zero are the correct
specifications that a repair broke (hatched), right of zero the accepts not shown correct that it repaired (dark).
Only valid changes count: a body verifies under the changed specification without a bypass.

The LLM judge and the determinacy flag run as originally designed, so their proposal replaces the specification.
The proposal of the invariant miner is the specification with the mined clauses conjoined, so it adds by design.
"ours" is step 3 of the pipeline: the proposals of all four proposers enter only as an added clause, one
strengthening per accept, a provably determinate one first.
"""
import fig_common as F

rules = F.load("repair_funnel_ext.json")["rules"]
ROWS = [(0.0, "LLM judge", "LLM judge|replace", False),
        (1.0, "determinacy flag", "determinacy rewrite|replace", False),
        (2.0, "mined invariants", "mined invariants|replace", False),
        (3.45, "ours", "all four proposers|add", True)]
rows = [(y, label, ours, rules[key]["broken"], rules[key]["repaired"]) for y, label, key, ours in ROWS]
units = rows[-1][0] + 1.1

fig, ax = F.bar_figure(units, 0.92, legend=False, right_in=0.12)
h = F.bar_height(fig, units)
ax.spines["left"].set_visible(False)
x_left = -(max(r[3] for r in rows) + 9)
x_right = max(r[4] for r in rows) + 9
u = (x_right - x_left) * 0.012
for y, label, ours, broken, repaired in rows:
    if broken:
        ax.barh(y, -broken, h, zorder=3, **F.BAD)
    if repaired:
        ax.barh(y, repaired, h, zorder=3, **F.GOOD)
    F.num_out(ax, -broken - u, y, "%d" % broken, ha="right", bold=ours)
    F.num_out(ax, repaired + u, y, "%d" % repaired, bold=ours)
ax.axvline(0, color=F.INK, lw=0.8, zorder=4)
ax.set_yticks([r[0] for r in rows])
ax.set_yticklabels([r[1] for r in rows], fontsize=F.FS_TICK)
for tick, r in zip(ax.get_yticklabels(), rows):
    if r[2]:
        tick.set_fontweight("bold")
ax.set_ylim(units - 1.0 + 0.1 + 0.5, -0.55)
ax.set_xlim(x_left, x_right)
ticks = [t for t in range(-100, 101, 20) if x_left + 2 <= t <= x_right - 2]
ax.set_xticks(ticks)
ax.set_xticklabels(["%d" % abs(t) for t in ticks])
for x, ha, text in ((-u * 3.5, "right", "correct ones broken"), (u * 3.5, "left", "repaired")):
    ax.annotate(text, xy=(x, 0), xycoords=("data", "axes fraction"), xytext=(0, -17), textcoords="offset points",
                ha=ha, va="top", fontsize=F.FS_LAB, color=F.INK)

F.save(fig, "fig3_repair.png")
for y, label, ours, broken, repaired in rows:
    print("  %-17s broken %2d, repaired %2d" % (label, broken, repaired))
