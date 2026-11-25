"""Rescue stage A (NO model calls): big-run tasks that failed with "Duplicate member name".
Re-assemble every stored attempt with dedupe_block() and re-verify. The first attempt that verifies is
the attempt at which the task would have been accepted had the harness not duplicated the helper.
Output: /tmp/fix_rescueA.jsonl (one line per affected task)."""
import os, sys, json, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H

OUT = os.environ.get("OUT", "/tmp/fix_rescueA.jsonl")
LIMIT = int(os.environ.get("LIMIT", "0"))
recs = H.load_bigrun(set(H.P11))
tg = [r for r in recs if r.get("status") == "no-verify"
      and any("Duplicate member name" in str(a.get("dafny_out", "")) for a in (r.get("code_attempts") or []))]
if LIMIT:
    tg = tg[:LIMIT]
print("targets:", len(tg), dict(collections.Counter(r["model"] for r in tg)), flush=True)


def work(r):
    out = {"model": r["model"], "source": r["source"], "task": r["task"], "stage": "A", "rescued": False}
    try:
        parts = H.task_parts(r["source"], r["task"])
        gen_ens = V.ensures_list("method _() returns ()\n  " + (r.get("gen_spec") or ""))
        tried = 0; last = ""
        for a in r["code_attempts"]:
            code = a.get("code") or ""
            if not code.strip():
                continue
            ded = H.dedupe_block(parts, code)
            if ded == code:
                continue
            tried += 1
            ok, err = H.dverify2(V.assemble(parts, ded))
            last = err[-300:]
            if ok and "method" in ded:
                out.update({"rescued": True, "iter": a.get("iter"), "code": ded,
                            "gen_verbatim": H.ensures_present(ded, gen_ens)})
                break
        out["tried"] = tried
        if not out["rescued"]:
            out["last_err"] = last
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


n = 0; resc = collections.Counter(); tot = collections.Counter()
with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "24"))) as ex, open(OUT, "w") as fo:
    for o in ex.map(work, tg):
        fo.write(json.dumps(o) + "\n"); fo.flush()
        n += 1; tot[o["model"]] += 1; resc[o["model"]] += bool(o["rescued"])
        if n % 40 == 0:
            print("  %d/%d rescued so far %d" % (n, len(tg), sum(resc.values())), flush=True)
for m in sorted(tot):
    print("  %-26s dup-failed %3d  rescued by dedupe %3d" % (m, tot[m], resc[m]))
print("DONE rescued %d of %d" % (sum(resc.values()), len(tg)), flush=True)
