"""Backfill the DIFFERENTIAL (mis-specification) branch over all accepted big-run records that have
NO ambiguity witness (branch order: witness first). NL-direct impls by the LOCAL model (free);
strong arbiter only on disagreements; guarded rewrite; keep-on-fail. Resumable side-file."""
import os, sys, json, glob
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import nl_gated_compare as NG
import big_run as BR
import misspec_controls as MC

LOCAL = os.environ.get("LOCAL", "qwen2.5-coder:32b")
ARB = os.environ.get("ARBITER", "claude:claude-opus-5-5")
OUT = os.environ.get("WOUT", "/tmp/diff_backfill.jsonl")

# witness side-files overlay (old records)
wb = {}
for wf in ["/tmp/witness_backfill.jsonl", "/tmp/witness_backfill_arr.jsonl", "/tmp/witness_backfill_arr2.jsonl"]:
    try:
        for l in open(wf):
            w = json.loads(l); wb[(w["model"], w["source"], w["task"])] = w["arm_witness"]
    except Exception:
        pass

done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            r = json.loads(l); done.add((r["model"], r["source"], r["task"]))
        except Exception:
            pass
fout = open(OUT, "a")

_files_env = os.environ.get("FILES", "")
if _files_env:
    files = [f for f in _files_env.split(",") if f]
else:
    files = [f for f in sorted(glob.glob("/tmp/big_run_*.jsonl")) if "apps" not in f]
seen = set()
n = 0
for f in files:
    for l in open(f):
        try:
            r = json.loads(l)
        except Exception:
            continue
        key = (r.get("model"), r.get("source"), r.get("task"))
        if key in seen or key in done:
            continue
        seen.add(key)
        if r.get("status") != "accepted" or not r.get("gen_spec"):
            continue
        aw = r.get("arm_witness") or wb.get(key) or {}
        if aw.get("n_rounds", 0) > 0:
            continue  # ambiguity branch has precedence
        code = None
        for a in r.get("code_attempts", []):
            if a.get("verified"):
                code = a["code"]
        if not code:
            code = r.get("code")  # CloverBench records store the verified code directly
        if not code:
            continue
        try:
            if r.get("source"):
                parts = V.load(V.BENCH + "/%s/yaml/%s" % (r["source"], r["task"]))
            else:  # CloverBench record: load via the Clover task loader
                sys.path.insert(0, os.path.expanduser("~/clover"))
                sys.path.insert(0, os.path.expanduser("~/clover/shim"))
                import clover_gated as CG
                t = CG.load_task(r["task"])
                if not t:
                    continue
                parts = t[2]
                r = dict(r); r["source"] = "cloverbench"
            sig = V.parse_sig(parts["vc-spec"])
            if not sig or not sig[2] or sig[2][1].replace(" ", "") not in ("int", "nat", "bool"):
                continue
            head = V.sig_head(parts["vc-spec"])
            trL = BR.Tracker(LOCAL); trA = BR.Tracker(ARB)
            d = MC.differential_arm(parts, head, r["gen_spec"], code, trL, trA)
            rec = {"model": r["model"], "source": r["source"], "task": r["task"],
                   "rel_before": r.get("reliable_gt")}
            rec.update({k: v for k, v in d.items() if k != "rewrite"})
            if d.get("rewrite"):
                c3, _ = BR.gen_code_raw(parts, head + "\n    " + d["rewrite"], trL)
                rec["rewritten"] = True
                rec["reverified"] = c3 is not None
                rec["rel_after"] = NG.reliable_gt(parts, d["rewrite"]) if c3 else None
            rec["cost"] = {"local": trL.summ(), "arb": trA.summ()}
            fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(key); n += 1
            if d.get("disagreement") or n % 20 == 0:
                print("  %-20s %-24s dis=%s arb=%s relB=%s relA=%s (n=%d)" % (
                    r["model"][:20], r["task"][:24], d.get("disagreement"), d.get("arbiter", ""),
                    r.get("reliable_gt"), rec.get("rel_after"), n), flush=True)
        except Exception as e:
            print("  err %s %s" % (r["task"][:20], str(e)[:60]), flush=True)
print("DONE diff backfill: %d records" % n, flush=True)
