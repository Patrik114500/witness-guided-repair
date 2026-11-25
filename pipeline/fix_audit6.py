"""Audit v6 (2026-11-18 late evening): everything re-checked with the STRICT verifier call.

Until now a Dafny run that ended with "N verified, 0 errors, K time out" was read as success, both for
programs (acceptance) and for the oracle's lemmas (reliability, determinacy). fix_harness.dverify2 is now
strict: an unfinished proof is not a proof. This script recomputes, with no model calls:
  MODE=main  every accepted big-run task: specification of record (read from the accepted program),
             canonical check, entailment lemma, determinacy lemma        -> /tmp/fix_scores6.jsonl
  MODE=E     the stage-E accepts (/tmp/fix_rerunE*_*.jsonl)              -> /tmp/fix_E6.jsonl
  MODE=arms  the repair arms' final specifications (first-pass accepts)  -> /tmp/fix_arms6.jsonl
"""
import os, sys, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_harness as H
import fix_oracle as O
import fix_state

NL = chr(10)
MODE = os.environ.get("MODE", "main")
pc = {}; lock = threading.Lock(); st = collections.Counter()


def parts_of(k):
    t = (k[1], k[2])
    if t not in pc:
        pc[t] = H.task_parts(k[1], k[2])
    return pc[t]


def jl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def score(parts, spec, code):
    rel, rc, re_ = O.rel2(parts, spec, code); det, dc, de_ = O.det2(parts, spec, code); cn, cc = O.canon_check(parts, code, spec)
    return {"rel": rel, "rel_cls": rc, "rel_err": re_, "det": det, "det_cls": dc, "canon": cn, "canon_cls": cc}


def run(jobs, fn, out_path):
    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "64"))) as ex:
        res = [r for r in ex.map(fn, jobs) if r is not None]
    with open(out_path, "w") as f:
        for r in res:
            f.write(json.dumps(r) + NL)
    print("wrote %s: %d" % (out_path, len(res)), flush=True)
    return res


if MODE == "main":
    S = fix_state.load()
    old = {(r["model"], r["source"], r["task"]): r for r in jl("/tmp/fix_scores5.jsonl")}
    keys = [k for k, v in S.items() if v["accepted"]]

    def work(k):
        v = S[k]; parts = parts_of(k)
        try:
            cs = O.code_spec(parts, v["code"])
            spec = cs if cs is not None else v["spec"]
            o = {"model": k[0], "source": k[1], "task": k[2], "spec": spec, "respec": cs is not None and H.nows(cs) != H.nows(O.spec_text(O.spec_ensures(v["spec"]))),
                 "origin": v["origin"], "two": bool(O.TWO.search(spec or ""))}
            o.update(score(parts, spec, v["code"]))
            p = old.get(k) or {}
            o.update({"v5_rel": p.get("rel"), "v5_det": p.get("det"), "v5_canon": p.get("canon")})
            with lock:
                st[("rel", str(p.get("rel")), str(o["rel"]))] += 1; st[("det", str(p.get("det")), str(o["det"]))] += 1
                st[("canon", str(p.get("canon")), str(o["canon"]))] += 1; st["n"] += 1
                if st["n"] % 400 == 0:
                    print("  ..%d" % st["n"], flush=True)
            return o
        except Exception as e:
            print("ERR", k, str(e)[:150], flush=True)
            return None
    run(keys, work, "/tmp/fix_scores6.jsonl")
    for k in sorted(st, key=str):
        if k != "n":
            print("  ", k, st[k])
elif MODE == "confirm":
    # time-outs measured on a loaded machine are re-measured once with few workers; a proof that then goes
    # through within Dafny's own limit counts, one that times out again does not
    S = fix_state.load()
    R = jl("/tmp/fix_scores6.jsonl")
    tgt = [r for r in R if "timeout" in (str(r.get("canon_cls")), str(r.get("rel_cls")), str(r.get("det_cls")))]
    print("records with a time-out class: %d (canon %d, rel %d, det %d)" % (len(tgt), sum(1 for r in tgt if r.get("canon_cls") == "timeout"),
          sum(1 for r in tgt if r.get("rel_cls") == "timeout"), sum(1 for r in tgt if r.get("det_cls") == "timeout")), flush=True)

    def work(r):
        k = (r["model"], r["source"], r["task"]); parts = parts_of(k); code = S[k]["code"]; ch = {}
        if r.get("canon_cls") == "timeout":
            cn, cc = O.canon_check(parts, code, r["spec"]); ch.update({"canon": cn, "canon_cls": cc})
        if r.get("rel_cls") == "timeout":
            rel, rc, _ = O.rel2(parts, r["spec"], code); ch.update({"rel": rel, "rel_cls": rc})
        if r.get("det_cls") == "timeout":
            det, dc, _ = O.det2(parts, r["spec"], code); ch.update({"det": det, "det_cls": dc})
        with lock:
            for f in ("canon", "rel", "det"):
                if f in ch:
                    st[(f, str(r.get(f)), str(ch[f]))] += 1
        return (k, ch)
    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "12"))) as ex:
        upd = dict(ex.map(work, tgt))
    with open("/tmp/fix_scores6.jsonl", "w") as f:
        for r in R:
            k = (r["model"], r["source"], r["task"])
            if k in upd:
                r = dict(r); r.update(upd[k]); r["confirmed"] = True
            f.write(json.dumps(r) + NL)
    for k in sorted(st, key=str):
        print("  ", k, st[k])
elif MODE == "E":
    recs = []
    for f in sorted(glob.glob("/tmp/fix_rerunE_*.jsonl")) + sorted(glob.glob("/tmp/fix_rerunE2_*.jsonl")):
        for r in jl(f):
            if r.get("accepted") and r.get("code"):
                recs.append((f, r))

    def work(x):
        f, r = x; k = (r["model"], r["source"], r["task"]); parts = parts_of(k)
        try:
            o = {"model": k[0], "source": k[1], "task": k[2], "mode": r["mode"], "file": os.path.basename(f), "spec": r["gen_spec"]}
            o.update(score(parts, r["gen_spec"], r["code"]))
            o["accepted"] = o["canon"] is True
            o["old_rel"] = r.get("rel"); o["old_det"] = r.get("det")
            with lock:
                st[("accepted", o["accepted"])] += 1; st[("rel", str(r.get("rel")), str(o["rel"]))] += 1
            return o
        except Exception as e:
            print("ERR", k, str(e)[:150], flush=True)
            return None
    run(recs, work, "/tmp/fix_E6.jsonl")
    for k in sorted(st, key=str):
        print("  ", k, st[k])
else:
    base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
    wb = O.load_witness_backfill()
    jobs = []
    for k, r in base.items():
        if r.get("status") != "accepted":
            continue
        for a in O.ARMS:
            arm = r.get(a)
            if a == "arm_witness" and k in wb and ((not arm) or wb[k].get("n_rounds", 0) >= (arm or {}).get("n_rounds", 0)):
                arm = wb[k]
            if arm and "final_spec" in arm:
                jobs.append((k, a, arm))

    def work(x):
        k, a, arm = x; r = base[k]; parts = parts_of(k)
        try:
            fs = arm.get("final_spec") or ""; gen = r.get("gen_spec") or ""
            code0 = (r.get("code_attempts") or [{}])[-1].get("code")
            changed = H.nows(fs) != H.nows(gen)
            o = {"model": k[0], "source": k[1], "task": k[2], "arm": a, "changed": changed}
            if changed:
                code = arm.get("final_code") or code0
                rel, rc, _ = O.rel2(parts, fs, code); cn, cc = O.canon_check(parts, code, fs)
                o.update({"after": rel, "after_cls": rc, "canon_after": cn, "canon_after_cls": cc})
            with lock:
                st["n"] += 1
                if st["n"] % 1000 == 0:
                    print("  ..%d" % st["n"], flush=True)
            return o
        except Exception as e:
            print("ERR", k, a, str(e)[:150], flush=True)
            return None
    run(jobs, work, "/tmp/fix_arms6.jsonl")
print("DONE", MODE, flush=True)
