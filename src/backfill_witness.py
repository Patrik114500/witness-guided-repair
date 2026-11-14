"""Backfill the NEW witness repair arm onto already-collected accepted big-run records.
Reads the big-run JSONLs (which contain gen_spec + the verified code), runs witness_arm with the
record's own model, writes side-file /tmp/witness_backfill.jsonl. Resumable.
Env: FILES (jsonl list), ONLY_MODELS (optional filter), WOUT."""
import os, sys, json
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import big_run as BR

OUT = os.environ.get("WOUT", "/tmp/witness_backfill.jsonl")
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            r = json.loads(l); done.add((r["model"], r["source"], r["task"]))
        except Exception:
            pass
fout = open(OUT, "a")
FILES = os.environ.get("FILES", "/tmp/big_run_local.jsonl,/tmp/big_run_closed.jsonl").split(",")
ONLY = [m for m in os.environ.get("ONLY_MODELS", "").split(",") if m]
ONLY_RT = [t for t in os.environ.get("ONLY_RT", "").split(",") if t]  # e.g. "array<int>,seq<int>,bool"


def rettype_of(parts):
    sig = V.parse_sig(parts["vc-spec"])
    return sig[2][1].replace(" ", "") if sig and sig[2] else None
tot_cost = 0.0
for f in FILES:
    if not os.path.exists(f):
        continue
    for l in open(f):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("status") != "accepted" or not r.get("gen_spec"):
            continue
        key = (r["model"], r["source"], r["task"])
        if key in done:
            continue
        if ONLY and r["model"] not in ONLY:
            continue
        code = None
        for a in r.get("code_attempts", []):
            if a.get("verified"):
                code = a["code"]
        if not code:
            continue
        try:
            parts = V.load(V.BENCH + "/%s/yaml/%s" % (r["source"], r["task"]))
            if ONLY_RT and rettype_of(parts) not in ONLY_RT:
                continue
            head = V.sig_head(parts["vc-spec"])
            tr = BR.Tracker(r["model"])
            arm = BR.witness_arm(parts, head, r["gen_spec"], code, tr)
            cost = tr.summ()
        except Exception as e:
            arm = {"error": str(e)[:200]}; cost = {}
        rec = {"model": r["model"], "source": r["source"], "task": r["task"],
               "reliable_gt_before": r.get("reliable_gt"), "arm_witness": arm, "cost": cost}
        fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(key)
        tot_cost += cost.get("cost_usd", 0)
        print("  %-22s %-26s rounds=%s benign=%s rel %s->%s $%.3f (cum $%.2f)" % (
            r["model"][:22], r["task"].replace("-spec.yaml", "").replace("_task.yaml", "")[:26],
            arm.get("n_rounds"), arm.get("benign_nondet"), r.get("reliable_gt"),
            arm.get("reliable_gt_after"), cost.get("cost_usd", 0), tot_cost), flush=True)
print("DONE backfill total $%.2f" % tot_cost, flush=True)
