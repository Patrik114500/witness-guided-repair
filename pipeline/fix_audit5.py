"""Audit v5: the specification of record is read from the ACCEPTED PROGRAM, not from the stored generated text.

The specification stage kept only the first line of every ensures clause. When a model wrote a clause over
several lines, the stored text is a truncated copy; a model that then restored the clause in its code was
accepted against the full clause, but scored against the truncated one (ill-formed or weaker). What the
verifier checked is what the program states, so that is the specification of record.
Records whose program states the same ensures as the stored text are copied from /tmp/fix_scores4.jsonl;
the others are re-scored (oracle v4, determinacy, canonical check). Output /tmp/fix_scores5.jsonl with the
specification text. No model calls."""
import os, sys, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_harness as H
import fix_oracle as O
import fix_state

NL = chr(10)
S = fix_state.load()
sc4 = {(r["model"], r["source"], r["task"]): r for r in (json.loads(l) for l in open("/tmp/fix_scores4.jsonl"))}
keys = [k for k, v in S.items() if v["accepted"] and k in sc4]
pc = {}; lock = threading.Lock(); st = collections.Counter()


def parts_of(k):
    t = (k[1], k[2])
    if t not in pc:
        pc[t] = H.task_parts(k[1], k[2])
    return pc[t]


def work(k):
    v = S[k]; r = dict(sc4[k]); parts = parts_of(k)
    stored = O.spec_text(O.spec_ensures(v["spec"]))
    cs = O.code_spec(parts, v["code"])
    r["spec"] = v["spec"]; r["respec"] = False
    if cs is not None and H.nows(cs) != H.nows(stored):
        rel, rc, re_ = O.rel2(parts, cs, v["code"]); det, dc, de_ = O.det2(parts, cs, v["code"]); cn, cc = O.canon_check(parts, v["code"], cs)
        with lock:
            st[("rel", str(r["rel"]), str(rel))] += 1; st[("canon", str(r.get("canon")), str(cn))] += 1
        r.update({"spec": cs, "respec": True, "v4_rel": r["rel"], "v4_det": r["det"], "v4_canon": r.get("canon"),
                  "rel": rel, "rel_cls": rc, "rel_err": re_, "det": det, "det_cls": dc, "det_err": de_, "canon": cn, "canon_cls": cc})
    return r


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "56"))) as ex:
    out = list(ex.map(work, keys))
with open("/tmp/fix_scores5.jsonl", "w") as f:
    for r in out:
        f.write(json.dumps(r) + NL)
print("accepts %d, specification re-read from the program for %d" % (len(out), sum(1 for r in out if r["respec"])))
for k in sorted(st, key=str):
    print("  ", k, st[k])
print("re-read per model:", dict(collections.Counter(r["model"].split(":")[-1] for r in out if r["respec"])))
print("canonical now:", dict(collections.Counter(str(r.get("canon")) + "/" + str(r.get("canon_cls")) for r in out)))
print("rel now:", dict(collections.Counter(str(r["rel"]) for r in out)), "| det:", dict(collections.Counter(str(r["det"]) for r in out)))
