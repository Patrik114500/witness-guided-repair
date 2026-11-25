"""Figure 2 extended to the end-to-end runs of figure 3 (2026-11-20). The accepts of BOTH pipelines on CloverBench
(62 tasks, 4 models x 3 runs, Clover's pipeline and ours) and MBPP-DFY (159 tasks, 4 models, dafny-synthesis and ours)
get the same repair strategies as the big run, run unchanged with the model that wrote the accept:
  mined invariants, LLM judge, determinacy flag : big_run.iterated_repair (ITERS=5, REPAIR_ROUNDS=5), as arms_rerun.py
  witness-guided                                 : wit2.witness_arm2, standard budget; for an accept the model called
                                                   complete, the force pass (PASS3), as in the big run
and are scored by the rules of repair_full.py (replace / add / witness-guided / all four proposers).
Oracle as in figure 3:
  CloverBench : O.canon_check + O.rel2 against the benchmark's strong specification (clover_multi_score.py)
  MBPP-DFY    : strict verifier, no bypass, mbpp_rescore2.proof_verdict against the reference program (correct /
                not-shown); an accept whose program does not implement the task's interface, or whose comparison
                does not resolve, has no defined correctness and is left out of the pool (counted)
For MBPP the task is stated in the program's own terms: the main method's header and postcondition, the program's
other declarations as the preamble (the repairers see the description, the header and the specification, never the
reference). The rebuilt program must reproduce the verdict of figure 3, else the accept is left out (counted).
Modes:
  PREP=1                      no model calls: /tmp/e2e_accepts.jsonl, and the agreement with figure 3's verdicts
  MODEL=<id> [WORKERS] [CAP] [LIMIT]   the strategies on that model's accepts -> /tmp/e2e_rep_<tag>.jsonl (resumable)
  AGG=1                       no model calls: /tmp/repair_funnel_ext.json (big run + end-to-end accepts)"""
import os, sys, json, glob, random, collections, threading
os.environ.setdefault("ITERS", "5"); os.environ.setdefault("REPAIR_ROUNDS", "5")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/clover")); sys.path.insert(0, os.path.expanduser("~/clover/clover"))
sys.path.insert(0, os.path.expanduser("~/clover/shim"))
os.environ.setdefault("MODEL", "none")
from concurrent.futures import ThreadPoolExecutor
import vericode_compete as V
import fix_harness as H
import fix_hdr as HDR
import fix_oracle as O
import fix_canon as FCN
import big_run as BR
import wit2 as W2
import mbpp_rescore2 as M
import clover_gated as CG

_old_sig_head = V.sig_head


def _sig_head(vs):
    h = HDR.parse(vs)
    return HDR.head_text(h) if h else _old_sig_head(vs)


V.sig_head = _sig_head                      # the robust header, as in arms_rerun.py / stage E
NL = chr(10)
ACC = "/tmp/e2e_accepts.jsonl"
ARMS = ["arm_ours", "arm_judge", "arm_determinacy"]
ORDER = {"witness_v2": 0, "arm_determinacy": 1, "arm_judge": 2, "arm_ours": 3}
MID = {"gpt-4o": "aoai:gpt-4o", "gpt-5-mini": "aoai:gpt-5-mini", "haiku-4-5": "claude:claude-haiku-4-5",
       "sonnet-4-6": "claude:claude-sonnet-4-6"}
TAG = {"gpt-4o": "aoai_gpt-4o", "gpt-5-mini": "aoai_gpt-5-mini", "haiku-4-5": "claude_claude-haiku-4-5",
       "sonnet-4-6": "claude_claude-sonnet-4-6"}
# CloverBench: the files clover_multi_score.py reads
CL = {"gpt-4o": {"clover": ["/tmp/clover_v2_clover_c%d_s*.jsonl" % i for i in (1, 2, 3)],
                 "ours": ["/tmp/clover_v2_ours_r%d_s*.jsonl" % i for i in (1, 2, 3)]}}
for _l in ("haiku-4-5", "sonnet-4-6", "gpt-5-mini"):
    CL[_l] = {m: ["/tmp/clover_v3_%s_%s_r%d_s*.jsonl" % (TAG[_l], m, i) for i in (1, 2, 3)] for m in ("clover", "ours")}
# MBPP-DFY: the FILES of the final scoring (/tmp/mbpp_multi_a2.json, /tmp/mbpp_multi_b2.json)
MB = {"haiku-4-5": {"baseline": "/tmp/mbpp_repro_haiku.jsonl;/tmp/mbpp3strict_repro_claude_claude-haiku-4-5_s*.jsonl",
                    "ours": "/tmp/mbpp_boost_full2.jsonl;/tmp/mbpp3fix_boost_claude_claude-haiku-4-5.jsonl;"
                            "/tmp/mbpp3strict_boost_claude_claude-haiku-4-5_s*.jsonl"}}
for _l in ("gpt-4o", "sonnet-4-6", "gpt-5-mini"):
    MB[_l] = {"baseline": "/tmp/mbpp3_repro_%s_s*.jsonl;/tmp/mbpp3strict_repro_%s_s*.jsonl" % (TAG[_l], TAG[_l]),
              "ours": "/tmp/mbpp3_boost_%s_s*.jsonl;/tmp/mbpp3fix_boost_%s.jsonl;/tmp/mbpp3strict_boost_%s_s*.jsonl" % (TAG[_l], TAG[_l], TAG[_l])}


def jl(p):
    out = []
    for g in sorted(glob.glob(p)):
        for l in open(g):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def dedupe(es):
    seen = set(); out = []
    for e in es:
        w = H.nows(e)
        if w and w not in seen:
            seen.add(w); out.append(e)
    return out


def bypass_of(parts, code, spec):
    h = O.hdr(parts)
    if not h or not code:
        return None
    prog = FCN.canonical_program(code, h["name"], HDR.head_text(h), O.spec_text(O.spec_ensures(spec)))
    if not prog:
        return None
    return W2.bypasses(H.dedupe_block(parts, prog))


# ---------------------------------------------------------------- the task and the oracle for one accept
_cl = {}


def clover_parts(task):
    if task not in _cl:
        _cl[task] = CG.load_task(task)
    return _cl[task]


def mbpp_parts(task, code):
    """the task in the program's own terms: (parts, main method block, specification) or (None, why)"""
    ref = M.REF.get(task)
    if ref is None:
        return None, "no reference file"
    rh = M.main_method(ref)
    gh = M.main_method(code, rh["name"] if rh else None)
    if not gh:
        return None, "no main method"
    ch = M.chunks(code)
    mains = [t for k, n, t in ch if k == "method" and n == gh["name"]]
    if len(mains) != 1:
        return None, "main method is not one top-level declaration"
    pre = (NL + NL).join(t.rstrip() for k, n, t in ch if not (k == "method" and n in (gh["name"], "Main")))
    vs = HDR.head_text(gh) + NL + "  " + (NL + "  ").join("ensures " + e for e in gh["ensures"])
    parts = {"vc-preamble": pre, "vc-helpers": "", "vc-code": "", "vc-postamble": "",
             "vc-description": M.db.get(task.replace("task_id_", ""), {}).get("task_description", ""), "vc-spec": vs}
    return (parts, mains[0], O.spec_text(gh["ensures"])), None


def oracle(a, spec, code):
    """True = the specification provably implies the reference; False = not shown; None = undefined"""
    parts = a["parts"]
    if a["dataset"] == "CloverBench":
        return O.rel2(parts, spec, code)[0]
    h = O.hdr(parts)
    prog = FCN.canonical_program(code or "", h["name"], HDR.head_text(h), O.spec_text(O.spec_ensures(spec)))
    if not prog:
        return None
    v = M.proof_verdict(V.assemble(parts, H.dedupe_block(parts, prog)), M.REF[a["task"]]).get("proof")
    return True if v == "correct" else (False if v == "not-shown" else None)


# ---------------------------------------------------------------- PREP: the pool, no model calls
def prep():
    jobs = []
    stored = {(o["model"], o["mode"], o["run"], o["task"]): o for o in jl("/tmp/clover_multi.jsonl")}
    for lab, modes in CL.items():
        for mode, runs in modes.items():
            for ri, pat in enumerate(runs):
                d = {}
                for r in jl(pat):
                    d[r["task"]] = r
                for t, r in d.items():
                    if r.get("status") == "accepted":
                        so = stored.get((lab, mode, ri, t)) or {}
                        st = "correct" if (so.get("canon") is True and so.get("rel") is True) else "not-shown"
                        jobs.append(("CloverBench", lab, mode, ri, t, r.get("gen_spec") or "", r.get("code") or "", st))
    for lab, pipes in MB.items():
        for pipe, spec in pipes.items():
            for r in M.records(spec):
                if r.get("status") == "accepted":
                    code = r.get("code") or ((r.get("attempts") or [{}])[-1].get("code")) or ""
                    jobs.append(("MBPP-DFY", lab, pipe, 0, r["task"], None, code, None))
    print("accepted records: %s" % dict(collections.Counter((j[0], j[1], j[2]) for j in jobs)), flush=True)

    def work(j):
        ds, lab, pipe, ri, task, gen, code, st = j
        a = {"key": "%s|%s|%s|%d|%s" % (ds, lab, pipe, ri, task), "dataset": ds, "label": lab, "model": MID[lab],
             "pipeline": pipe, "run": ri, "task": task}
        try:
            if ds == "CloverBench":
                x = clover_parts(task)
                if not x:
                    a["out"] = "no task file"; return a
                parts = x[2]; a.update({"parts": parts, "spec0": gen, "code0": code, "stored": st})
            else:
                ok, _ = H.dverify2(code, 90)
                if not ok or M.BYPASS.search(M.nocomment(code)):
                    a["out"] = "not a strict accept"; return a
                pv = M.proof_verdict(code, M.REF[task]) if task in M.REF else {"proof": "unresolved"}
                a["stored"] = pv.get("proof")
                if pv.get("proof") not in ("correct", "not-shown"):
                    a["out"] = "verdict " + str(pv.get("proof")); return a
                x, why = mbpp_parts(task, code)
                if not x:
                    a["out"] = why; return a
                a.update({"parts": x[0], "code0": x[1], "spec0": x[2]})
            a["canon0"] = O.canon_check(a["parts"], a["code0"], a["spec0"])[0]
            if a["canon0"] is not True:
                a["out"] = "not canonical"; return a
            b = oracle(a, a["spec0"], a["code0"])
            a["before"] = b
            if b is None:
                a["out"] = "oracle undefined"; return a
            if (b is True) != (a["stored"] == "correct"):
                a["out"] = "verdict differs from figure 3"; return a
            a["det0"] = O.det2(a["parts"], a["spec0"], a["code0"])[0]
            a["out"] = "pool"
        except Exception as e:
            a["out"] = "error"; a["error"] = str(e)[:200]
        return a

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "48"))) as ex:
        rows = list(ex.map(work, jobs))
    with open(ACC, "w") as f:
        for a in rows:
            f.write(json.dumps(a) + NL)
    print("outcome: %s" % dict(collections.Counter((a["dataset"], a["out"]) for a in rows)), flush=True)
    P = [a for a in rows if a["out"] == "pool"]
    for ds in ("CloverBench", "MBPP-DFY"):
        L = [a for a in P if a["dataset"] == ds]
        print("%-12s pool %4d | correct %4d not shown %4d | determinacy flags %d | by model %s" % (
            ds, len(L), sum(a["before"] is True for a in L), sum(a["before"] is False for a in L), sum(a.get("det0") == 0.0 for a in L),
            dict(collections.Counter(a["label"] for a in L))), flush=True)
    print("DONE", flush=True)


# ---------------------------------------------------------------- RUN: the strategies on one model's accepts
def score(a, o):
    """the verdict of every rule for one accept, by the rules of repair_full.py"""
    parts = a["parts"]; S0 = a["spec0"]; C0 = a["code0"]; before = a["before"]
    s0 = O.spec_ensures(S0)
    row = {k: a[k] for k in ("key", "dataset", "label", "model", "pipeline", "run", "task", "before")}
    row["source"] = a["dataset"]; cands = []
    for arm in ARMS:
        ar = o.get(arm) or {}
        fs = ar.get("final_spec") or ""
        rep = [False, None]; add = [False, None]
        if fs and H.nows(fs) != H.nows(S0):
            code1 = ar.get("final_code") or C0
            if O.canon_check(parts, code1, fs)[0] is True and not bypass_of(parts, code1, fs):
                rep = [True, oracle(a, fs, code1)]
            both = dedupe(s0 + O.spec_ensures(fs))
            if len(both) > len(s0):
                sp = O.spec_text(both); body = None
                for code in (code1, C0):
                    if not code or bypass_of(parts, code, sp):
                        continue
                    if O.canon_check(parts, code, sp)[0] is True:
                        body = code; break
                if body is not None:
                    after = True if before is True else oracle(a, sp, body)
                    add = [True, after]
                    cands.append((arm, after, O.det2(parts, sp, body)[0]))
        row[arm + "|replace"] = rep; row[arm + "|add"] = add
    w = o.get("witness") or {}
    row["witness|add"] = [False, None]
    if w.get("changed") and O.canon_check(parts, w.get("final_code"), w["final_spec"])[0] is True:
        after = True if before is True else oracle(a, w["final_spec"], w.get("final_code"))
        row["witness|add"] = [True, after]
        cands.append(("witness_v2", after, O.det2(parts, w["final_spec"], w.get("final_code"))[0]))
    if cands:
        cands.sort(key=lambda x: (0 if x[2] == 1.0 else 1, ORDER[x[0]]))
        row["all|add"] = [True, cands[0][1]]
    else:
        row["all|add"] = [False, None]
    return row


def run_model():
    MODEL = os.environ["MODEL"]
    OUT = os.environ.get("OUT", "/tmp/e2e_rep_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_"))
    CAP = float(os.environ.get("CAP", "10")); LIMIT = int(os.environ.get("LIMIT", "0"))
    pool = [a for a in jl(ACC) if a.get("out") == "pool" and a["model"] == MODEL]
    done = set(r["key"] for r in jl(OUT) if r.get("status") == "ok")
    tg = [a for a in pool if a["key"] not in done]
    random.Random(7).shuffle(tg)
    if os.environ.get("SMOKE") == "1":       # a small trial that touches every path: both datasets, both pipelines, the witness
        pick = []
        for f in (lambda a: a["dataset"] == "CloverBench", lambda a: a["dataset"] == "MBPP-DFY" and a["pipeline"] == "baseline",
                  lambda a: a.get("det0") == 0.0 and a["before"] is False, lambda a: a["before"] is False and a.get("det0") != 0.0):
            c = [a for a in tg if f(a) and a not in pick]
            if c:
                pick.append(c[0])
        tg = pick
    if LIMIT:
        tg = tg[:LIMIT]
    print("%s: %d accepts to run (pool %d, done %d), cap $%.0f" % (MODEL, len(tg), len(pool), len(done), CAP), flush=True)
    lock = threading.Lock(); spent = [0.0]; st = collections.Counter(); fo = open(OUT, "a")

    def work(a):
        if spent[0] > CAP:
            with lock:
                st["skipped-cap"] += 1
            return
        parts = a["parts"]; S0 = a["spec0"]; C0 = a["code0"]
        o = {k: a[k] for k in ("key", "dataset", "label", "model", "pipeline", "run", "task", "before", "det0")}
        tr = BR.Tracker(MODEL); asker = H.Asker(MODEL)
        try:
            head = O.head(parts)
            for arm, name in (("ours", "arm_ours"), ("judge", "arm_judge"), ("det", "arm_determinacy")):
                o[name] = BR.iterated_repair(parts, head, S0, C0, tr, arm)
            w = None
            if a.get("det0") == 0.0 and not O.modifies_text(parts).strip() and (O.sig_all(parts) or (0, 0, []))[2]:
                w = W2.witness_arm2(parts, S0, C0, asker); w["pass"] = 1
                if not w.get("changed") and w.get("stop") == "complete":
                    w3 = W2.witness_arm2(parts, S0, C0, asker, force_first=True)
                    w3["pass"] = 3; w3["prev_stop"] = w.get("stop"); w = w3
            o["witness"] = w
            o["rows"] = score(a, o)
            o["status"] = "ok"
        except Exception as e:
            o["status"] = "error"; o["error"] = str(e)[:300]
        o["cost_arms"] = tr.summ(); o["cost_witness"] = asker.summ()
        c = o["cost_arms"].get("cost_usd", 0) + o["cost_witness"].get("cost_usd", 0)
        with lock:
            spent[0] += c
            fo.write(json.dumps(o) + NL); fo.flush()
            st["n"] += 1; st[o["status"]] += 1
            rw = o.get("rows") or {}
            for k, short in (("arm_judge|replace", "judge"), ("arm_determinacy|replace", "detflag"), ("arm_ours|replace", "invar"),
                             ("all|add", "OURS")):
                v = rw.get(k) or [False, None]
                if v[0] and a["before"] is True and v[1] is not True:
                    st["broke " + short] += 1
                if v[0] and a["before"] is False and v[1] is True:
                    st["fixed " + short] += 1
            print("  %-12s %-9s %-28s %-6s $%.3f | n %d/%d spent $%.2f | %s" % (
                a["dataset"], a["pipeline"], a["task"][:28], o["status"], c, st["n"], len(tg), spent[0],
                ", ".join("%s %d" % (k, v) for k, v in sorted(st.items()) if k.startswith(("broke", "fixed")))), flush=True)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "6"))) as ex:
        list(ex.map(work, tg))
    print("DONE %s %s spent $%.2f" % (MODEL, dict(st), spent[0]), flush=True)


# ---------------------------------------------------------------- AGG: big run + end-to-end accepts
KEYS = [("LLM judge|replace", "arm_judge|replace"), ("LLM judge|add", "arm_judge|add"),
        ("determinacy rewrite|replace", "arm_determinacy|replace"), ("determinacy rewrite|add", "arm_determinacy|add"),
        ("mined invariants|replace", "arm_ours|replace"), ("mined invariants|add", "arm_ours|add"),
        ("witness-guided|add", "witness|add"), ("all four proposers|add", "all|add")]


def funnel(rows):
    out = {}
    for name, key in KEYS:
        c = collections.Counter()
        for r in rows:
            valid, after = r[key]
            if not valid:
                continue
            c["changes"] += 1
            if r["before"] is True:
                c["stays_correct"] += after is True; c["broken"] += after is not True; c["broken_undecided"] += after is None
            else:
                c["repaired"] += after is True; c["still_not_shown"] += after is not True
        out[name] = {k: c[k] for k in ("changes", "stays_correct", "broken", "broken_undecided", "repaired", "still_not_shown")}
    return out


def agg():
    big = jl("/tmp/repair_full_rows.jsonl")
    for r in big:
        r["dataset"] = r["source"]
    e2e = []
    for f in sorted(glob.glob("/tmp/e2e_rep_*.jsonl")):
        for o in jl(f):
            if o.get("status") == "ok" and o.get("rows"):
                e2e.append(o["rows"])
    e2e = list({r["key"]: r for r in e2e}.values())
    pool = [a for a in jl(ACC) if a.get("out") == "pool"]
    print("big run rows %d | end-to-end rows %d of a pool of %d" % (len(big), len(e2e), len(pool)), flush=True)
    rows = big + e2e
    OUT = {"common": len(rows), "correct": sum(r["before"] is True for r in rows), "not_shown": sum(r["before"] is False for r in rows),
           "models": len(set(r["model"] for r in rows)), "tasks": len(set((r["dataset"], r["task"]) for r in rows)),
           "by_source": {"big run": len(big), "end-to-end": len(e2e)}, "pool_e2e": len(pool), "rules": funnel(rows), "parts": {}}
    for name, L in (("big run", big), ("end-to-end", e2e), ("CloverBench", [r for r in e2e if r["dataset"] == "CloverBench"]),
                    ("MBPP-DFY", [r for r in e2e if r["dataset"] == "MBPP-DFY"])):
        OUT["parts"][name] = {"accepts": len(L), "correct": sum(r["before"] is True for r in L), "rules": funnel(L)}
    json.dump(OUT, open("/tmp/repair_funnel_ext.json", "w"), indent=1)
    for part in ("big run", "end-to-end", "CloverBench", "MBPP-DFY"):
        P = OUT["parts"][part]
        print("== %s: %d accepts, %d correct" % (part, P["accepts"], P["correct"]), flush=True)
        for name, _ in KEYS:
            v = P["rules"][name]
            print("   %-30s changes %4d | stayed correct %4d broken %3d | repaired %3d still not shown %3d" % (
                name, v["changes"], v["stays_correct"], v["broken"], v["repaired"], v["still_not_shown"]), flush=True)
    print("ALL: %d accepts (%d correct, %d not shown), %d models, %d tasks" % (OUT["common"], OUT["correct"], OUT["not_shown"], OUT["models"], OUT["tasks"]))
    for name, _ in KEYS:
        v = OUT["rules"][name]
        print("   %-30s changes %4d | stayed correct %4d broken %3d | repaired %3d still not shown %3d" % (
            name, v["changes"], v["stays_correct"], v["broken"], v["repaired"], v["still_not_shown"]), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    if os.environ.get("PREP") == "1":
        prep()
    elif os.environ.get("AGG") == "1":
        agg()
    else:
        run_model()
