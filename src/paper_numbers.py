"""Extract the exact numbers for the ESANN paper from the big-run JSONL (snapshot)."""
import json, collections

import glob as _glob
recs = []
_seen = set()
for f in sorted(_glob.glob("/tmp/big_run_*.jsonl")):
    if "apps" in f:
        continue  # the hard-benchmark sample is analysed separately, not in the headline corpus
    try:
        for l in open(f):
            try:
                r = json.loads(l)
                k = (r.get("model"), r.get("source"), r.get("task"))
                if k in _seen:
                    continue  # dedupe (a 2h double-writer window on 2026-11-12 left ~57 dup keys)
                _seen.add(k)
                recs.append(r)
            except: pass
    except: pass

acc = [r for r in recs if r.get("status") == "accepted"]
# merge the witness-arm backfill side-files (later files = fixed reruns, OVERRIDE earlier/inline)
wb = {}
for wf in ["/tmp/witness_backfill.jsonl", "/tmp/witness_backfill_arr.jsonl", "/tmp/witness_backfill_arr2.jsonl"]:
    try:
        for l in open(wf):
            w = json.loads(l); wb[(w["model"], w["source"], w["task"])] = w["arm_witness"]
    except Exception:
        pass
for r in acc:
    k = (r["model"], r["source"], r["task"])
    if k in wb and (("arm_witness" not in r) or wb[k].get("n_rounds", 0) >= r.get("arm_witness", {}).get("n_rounds", 0)):
        r["arm_witness"] = wb[k]
    elif "arm_witness" not in r:
        r["arm_witness"] = {}
kk = [r for r in acc if r.get("reliable_gt") is not None]
out = {"records": len(recs), "accepted": len(acc), "with_gt": len(kk)}

# per model (only models with >=50 records for stability)
bym = collections.defaultdict(lambda: [0, 0, 0])
for r in recs:
    m = r["model"]; bym[m][0] += 1
    if r.get("status") == "accepted":
        bym[m][1] += 1
        if r.get("reliable_gt") is True: bym[m][2] += 1
out["models"] = {m: {"total": t, "acc": a, "rel": rl} for m, (t, a, rl) in bym.items() if t >= 50}

# signals P/R/F1
def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    f = 2 * p * r / (p + r) if p + r else 0
    return round(p, 2), round(r, 2), round(f, 2)

sigs = {}
defs = [("determinacy", lambda r: r.get("signals", {}).get("determinacy") == 0.0,
         lambda r: r.get("signals", {}).get("determinacy") is not None),
        ("perturbation", lambda r: (r.get("signals", {}).get("perturbation_c") or 1) < 0.8,
         lambda r: r.get("signals", {}).get("perturbation_c") is not None),
        ("mutation", lambda r: (r.get("signals", {}).get("mutation_kill") or 1) < 0.8,
         lambda r: r.get("signals", {}).get("mutation_kill") is not None),
        ("invariant", lambda r: r.get("signals", {}).get("invariant") == 0.0,
         lambda r: r.get("signals", {}).get("invariant") is not None),
        ("judge", lambda r: bool(r.get("arm_judge", {}).get("judge_reasoning_round0")) and
         "WEAK" in str(r.get("arm_judge", {}).get("judge_reasoning_round0")).upper().splitlines()[-1],
         lambda r: r.get("arm_judge", {}).get("judge_reasoning_round0") is not None)]
for name, pred, hasv in defs:
    tp = fp = tn = fn = 0
    for r in kk:
        if not hasv(r): continue
        f_ = bool(pred(r)); w = (r["reliable_gt"] is False)
        tp += f_ and w; fp += f_ and not w; tn += (not f_) and (not w); fn += (not f_) and w
    n = tp + fp + tn + fn
    p, rc, f1 = prf(tp, fp, fn)
    sigs[name] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": n,
                  "agree": round((tp + tn) / n, 2) if n else 0, "P": p, "R": rc, "F1": f1}
out["signals"] = sigs

# repair arms
weak = [r for r in kk if r["reliable_gt"] is False]
good = [r for r in kk if r["reliable_gt"] is True]
arms = {}
for a, lab in [("arm_ours", "invariant"), ("arm_judge", "judge"), ("arm_determinacy", "determinacy"),
               ("arm_witness", "witness")]:
    fixed = sum(1 for r in weak if r.get(a, {}).get("reliable_gt_after") is True)
    broke = sum(1 for r in good if r.get(a, {}).get("reliable_gt_after") not in (True, None))
    after = sum(1 for r in kk if r.get(a, {}).get("reliable_gt_after") is True)
    arms[lab] = {"fixed": fixed, "broke": broke, "after": after, "delta": fixed - broke}
out["repair"] = {"weak_before": len(weak), "good_before": len(good), "arms": arms}
out["witness"] = {"activated": sum(1 for r in acc if r.get("arm_witness", {}).get("n_rounds", 0) > 0),
                  "benign_stops": sum(1 for r in acc if r.get("arm_witness", {}).get("benign_nondet"))}

# non-det confound
out["nondet"] = {
    "weak_nondet": sum(1 for r in weak if r.get("meta", {}).get("gt_determinate") is False),
    "weak_total": len(weak),
    "det_fp_nondet": sum(1 for r in good if r.get("signals", {}).get("determinacy") == 0.0
                         and r.get("meta", {}).get("gt_determinate") is False),
    "det_fp_total": sum(1 for r in good if r.get("signals", {}).get("determinacy") == 0.0)}

# per source
bys = collections.defaultdict(lambda: [0, 0])
for r in kk:
    bys[r["source"]][0] += 1
    if r["reliable_gt"] is True: bys[r["source"]][1] += 1
out["sources"] = {s: {"acc": a, "rel": rl} for s, (a, rl) in bys.items()}

json.dump(out, open("/tmp/paper_numbers.json", "w"), indent=1)
print(json.dumps(out, indent=1))
