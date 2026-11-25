"""Rescue stage C (NO model calls): score what stages A/B rescued, and re-score accepted records whose
accepted code does not carry the generated ensures verbatim (the spec of record is then what the accepted
program actually states). Same oracle and same determinacy signal as the big run.
Output: /tmp/fix_scores.jsonl (resumable by key)."""
import os, sys, re, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import nl_gated_compare as NG
import det_gate
import fix_harness as H

OUT = os.environ.get("OUT", "/tmp/fix_scores.jsonl")
base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            r = json.loads(l); done.add((r["model"], r["source"], r["task"]))
        except Exception:
            pass
jobs = []
for f in ["/tmp/fix_rescueA.jsonl"] + sorted(glob.glob("/tmp/fix_rescueB_*.jsonl")):
    for l in open(f):
        try:
            r = json.loads(l)
        except Exception:
            continue
        k = (r["model"], r["source"], r["task"])
        if r.get("rescued") and k not in done and k in base:
            jobs.append(("rescue" + r["stage"], k, r["code"]))
            done.add(k)
bad10 = 0
for k, r in base.items():
    if r.get("status") != "accepted" or k in done:
        continue
    code = (r.get("code_attempts") or [{}])[-1].get("code") or ""
    out = str((r.get("code_attempts") or [{}])[-1].get("dafny_out", ""))
    if re.search(r"[1-9]\d*0 errors", out):
        bad10 += 1
        jobs.append(("demote-10errors", k, code)); continue
    gen_ens = V.ensures_list("method _() returns ()\n  " + (r.get("gen_spec") or ""))
    if not H.ensures_present(code, gen_ens):
        jobs.append(("rescore", k, code))
print("jobs:", len(jobs), dict(collections.Counter(j[0] for j in jobs)), "| accepted with a 'N0 errors' verdict:", bad10, flush=True)
lock = threading.Lock(); fo = open(OUT, "a"); st = collections.Counter()


def work(job):
    origin, k, code = job
    r = base[k]
    o = {"model": k[0], "source": k[1], "task": k[2], "origin": origin, "accepted": origin != "demote-10errors"}
    try:
        if o["accepted"]:
            parts = H.task_parts(k[1], k[2])
            sig = V.parse_sig(parts["vc-spec"])
            gen = r.get("gen_spec") or ""
            gen_ens = V.ensures_list("method _() returns ()\n  " + gen)
            verb = H.ensures_present(code, gen_ens)
            o["gen_verbatim"] = verb
            if verb:
                spec = gen
            else:
                ce = H.method_ensures(code, sig[0]) if sig else None
                spec = "\n    ".join("ensures " + e for e in ce) if ce else ""
                o["code_ensures_n"] = len(ce) if ce else 0
            if not spec.strip():
                o["reliable_gt"] = False; o["determinacy"] = 0.0     # verified against no postcondition at all
            else:
                o["reliable_gt"] = NG.reliable_gt(parts, spec)
                try:
                    o["determinacy"] = det_gate.completeness_determinacy(parts, spec)
                except Exception:
                    o["determinacy"] = None
            o["old_reliable_gt"] = r.get("reliable_gt") if r.get("status") == "accepted" else None
    except Exception as e:
        o["error"] = str(e)[:200]
    with lock:
        fo.write(json.dumps(o) + "\n"); fo.flush(); st[(origin, str(o.get("reliable_gt")))] += 1
    return o


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "24"))) as ex:
    list(ex.map(work, jobs))
print("DONE", dict(st), flush=True)
