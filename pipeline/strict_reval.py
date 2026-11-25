"""Strict re-validation of the accepts behind results 3 and 4 (2026-11-18 late evening). No model calls.

The verifier call used so far read "N verified, 0 errors, K time out" as success. Every accepted program of
the comparison runs is verified again with the strict call (fix_harness.dverify2: an unfinished proof is not
a proof), the same rule for our loop and for the baselines we re-ran.
  MODE=cfs     Dafny given-spec runs      /tmp/cfs2_<model>.jsonl          -> /tmp/strict_cfs.jsonl
  MODE=clover  CloverBench, both pipelines /tmp/clover_v2_<mode>_<rep>_s*   -> /tmp/strict_clover.jsonl
               (also re-scored with the robust oracle: canonical check, entailment, determinacy)
  MODE=mbpp    MBPP-DFY, both pipelines    (acceptance only)                -> /tmp/strict_mbpp.jsonl
"""
import os, sys, re, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_oracle as O

NL = chr(10)
MODE = os.environ.get("MODE", "cfs")
W = int(os.environ.get("WORKERS", "24"))


def jl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def pmap(fn, jobs):
    with ThreadPoolExecutor(max_workers=W) as ex:
        return [r for r in ex.map(fn, jobs) if r is not None]


def dump(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + NL)
    print("wrote %s: %d" % (path, len(rows)), flush=True)


if MODE == "cfs":
    jobs = []
    for f in sorted(glob.glob("/tmp/cfs2_*.jsonl")):
        for r in jl(f):
            jobs.append(r)
    for r in jobs:
        r["accepted"] = bool(r.get("accepted") or r.get("success"))
    print("given-spec records: %d, accepted %d" % (len(jobs), sum(1 for r in jobs if r.get("accepted"))), flush=True)
    if jobs:
        print("fields:", sorted(jobs[0].keys()))

    def work(r):
        o = {"model": r["model"], "source": r["source"], "task": r["task"], "accepted": bool(r.get("accepted")), "strict": False}
        if r.get("accepted") and r.get("code"):
            parts = H.task_parts(r["source"], r["task"])
            ok, out = H.dverify2(V.assemble(parts, r["code"]), 90)
            o["strict"] = ok; o["out"] = "TIMEOUT" if out == "TIMEOUT" else out[-120:]
        return o
    rows = pmap(work, jobs); dump("/tmp/strict_cfs.jsonl", rows)
    c = collections.Counter()
    for o in rows:
        c[(o["model"], o["source"], "n")] += 1; c[(o["model"], o["source"], "accepted")] += o["accepted"]; c[(o["model"], o["source"], "strict")] += o["strict"]
    for m in sorted(set(k[0] for k in c)):
        for s in sorted(set(k[1] for k in c if k[0] == m)):
            print("  %-16s %-14s n %3d accepted %3d strict %3d" % (m, s, c[(m, s, "n")], c[(m, s, "accepted")], c[(m, s, "strict")]))
elif MODE == "clover":
    sys.path.insert(0, os.path.expanduser("~/clover")); sys.path.insert(0, os.path.expanduser("~/clover/clover")); sys.path.insert(0, os.path.expanduser("~/clover/shim"))
    import clover_gated as CG
    jobs = []
    for mode, reps in [("clover", ["c1", "c2", "c3"]), ("ours", ["r1", "r2", "r3"])]:
        for rep in reps:
            d = {}
            for f in sorted(glob.glob("/tmp/clover_v2_%s_%s_s*.jsonl" % (mode, rep))):
                for r in jl(f):
                    d[r["task"]] = r
            for t, r in d.items():
                jobs.append((mode, rep, r))
    print("clover records: %d" % len(jobs), flush=True)

    def work(x):
        mode, rep, r = x
        o = {"mode": mode, "rep": rep, "task": r["task"], "status": r.get("status"), "old_canon": r.get("canon_ok"), "old_rel": r.get("reliable_gt"),
             "old_det": r.get("determinacy"), "accepted": r.get("status") == "accepted"}
        if o["accepted"]:
            try:
                doc, head, parts = CG.load_task(r["task"])
                gen = r.get("gen_spec") or ""; code = r.get("code") or ""
                cn, cc = O.canon_check(parts, code, gen)
                rel, rc, _ = O.rel2(parts, gen, code); det, dc, _ = O.det2(parts, gen, code)
                o.update({"canon": cn, "canon_cls": cc, "rel": rel, "rel_cls": rc, "det": det, "det_cls": dc})
            except Exception as e:
                o["error"] = str(e)[:200]
        return o
    rows = pmap(work, jobs); dump("/tmp/strict_clover.jsonl", rows)
    N = 62; summ = {}
    for mode in ["clover", "ours"]:
        per = []
        for rep in sorted(set(o["rep"] for o in rows if o["mode"] == mode)):
            L = [o for o in rows if o["mode"] == mode and o["rep"] == rep]
            acc = [o for o in L if o["accepted"]]; valid = [o for o in acc if o.get("canon") is True]
            T = [o for o in valid if o.get("rel") is True]; F = [o for o in valid if o.get("rel") is False]; U = [o for o in valid if o.get("rel") is None]
            cert = [o for o in valid if o.get("det") == 1.0]; cT = [o for o in cert if o.get("rel") is True]
            oT = sum(1 for o in acc if o.get("old_canon") and o.get("old_rel") is True)
            per.append({"rep": rep, "acc": len(acc), "valid": len(valid), "T": len(T), "F": len(F), "U": len(U), "cert": len(cert), "cT": len(cT), "old_T": oT,
                        "Tset": sorted(o["task"] for o in T)})
            print("  %-6s %s accepted %2d | strict valid %2d | correct %2d (was %2d) weak %2d not assessable %2d | certified %2d of which correct %2d" % (
                mode, rep, len(acc), len(valid), len(T), oT, len(F), len(U), len(cert), len(cT)))
        m = lambda key: sum(p[key] for p in per) / max(1, len(per))
        summ[mode] = {"runs": len(per), "acc": m("acc"), "valid": m("valid"), "correct": m("T"), "weak": m("F"), "unsc": m("U"), "invalid": m("acc") - m("valid"),
                      "correct_min": min(p["T"] for p in per), "correct_max": max(p["T"] for p in per), "cert": m("cert"), "cert_correct": m("cT"),
                      "precision": 100.0 * m("T") / max(1e-9, m("acc")), "old_correct": m("old_T"), "per_run": per}
        print("MEAN %-6s accepted %.1f valid %.1f CORRECT %.1f of %d (was %.1f) weak %.1f n/a %.1f precision %.1f%% certified %.1f (correct %.1f)" % (
            mode, summ[mode]["acc"], summ[mode]["valid"], summ[mode]["correct"], N, summ[mode]["old_correct"], summ[mode]["weak"], summ[mode]["unsc"],
            summ[mode]["precision"], summ[mode]["cert"], summ[mode]["cert_correct"]))
    # paired: majority-correct per task
    maj = {}
    for mode in ["clover", "ours"]:
        cnt = collections.Counter(t for p in summ[mode]["per_run"] for t in p["Tset"])
        maj[mode] = set(t for t, n in cnt.items() if n >= 2)
    print("majority-correct tasks: ours %d, clover %d ; ours only %d, clover only %d" % (len(maj["ours"]), len(maj["clover"]), len(maj["ours"] - maj["clover"]), len(maj["clover"] - maj["ours"])))
    summ["majority"] = {"ours": len(maj["ours"]), "clover": len(maj["clover"]), "ours_only": len(maj["ours"] - maj["clover"]), "clover_only": len(maj["clover"] - maj["ours"])}
    json.dump(summ, open("/tmp/strict_clover_summary.json", "w"), indent=1)
else:
    files = [x for x in os.environ.get("FILES", "/tmp/mbpp_boost_full.jsonl,/tmp/mbpp_boost.jsonl,/tmp/mbpp_ours.jsonl,/tmp/mbpp_ours2.jsonl,/tmp/mbpp_boost_full2.jsonl,/tmp/mbpp_repro_haiku.jsonl").split(",") if os.path.exists(x)]
    jobs = []
    for f in files:
        for r in jl(f):
            jobs.append((os.path.basename(f), r))
    print("mbpp records: %d in %d files" % (len(jobs), len(files)), flush=True)

    def work(x):
        fn, r = x
        o = {"file": fn, "task": r.get("task"), "status": r.get("status"), "accepted": r.get("status") == "accepted", "reliable_gt": r.get("reliable_gt"), "strict": False}
        if o["accepted"]:
            code = r.get("code") or ((r.get("attempts") or [{}])[-1].get("code")) or ""
            ok, out = H.dverify2(code, 90)
            o["strict"] = ok; o["out"] = "TIMEOUT" if out == "TIMEOUT" else out[-120:]
        return o
    rows = pmap(work, jobs); dump("/tmp/strict_mbpp.jsonl", rows)
    for fn in sorted(set(o["file"] for o in rows)):
        L = [o for o in rows if o["file"] == fn]; acc = [o for o in L if o["accepted"]]; sa = [o for o in acc if o["strict"]]
        print("  %-28s records %3d accepted %3d strict %3d | correct (stored oracle) %3d -> among strict %3d | wrong %3d -> %3d | n/a %3d -> %3d" % (
            fn, len(L), len(acc), len(sa), sum(1 for o in acc if o["reliable_gt"] is True), sum(1 for o in sa if o["reliable_gt"] is True),
            sum(1 for o in acc if o["reliable_gt"] is False), sum(1 for o in sa if o["reliable_gt"] is False),
            sum(1 for o in acc if o["reliable_gt"] is None), sum(1 for o in sa if o["reliable_gt"] is None)))
print("DONE", MODE, flush=True)
