"""Rescue stage B (model calls): big-run tasks killed by a harness artifact that stage A could not settle.
  class "empty": the code loop aborted on an empty / timed-out response (reasoning budget, API error);
  class "dup"  : a "Duplicate member name" error replaced the real verifier feedback and dedupe alone
                 did not make any stored attempt verify.
The code stage is re-run from the stored generated spec with the ORIGINAL prompt, ITERS=5, and the fixed
harness (dedupe, robust ask). Nothing else of the pipeline changes.
Env: MODEL, CLASSES (default "empty,dup"), WORKERS, LIMIT, OUT. Resumable by key."""
import os, sys, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H

MODEL = os.environ["MODEL"]
CLASSES = set(os.environ.get("CLASSES", "empty,dup").split(","))
OUT = os.environ.get("OUT", "/tmp/fix_rescueB_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_"))
LIMIT = int(os.environ.get("LIMIT", "0"))
ITERS = int(os.environ.get("ITERS", "5"))
A = {}
for l in open("/tmp/fix_rescueA.jsonl"):
    r = json.loads(l); A[(r["model"], r["source"], r["task"])] = r
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            r = json.loads(l); done.add((r["model"], r["source"], r["task"]))
        except Exception:
            pass
tg = []
for r in H.load_bigrun({MODEL}):
    if r.get("status") != "no-verify":
        continue
    k = (r["model"], r["source"], r["task"])
    if k in done or (k in A and A[k]["rescued"]) or not (r.get("gen_spec") or "").strip():
        continue
    ca = r.get("code_attempts") or []
    cls = "empty" if (ca and not str(ca[-1].get("code") or "").strip()) else ("dup" if k in A else None)
    if cls in CLASSES:
        tg.append((cls, r))
tg.sort(key=lambda x: (x[1].get("spec_syntax_ok") is False, x[1]["source"], x[1]["task"]))
if LIMIT:
    tg = tg[:LIMIT]
print("%s targets: %d %s (already done %d)" % (MODEL, len(tg), dict(collections.Counter(c for c, _ in tg)), len(done)), flush=True)
lock = threading.Lock(); fo = open(OUT, "a"); stat = collections.Counter(); cost = [0.0]


def work(item):
    cls, r = item
    out = {"model": r["model"], "source": r["source"], "task": r["task"], "stage": "B", "class": cls, "rescued": False}
    try:
        parts = H.task_parts(r["source"], r["task"])
        head = V.sig_head(parts["vc-spec"])
        gen = r["gen_spec"]
        asker = H.Asker(MODEL)
        code, att = H.gen_code_fixed(parts, head + "\n    " + gen, asker, iters=ITERS, variant="orig", enforce_ens=None,
                                     guard=os.environ.get("GUARD", "0") == "1")
        out["attempts"] = [{"iter": a["iter"], "verified": a["verified"], "out": a["dafny_out"][-220:]} for a in att]
        out["cost"] = asker.summ()
        if code is not None:
            gen_ens = V.ensures_list("method _() returns ()\n  " + gen)
            out.update({"rescued": True, "iter": att[-1]["iter"], "code": code, "gen_verbatim": H.ensures_present(code, gen_ens)})
    except Exception as e:
        out["error"] = str(e)[:200]
    with lock:
        fo.write(json.dumps(out) + "\n"); fo.flush()
        stat["n"] += 1; stat["rescued"] += bool(out["rescued"]); cost[0] += (out.get("cost") or {}).get("cost_usd", 0)
        print("  %-5s %-36s %s it=%s calls=%s out_tok=%s $%.3f | %d/%d rescued %d cum $%.2f" % (
            cls, r["task"][:36], "RESCUED" if out["rescued"] else "fail   ", out.get("iter"),
            (out.get("cost") or {}).get("calls"), (out.get("cost") or {}).get("tok_out"),
            (out.get("cost") or {}).get("cost_usd", 0), stat["n"], len(tg), stat["rescued"], cost[0]), flush=True)
    return out


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "8"))) as ex:
    list(ex.map(work, tg))
print("DONE %s rescued %d of %d, cost $%.2f" % (MODEL, stat["rescued"], stat["n"], cost[0]), flush=True)
