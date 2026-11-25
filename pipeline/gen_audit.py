"""Reference-free audit of the GENERATED specifications behind every accept of the end-to-end big run.

"S does not imply the reference" has two weaknesses as a measure: it needs a reference that is itself complete,
and a failed proof is not a proof of weakness. This audit asks the same question the given-spec audit asks of
the benchmarks (given_audit.py), now of the model-written postcondition S of each accepted solution, and every
positive answer is a PROOF:
  D  determinate    : S admits at most one output per input (already in the state: det == 1.0)
  A  unconstrained  : if S accepts one output it accepts every output of the type
  B  shape only     : if S accepts one output it accepts every output of the same length
  T  trivial program: a body that ignores the task verifies under the benchmark's header with S,
                      and the SAME body does not verify against the benchmark's reference postcondition
                      (so the task is not one that a constant solves)
"provably too weak" = A or B or T. No model call, no use of the reference except to exclude trivial tasks.
State: fix_state5.load5() (audited accepts, before repair). Output: /tmp/gen_audit.jsonl"""
import os, sys, re, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import vericode_compete as V
import fix_harness as H
import fix_oracle as O
import fix_state5
import given_audit as G

NL = chr(10)
S = fix_state5.load5()
acc = [k for k, v in S.items() if v["accepted"]]
print("accepted solutions: %d" % len(acc), flush=True)
pc = {}; gcache = {}; lock = threading.Lock(); n = [0]


def parts_of(k):
    t = (k[1], k[2])
    if t not in pc:
        pc[t] = H.task_parts(k[1], k[2])
    return pc[t]


def prog(parts, ens, st):
    return O.head(parts) + NL + "    " + O.spec_text(ens) + NL + "{" + NL + "  " + st + NL + "}" + NL


def passes_reference(k, parts, h, lab, st):
    """does the same task-ignoring body verify against the benchmark's own postcondition?"""
    key = (k[1], k[2], lab)
    with lock:
        if key in gcache:
            return gcache[key]
    ok, _ = H.dverify2(V.assemble(parts, prog(parts, h["ensures"], st)), 90) if h["ensures"] else (True, "")
    with lock:
        gcache[key] = bool(ok)
    return bool(ok)


def work(k):
    v = S[k]; o = {"model": k[0], "source": k[1], "task": k[2], "rel": v["rel"], "det": v["det"]}
    try:
        parts = parts_of(k); h = O.hdr(parts)
        if not h or not h["rets"] or h["modifies"]:
            o["cls"] = "n/a"; return o
        ens = O.spec_ensures(v["spec"])
        if v["det"] == 1.0:
            o["cls"] = "determinate"; return o
        if not ens:
            o.update({"cls": "weak", "A": True, "note": "no postcondition"}); return o
        h2 = dict(h); h2["ensures"] = ens
        o["A"] = G.prove(G.lemma(parts, h2, "A"))
        o["B"] = None if o["A"] else G.prove(G.lemma(parts, h2, "B"))
        o["T"] = None
        for lab, st in G.trivial_bodies(h2):
            ok, _ = H.dverify2(V.assemble(parts, prog(parts, ens, st)), 90)
            if ok:
                if passes_reference(k, parts, h, lab, st):
                    o["trivial_task"] = lab          # the task itself is solved by this body: not evidence of weakness
                else:
                    o["T"] = lab; break
        o["cls"] = "weak" if (o.get("A") or o.get("B") or o.get("T")) else "undecided"
    except Exception as e:
        o["cls"] = "error"; o["error"] = str(e)[:160]
    with lock:
        n[0] += 1
        if n[0] % 100 == 0:
            print("  ..%d non-determinate audited" % n[0], flush=True)
    return o


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "32"))) as ex:
    res = list(ex.map(work, acc))
with open("/tmp/gen_audit.jsonl", "w") as f:
    for o in res:
        f.write(json.dumps(o) + NL)
refdet = json.load(open("/tmp/ref_det.json")) if os.path.exists("/tmp/ref_det.json") else {}
cert = set(k for k, d in refdet.items() if d == 1.0)
print()
print("%-22s %5s | %-11s %-12s %-9s %4s | %s" % ("model", "acc", "determinate", "provably weak", "undecided", "n/a", "provably weak share of auditable"))
tot = collections.Counter()
for m in H.P11:
    L = [o for o in res if o["model"] == m]; c = collections.Counter(o["cls"] for o in L)
    aud = c["determinate"] + c["weak"] + c["undecided"]
    tot.update(c); tot["acc"] += len(L)
    print("%-22s %5d | %11d %12d %9d %4d | %.1f%%" % (m.split(":")[-1], len(L), c["determinate"], c["weak"], c["undecided"], c["n/a"] + c["error"], 100.0 * c["weak"] / max(1, aud)))
aud = tot["determinate"] + tot["weak"] + tot["undecided"]
print("%-22s %5d | %11d %12d %9d %4d | %.1f%%" % ("ALL", tot["acc"], tot["determinate"], tot["weak"], tot["undecided"], tot["n/a"] + tot["error"], 100.0 * tot["weak"] / max(1, aud)))
print("certificates among provably weak:", dict(collections.Counter(("A" if o.get("A") else "") + ("B" if o.get("B") else "") + ("T" if o.get("T") else "") for o in res if o["cls"] == "weak")))
print("trivial bodies that passed:", collections.Counter(o.get("T") for o in res if o.get("T")).most_common(8))
print("errors:", sum(1 for o in res if o["cls"] == "error"), "| accepts on tasks a trivial body really solves:", sum(1 for o in res if o.get("trivial_task")))
print()
print("cross-check against the entailment oracle (S => reference):")
for name, flt in [("all tasks", lambda o: True), ("tasks with a provably determinate reference", lambda o: "%s|%s" % (o["source"], o["task"]) in cert)]:
    for c in ["determinate", "weak", "undecided"]:
        L = [o for o in res if o["cls"] == c and flt(o)]
        print("   %-46s S %-11s n %4d | implies reference: yes %4d, not proved %4d, n/a %3d" % (name, c, len(L), sum(1 for o in L if o["rel"] is True),
              sum(1 for o in L if o["rel"] is False), sum(1 for o in L if o["rel"] is None)))
