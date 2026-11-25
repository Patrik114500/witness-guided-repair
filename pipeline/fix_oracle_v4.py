"""Oracle v4 patch run: only the two-state cases change against v3 (old(X) read as X for methods without a
modifies clause), so everything else is copied from /tmp/fix_scores3.jsonl and /tmp/fix_arms3.jsonl.
Output: /tmp/fix_scores4.jsonl, /tmp/fix_arms4.jsonl. No model calls."""
import os, sys, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_harness as H
import fix_oracle as O
import fix_state

NL = chr(10)
S = fix_state.load()
base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
wb = O.load_witness_backfill()
R3 = [json.loads(l) for l in open("/tmp/fix_scores3.jsonl")]
A3 = [json.loads(l) for l in open("/tmp/fix_arms3.jsonl")]
pc = {}; lock = threading.Lock(); st = collections.Counter()


def parts_of(k):
    t = (k[1], k[2])
    if t not in pc:
        pc[t] = H.task_parts(k[1], k[2])
    return pc[t]


def main_job(r):
    k = (r["model"], r["source"], r["task"]); v = S[k]
    o = dict(r)
    if O.TWO.search(v["spec"] or "") or r.get("rel_cls") == "illformed" or r.get("det_cls") == "illformed":
        parts = parts_of(k)
        rel, rc, re_ = O.rel2(parts, v["spec"], v["code"]); det, dc, de_ = O.det2(parts, v["spec"], v["code"])
        with lock:
            st[("main", str(r["rel"]), str(rel))] += 1; st[("det", str(r["det"]), str(det))] += 1
        o.update({"rel": rel, "rel_cls": rc, "rel_err": re_, "det": det, "det_cls": dc, "det_err": de_, "v3_rel": r["rel"], "v3_det": r["det"]})
    return o


def arm_job(a):
    k = (a["model"], a["source"], a["task"]); r = base[k]
    arm = r.get(a["arm"])
    if a["arm"] == "arm_witness" and k in wb and ((not arm) or wb[k].get("n_rounds", 0) >= (arm or {}).get("n_rounds", 0)):
        arm = wb[k]
    arm = arm or {}
    fs = arm.get("final_spec") or ""; gen = r.get("gen_spec") or ""
    o = dict(a)
    code0 = (r.get("code_attempts") or [{}])[-1].get("code")
    if O.TWO.search(gen) or a.get("before_cls") == "illformed":
        b, bc, _ = O.rel2(parts_of(k), gen, code0); o.update({"before": b, "before_cls": bc})
    if not a["changed"]:
        o["after"] = o["before"]; o["after_cls"] = o["before_cls"]
    elif O.TWO.search(fs) or a.get("after_cls") == "illformed":
        x, xc, _ = O.rel2(parts_of(k), fs, arm.get("final_code") or code0); o.update({"after": x, "after_cls": xc})
    if a["changed"] and "canon_after" not in o:
        # keep-on-fail, applied uniformly: a rewritten specification only counts if a body verifies under it
        cn, cc = O.canon_check(parts_of(k), arm.get("final_code") or code0, fs)
        o["canon_after"] = cn; o["canon_after_cls"] = cc
    with lock:
        st["arm"] += 1
    return o


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "64"))) as ex:
    R4 = list(ex.map(main_job, R3))
    with open("/tmp/fix_scores4.jsonl", "w") as f:
        for o in R4:
            f.write(json.dumps(o) + NL)
    print("main done", {str(k): v for k, v in st.items()}, flush=True)
    A4 = list(ex.map(arm_job, A3))
    with open("/tmp/fix_arms4.jsonl", "w") as f:
        for o in A4:
            f.write(json.dumps(o) + NL)
print("DONE", len(R4), len(A4), flush=True)
