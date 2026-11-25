"""Figure 3 with the full pipeline (2026-11-20): our end-to-end accepts plus step 3, repair
by adding (all four proposers, one strengthening per accept, determinate first, no reference), from e2e_repair.py.
A task counts as correct when it was correct before or the repair made it provably correct; the rule cannot break a
correct one. Also: the published pipelines' accepts with our repair (for the text), and the model calls.
CloverBench: per run, mean over the three runs, and the tasks correct in at least two runs for the paired test, as
clover_multi_score.py. MBPP-DFY: one run.
Reads /tmp/e2e_rep_*.jsonl, /tmp/clover_multi_summary.json, /tmp/mbpp_multi_summary.json.
Writes /tmp/e2e_fig3.json."""
import json, glob, collections
from math import comb

rows = []
for f in sorted(glob.glob("/tmp/e2e_rep_*.jsonl")):
    for l in open(f):
        o = json.loads(l)
        if o.get("status") == "ok":
            rows.append(o)
CLS = json.load(open("/tmp/clover_multi_summary.json"))
MBS = json.load(open("/tmp/mbpp_multi_summary.json"))
MODELS = ["gpt-4o", "gpt-5-mini", "haiku-4-5", "sonnet-4-6"]


def sign_p(a, b):
    n = a + b
    return min(1.0, 2.0 * sum(comb(n, k) for k in range(0, min(a, b) + 1)) / (2.0 ** n)) if n else 1.0


out = {"CloverBench": {}, "MBPP-DFY": {}}
correct = collections.defaultdict(set)      # (dataset, label, pipeline, run, "before"/"after") -> tasks
calls = collections.Counter()
for o in rows:
    ds, lab, pipe, run, task = o["dataset"], o["label"], o["pipeline"], o["run"], o["task"]
    r = o["rows"]["all|add"]
    before = o["before"] is True
    after = before or (r[0] and r[1] is True)
    if before:
        correct[(ds, lab, pipe, run, "before")].add(task)
    if after:
        correct[(ds, lab, pipe, run, "after")].add(task)
    calls[(ds, lab, pipe)] += o["cost_arms"].get("calls", 0) + o["cost_witness"].get("calls", 0)
for lab in MODELS:
    # CloverBench: three runs per pipeline
    d = {}
    for pipe in ("clover", "ours"):
        for st in ("before", "after"):
            per = [len(correct[("CloverBench", lab, pipe, ri, st)]) for ri in range(3)]
            cnt = collections.Counter(t for ri in range(3) for t in correct[("CloverBench", lab, pipe, ri, st)])
            d["%s_%s" % (pipe, st)] = {"mean": sum(per) / 3.0, "runs": per, "majority": sorted(t for t, n in cnt.items() if n >= 2)}
        d[pipe + "_pipeline_calls"] = CLS[lab][pipe]["calls"]
        d[pipe + "_repair_calls"] = calls[("CloverBench", lab, pipe)]
    a = set(d["ours_after"]["majority"]); b = set(d["clover_before"]["majority"])
    d["paired_after"] = {"ours_only": len(a - b), "clover_only": len(b - a), "p": sign_p(len(a - b), len(b - a))}
    out["CloverBench"][lab] = d
    # MBPP-DFY: one run per pipeline
    d = {}
    for pipe in ("baseline", "ours"):
        for st in ("before", "after"):
            d["%s_%s" % (pipe, st)] = {"n": len(correct[("MBPP-DFY", lab, pipe, 0, st)]), "tasks": sorted(correct[("MBPP-DFY", lab, pipe, 0, st)])}
        d[pipe + "_pipeline_calls"] = MBS["runs"][pipe + "@" + lab]["calls"]
        d[pipe + "_repair_calls"] = calls[("MBPP-DFY", lab, pipe)]
        d[pipe + "_fig3_correct"] = MBS[pipe + "@" + lab]["proof"]["correct"]
    a = set(d["ours_after"]["tasks"]); b = set(d["baseline_before"]["tasks"])
    d["paired_after"] = {"ours_only": len(a - b), "baseline_only": len(b - a), "p": sign_p(len(a - b), len(b - a))}
    out["MBPP-DFY"][lab] = d
pool = {}
for ds, key, other in (("CloverBench", "clover_only", "clover"), ("MBPP-DFY", "baseline_only", "baseline")):
    A = sum(out[ds][m]["paired_after"]["ours_only"] for m in MODELS); B = sum(out[ds][m]["paired_after"][key] for m in MODELS)
    pool[ds] = {"ours_only": A, other + "_only": B, "p": sign_p(A, B)}
out["pooled_after"] = pool
json.dump(out, open("/tmp/e2e_fig3.json", "w"), indent=1)
for lab in MODELS:
    c = out["CloverBench"][lab]; m = out["MBPP-DFY"][lab]
    print("%-11s Clover %.1f (+our repair %.1f) | ours %.1f -> %.1f  calls pipe %d + repair %d | paired %s" % (
        lab, c["clover_before"]["mean"], c["clover_after"]["mean"], c["ours_before"]["mean"], c["ours_after"]["mean"],
        c["ours_pipeline_calls"], c["ours_repair_calls"], c["paired_after"]))
    print("%-11s dafny-syn %d (+our repair %d) | ours %d -> %d (fig3 %d)  calls pipe %d + repair %d | paired %s" % (
        "", m["baseline_before"]["n"], m["baseline_after"]["n"], m["ours_before"]["n"], m["ours_after"]["n"], m["ours_fig3_correct"],
        m["ours_pipeline_calls"], m["ours_repair_calls"], m["paired_after"]))
print("pooled:", pool)
