"""Figure 2 on the FULL set: every assessable accept of all 11 models on the 378 tasks with a reference contract.
No model calls. Same rules as repair_funnel.py / conj_arms.py / fix_table5.py:
  replace : the arm's proposal replaces the accepted specification; valid if its body verifies canonically under it
            without a bypass
  add     : the proposal is conjoined to the accepted specification; valid if a stored body (the arm's, else the
            accepted one) verifies canonically under the conjunction without a bypass
  witness-guided: wit2 records attached to the current state (rescored with the final oracle)
Arm proposals come from the big run for accepts whose specification is the original one (their verdicts are reused
from /tmp/fix_arms6.jsonl and /tmp/fix_arms_conj.jsonl, unchanged), and from arms_rerun.py for accepts whose
specification changed after the big run (scored here).
Writes /tmp/repair_funnel_full.json (same format as repair_funnel.json) and /tmp/repair_full_rows.jsonl."""
import os, sys, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import fix_harness as H
import fix_oracle as O
import fix_hdr as HDR
import fix_canon as FCN
import fix_state, fix_state5
import wit2 as W2

NL = chr(10)
ARMS = ["arm_ours", "arm_judge", "arm_determinacy"]
LAB = {"arm_ours": "mined invariants", "arm_judge": "LLM judge", "arm_determinacy": "determinacy rewrite"}
ORDER = {"witness_v2": 0, "arm_determinacy": 1, "arm_judge": 2, "arm_ours": 3}


def jl(p):
    out = []
    for g in sorted(glob.glob(p)):
        for l in open(g):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def bypass_of(parts, code, spec):
    h = O.hdr(parts)
    if not h or not code:
        return None
    prog = FCN.canonical_program(code, h["name"], HDR.head_text(h), O.spec_text(O.spec_ensures(spec)))
    if not prog:
        return None
    return W2.bypasses(H.dedupe_block(parts, prog))


def dedupe(es):
    seen = set(); out = []
    for e in es:
        w = H.nows(e)
        if w and w not in seen:
            seen.add(w); out.append(e)
    return out


S0 = fix_state.load(); E = fix_state5.load_E(); S = fix_state5.load5()
sc = {(r["model"], r["source"], r["task"]): r for r in jl("/tmp/fix_scores6.jsonl")}
pos = json.load(open("/tmp/posable.json"))
base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
plain6 = {(a["model"], a["source"], a["task"], a["arm"]): a for a in jl("/tmp/fix_arms6.jsonl")}
conj6 = {(a["model"], a["source"], a["task"], a["arm"]): a for a in jl("/tmp/fix_arms_conj.jsonl")}
rerun = {}
for r in jl("/tmp/arms_rerun_*.jsonl"):
    if r.get("status") != "ok":
        continue
    k = (r["model"], r["source"], r["task"])
    if k in S and H.nows(r.get("spec_before")) == H.nows(S[k]["spec"]):
        rerun[k] = r
acc = [k for k, v in S.items() if v["accepted"] and v["rel"] is not None and pos.get("%s|%s" % (k[1], k[2]))]
in_common = lambda k: (S0.get(k, {}).get("origin") == "orig" and k not in E and sc.get(k, {}).get("canon") is True and not sc.get(k, {}).get("respec"))
full = [k for k in acc if in_common(k) or k in rerun]
print("assessable accepts %d | with arm proposals for the current specification %d (big run %d, re-run %d) | without %d" % (
    len(acc), len(full), sum(1 for k in full if in_common(k)), sum(1 for k in full if not in_common(k)), len(acc) - len(full)), flush=True)
missing = collections.Counter(k[0].split(":")[-1] for k in acc if k not in full)
if missing:
    print("   accepts without proposals, by model:", dict(missing), flush=True)

# witness-guided records attached to the current state, and the rescoring cache of fix_table5.py
W = {}
for f in sorted(glob.glob("/tmp/wit2_*.jsonl")):
    if "rescore" in f or "smoke" in f:
        continue
    for r in jl(f):
        if "stop" not in r or r.get("stop") == "api-fail":
            continue
        k = (r["model"], r["source"], r["task"])
        if k in S and H.nows(r.get("spec_before")) == H.nows(S[k]["spec"]):
            if k in W and W[k].get("changed") and not r.get("changed"):
                continue
            W[k] = r
CACHE = "/tmp/wit2_rescore.jsonl"
cache = {(r["model"], r["source"], r["task"], r["spec"]): r for r in jl(CACHE)}
lock = threading.Lock()
pc = {}


def parts_of(k):
    t = (k[1], k[2])
    if t not in pc:
        pc[t] = H.task_parts(k[1], k[2])
    return pc[t]


def rescore_w(k):
    r = W[k]; parts = parts_of(k)
    rel, rc, _ = O.rel2(parts, r["final_spec"], r.get("final_code")); det, dc, _ = O.det2(parts, r["final_spec"], r.get("final_code"))
    cn, cc = O.canon_check(parts, r.get("final_code"), r["final_spec"])
    o = {"model": k[0], "source": k[1], "task": k[2], "spec": H.nows(r["final_spec"]), "rel": rel, "det": det, "canon": cn}
    with lock:
        with open(CACHE, "a") as f:
            f.write(json.dumps(o) + NL)
    return o


todo = [k for k in full if k in W and W[k].get("changed") and (k[0], k[1], k[2], H.nows(W[k]["final_spec"])) not in cache]
print("witness changes to rescore: %d" % len(todo), flush=True)
with ThreadPoolExecutor(max_workers=32) as ex:
    for o in ex.map(rescore_w, todo):
        cache[(o["model"], o["source"], o["task"], o["spec"])] = o


def score_new(k):
    """plain and conjunctive verdicts for the re-run proposals of one accept"""
    r = rerun[k]; parts = parts_of(k); v = S[k]
    s0 = O.spec_ensures(v["spec"] or "")
    out = {}
    for arm in ARMS:
        ar = r.get(arm) or {}
        fs = ar.get("final_spec") or ""
        o = {"changed": H.nows(fs) != H.nows(v["spec"])}
        if o["changed"]:
            code1 = ar.get("final_code") or v["code"]
            byp = bypass_of(parts, code1, fs)
            cn, cc = O.canon_check(parts, code1, fs)
            o["plain_valid"] = cn is True and not byp
            if o["plain_valid"]:
                o["plain_after"] = O.rel2(parts, fs, code1)[0]
            both = dedupe(s0 + O.spec_ensures(fs))
            if len(both) > len(s0):
                sp = O.spec_text(both); body = None
                for code in (code1, v["code"]):
                    if not code or bypass_of(parts, code, sp):
                        continue
                    if O.canon_check(parts, code, sp)[0] is True:
                        body = code; break
                o["conj_valid"] = body is not None
                if body is not None:
                    rel = O.rel2(parts, sp, body)[0]
                    o["conj_after"] = True if v["rel"] is True else rel
                    o["conj_det"] = O.det2(parts, sp, body)[0]
            else:
                o["conj_valid"] = False
        out[arm] = o
    return k, out


new = [k for k in full if not in_common(k)]
print("re-run accepts to score: %d" % len(new), flush=True)
with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "40"))) as ex:
    newv = dict(ex.map(score_new, new))

# ---- per accept, per rule: (valid change?, verdict after) ----
rows = []
for k in full:
    before = S[k]["rel"]
    row = {"model": k[0], "source": k[1], "task": k[2], "before": before, "source_of_proposals": "big run" if in_common(k) else "re-run"}
    cands = []
    for arm in ARMS:
        if in_common(k):
            a = plain6.get((k[0], k[1], k[2], arm)) or {}
            c = conj6.get((k[0], k[1], k[2], arm)) or {}
            byp = bool(c.get("plain_bypass"))
            pv = bool(a.get("changed") and a.get("canon_after") is True and not byp)
            row[arm + "|replace"] = (pv, a.get("after") if pv else None)
            cv = bool(c and "skip" not in c and "error" not in c and c.get("conj_valid"))
            row[arm + "|add"] = (cv, c.get("conj_after") if cv else None)
            if cv:
                cands.append((arm, c.get("conj_after"), c.get("det")))
        else:
            o = newv[k][arm]
            pv = bool(o.get("changed") and o.get("plain_valid"))
            row[arm + "|replace"] = (pv, o.get("plain_after") if pv else None)
            cv = bool(o.get("conj_valid"))
            row[arm + "|add"] = (cv, o.get("conj_after") if cv else None)
            if cv:
                cands.append((arm, o.get("conj_after"), o.get("conj_det")))
    w = W.get(k)
    w_valid = False; wv = None
    if w and w.get("changed"):
        cw = cache.get((k[0], k[1], k[2], H.nows(w["final_spec"])))
        if cw and cw.get("canon") is True:
            w_valid = True
            wv = True if before is True else cw.get("rel")      # adding cannot break a correct specification
            cands.append(("witness_v2", wv, cw.get("det")))
    row["witness|add"] = (w_valid, wv)
    if cands:
        cands.sort(key=lambda x: (0 if x[2] == 1.0 else 1, ORDER[x[0]]))
        row["all|add"] = (True, cands[0][1])
    else:
        row["all|add"] = (False, None)
    rows.append(row)
with open("/tmp/repair_full_rows.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r) + NL)

good = [r for r in rows if r["before"] is True]; weak = [r for r in rows if r["before"] is False]
OUT = {"common": len(rows), "correct": len(good), "not_shown": len(weak), "models": len(set(r["model"] for r in rows)),
       "by_source": dict(collections.Counter(r["source_of_proposals"] for r in rows)), "rules": {}}
KEYS = [("LLM judge|replace", "arm_judge|replace"), ("LLM judge|add", "arm_judge|add"), ("determinacy rewrite|replace", "arm_determinacy|replace"),
        ("determinacy rewrite|add", "arm_determinacy|add"), ("mined invariants|replace", "arm_ours|replace"), ("mined invariants|add", "arm_ours|add"),
        ("witness-guided|add", "witness|add"), ("all four proposers|add", "all|add")]
print("full set: %d accepts of %d models | correct %d | not shown correct %d" % (len(rows), OUT["models"], len(good), len(weak)))
for name, key in KEYS:
    c = collections.Counter()
    for r in rows:
        valid, after = r[key]
        if not valid:
            continue
        c["changes"] += 1
        if r["before"] is True:
            c["stays_correct"] += after is True; c["broken"] += after is not True
            c["broken_undecided"] += after is None          # part of "broken": no longer provably correct, not refuted
        else:
            c["repaired"] += after is True; c["still_not_shown"] += after is not True
    OUT["rules"][name] = {k: c[k] for k in ("changes", "stays_correct", "broken", "broken_undecided", "repaired", "still_not_shown")}
    print("   %-30s changes %4d | stayed correct %4d broken %3d (of them undecided %d) | repaired %3d still not shown %3d" % (
        name, c["changes"], c["stays_correct"], c["broken"], c["broken_undecided"], c["repaired"], c["still_not_shown"]))
json.dump(OUT, open("/tmp/repair_funnel_full.json", "w"), indent=1)
print("DONE")
