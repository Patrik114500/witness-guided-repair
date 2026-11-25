"""CloverBench with several models: both pipelines of clover_v2.py scored by one rule. No model calls.
Every accepted record is re-scored with the robust oracle, exactly as strict_reval.py (MODE=clover) does for
the gpt-4o runs: canonical check (the accepted body verifies under the benchmark's own header with the generated
specification, strict verifier) and entailment of the reference specification.
  correct   = accepted, canonical, entailment proved
  not shown = accepted and canonical, entailment not proved; or accepted but not canonical
  n/a       = accepted and canonical, the entailment cannot be posed
Per model and pipeline: the three runs, their mean and range, the tasks correct in at least two runs, and a
paired McNemar test on those. Writes /tmp/clover_multi.jsonl and /tmp/clover_multi_summary.json.
Env: MODELS (tag=model label, comma separated; default the four models), WORKERS."""
import os, sys, json, glob, collections
from math import comb
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/clover")); sys.path.insert(0, os.path.expanduser("~/clover/clover")); sys.path.insert(0, os.path.expanduser("~/clover/shim"))
os.environ.setdefault("MODEL", "none")
import fix_oracle as O
import clover_gated as CG

NL = chr(10)
N = 62
W = int(os.environ.get("WORKERS", "32"))
# label -> {mode: [glob per run]}
SETS = {
    "gpt-4o": {"clover": ["/tmp/clover_v2_clover_c%d_s*.jsonl" % i for i in (1, 2, 3)],
               "ours": ["/tmp/clover_v2_ours_r%d_s*.jsonl" % i for i in (1, 2, 3)]},
}
for lab, tag in [("haiku-4-5", "claude_claude-haiku-4-5"), ("sonnet-4-6", "claude_claude-sonnet-4-6"), ("gpt-5-mini", "aoai_gpt-5-mini")]:
    SETS[lab] = {m: ["/tmp/clover_v3_%s_%s_r%d_s*.jsonl" % (tag, m, i) for i in (1, 2, 3)] for m in ("clover", "ours")}


def jl(p):
    out = []
    for f in sorted(glob.glob(p)):
        for l in open(f):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


pc = {}


def parts_of(task):
    if task not in pc:
        pc[task] = CG.load_task(task)
    return pc[task]


jobs = []; info = {}
for lab, modes in SETS.items():
    for mode, runs in modes.items():
        for ri, pat in enumerate(runs):
            d = {}
            for r in jl(pat):
                d[r["task"]] = r
            info[(lab, mode, ri)] = dict(collections.Counter(str(r.get("status")) for r in d.values()))
            for t, r in d.items():
                jobs.append((lab, mode, ri, r))
print("records: %d" % len(jobs), flush=True)
for k in sorted(info):
    print("   %-11s %-6s run %d: %s" % (k[0], k[1], k[2] + 1, info[k]), flush=True)


def work(x):
    lab, mode, ri, r = x
    o = {"model": lab, "mode": mode, "run": ri, "task": r["task"], "status": r.get("status"), "accepted": r.get("status") == "accepted", "calls": r.get("calls")}
    if o["accepted"]:
        try:
            doc, head, parts = parts_of(r["task"])
            gen = r.get("gen_spec") or ""; code = r.get("code") or ""
            cn, cc = O.canon_check(parts, code, gen)
            rel, rc, _ = O.rel2(parts, gen, code)
            o.update({"canon": cn, "canon_cls": cc, "rel": rel, "rel_cls": rc})
        except Exception as e:
            o["error"] = str(e)[:200]
    return o


with ThreadPoolExecutor(max_workers=W) as ex:
    rows = list(ex.map(work, jobs))
with open("/tmp/clover_multi.jsonl", "w") as f:
    for o in rows:
        f.write(json.dumps(o) + NL)
summ = {}
for lab in SETS:
    summ[lab] = {}
    maj = {}
    for mode in ("clover", "ours"):
        per = []
        for ri in range(3):
            L = [o for o in rows if o["model"] == lab and o["mode"] == mode and o["run"] == ri]
            if not L:
                continue
            acc = [o for o in L if o["accepted"]]
            T = [o for o in acc if o.get("canon") is True and o.get("rel") is True]
            U = [o for o in acc if o.get("canon") is True and o.get("rel") is None]
            F = [o for o in acc if o not in T and o not in U]
            per.append({"records": len(L), "errors": sum(1 for o in L if o["status"] == "error"), "acc": len(acc), "T": len(T), "F": len(F), "U": len(U),
                        "calls": sum(o.get("calls") or 0 for o in L), "Tset": sorted(o["task"] for o in T)})
        if not per:
            continue
        m = lambda key: sum(p[key] for p in per) / float(len(per))
        cnt = collections.Counter(t for p in per for t in p["Tset"])
        maj[mode] = set(t for t, n in cnt.items() if n >= 2)
        summ[lab][mode] = {"runs": len(per), "acc": m("acc"), "correct": m("T"), "not_shown": m("F"), "na": m("U"), "correct_min": min(p["T"] for p in per),
                           "correct_max": max(p["T"] for p in per), "errors": sum(p["errors"] for p in per), "records": [p["records"] for p in per],
                           "calls": sum(p["calls"] for p in per), "majority": len(maj[mode])}
        print("%-11s %-6s runs %d | accepted %.1f | CORRECT %.1f of %d (range %d-%d) | not shown %.1f | n/a %.1f | errors %d | records %s" % (
            lab, mode, len(per), m("acc"), m("T"), N, summ[lab][mode]["correct_min"], summ[lab][mode]["correct_max"], m("F"), m("U"),
            summ[lab][mode]["errors"], [p["records"] for p in per]), flush=True)
    if "clover" in maj and "ours" in maj:
        a, b = len(maj["ours"] - maj["clover"]), len(maj["clover"] - maj["ours"]); n = a + b
        pv = min(1.0, 2.0 * sum(comb(n, k) for k in range(0, min(a, b) + 1)) / (2.0 ** n)) if n else 1.0
        summ[lab]["paired"] = {"ours_only": a, "clover_only": b, "p": pv}
        print("%-11s tasks correct in at least two runs: ours %d, clover %d | only ours %d, only clover %d | McNemar exact p = %.4f" % (
            lab, len(maj["ours"]), len(maj["clover"]), a, b, pv), flush=True)
json.dump(summ, open("/tmp/clover_multi_summary.json", "w"), indent=1)
print("DONE", flush=True)
