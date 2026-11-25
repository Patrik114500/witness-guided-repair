"""Second route to 'correct' for accepts whose entailment lemma S => G does not go through. No model calls.

If the generated postcondition S is provably DETERMINATE and the REVERSE entailment G => S is proved, then S and
the reference G agree wherever the reference is satisfiable: take any output r with S(x, r) and any r' with
G(x, r'); then S(x, r') by the reverse entailment, so r' = r by determinacy, hence G(x, r). So S => G holds on
every input for which the task has a solution at all. A failed forward lemma in that situation is the prover
giving up, not a weak specification.
For every accepted solution with rel == False this script tries the reverse lemma and reports the outcome by
the determinacy of S. Output: /tmp/rev_entail.jsonl"""
import os, sys, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_harness as H
import fix_oracle as O
import fix_state5

NL = chr(10)
S = fix_state5.load5()
tg = [k for k, v in S.items() if v["accepted"] and v["rel"] is False]
refdet = json.load(open("/tmp/ref_det.json")) if os.path.exists("/tmp/ref_det.json") else {}
cert = set(k for k, d in refdet.items() if d == 1.0)
print("accepts not proved to imply the reference: %d" % len(tg), flush=True)
pc = {}


def work(k):
    v = S[k]
    o = {"model": k[0], "source": k[1], "task": k[2], "det": v["det"], "ref_certified": ("%s|%s" % (k[1], k[2])) in cert, "rev": None}
    try:
        t = (k[1], k[2])
        if t not in pc:
            pc[t] = H.task_parts(k[1], k[2])
        parts = pc[t]
        if not O.hdr(parts):
            return o
        s_ens = O.spec_ensures(v["spec"]); g_ens = O.ref_ensures(parts)
        if not s_ens or not g_ens:
            return o
        ok, out = H.dverify2(O.gt_lemma(parts, g_ens, s_ens), 90)      # requires G, ensures S
        if ok:
            o["rev"] = True
        elif out != "TIMEOUT" and ("resolution/type errors" in out or "parse errors" in out):
            o["rev"] = None
        else:
            o["rev"] = False
    except Exception as e:
        o["error"] = str(e)[:160]
    return o


with ThreadPoolExecutor(max_workers=32) as ex:
    res = list(ex.map(work, tg))
with open("/tmp/rev_entail.jsonl", "w") as f:
    for o in res:
        f.write(json.dumps(o) + NL)
for name, flt in [("all tasks", lambda o: True), ("tasks with a provably determinate reference", lambda o: o["ref_certified"])]:
    L = [o for o in res if flt(o)]
    print(name, "| not proved forward:", len(L))
    for d, lab in [(1.0, "S provably determinate"), (0.0, "S not proved determinate"), (None, "S determinacy n/a")]:
        M = [o for o in L if o["det"] == d]
        print("   %-26s n %4d | reverse entailment proved %4d (=> equivalent to the reference when S is determinate), not proved %4d, n/a %3d" % (
            lab, len(M), sum(1 for o in M if o["rev"] is True), sum(1 for o in M if o["rev"] is False), sum(1 for o in M if o["rev"] is None)))
eq = [o for o in res if o["det"] == 1.0 and o["rev"] is True]
print("reclassified as equivalent to the reference: %d ; per model %s" % (len(eq), dict(collections.Counter(o["model"].split(":")[-1] for o in eq))))
