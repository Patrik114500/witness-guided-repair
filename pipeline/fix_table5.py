"""Final big-run tables after the evening audit (2026-11-18): oracle v4, canonical accepts only, stage E
(header bug repaired), and the witness arm v2 as the repair step. Read-only except for a small cache of
re-scored repairs. Prints the tables and writes /tmp/fix_final5.json for the figures."""
import os, sys, json, glob, collections, random, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_harness as H
import fix_oracle as O
import fix_state, fix_state5

NL = chr(10)
SRC = ["numpy_simple", "verina", "verified_cogen"]
CLOUD = [m for m in H.P11 if ":" in m and m.split(":")[0] in ("aoai", "claude", "grok")]


def jl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


S = fix_state5.load5()                       # before repair
S_noE = fix_state5.load5(use_E=False)
S0 = fix_state.load()
base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
E = fix_state5.load_E()

# optional task filter. "certified": only the tasks whose REFERENCE specification is provably determinate, i.e. the
# reference itself is complete, so "the generated specification implies the reference" means what it should.
TASKSET = os.environ.get("TASKSET", "")
OUTJ = "/tmp/fix_final5.json"
CERT = None
if TASKSET == "certified":
    RD = "/tmp/ref_det.json"
    if os.path.exists(RD):
        refdet = json.load(open(RD))
    else:
        def _rd(t):
            parts = H.task_parts(t[0], t[1])
            g = O.spec_text(O.ref_ensures(parts)) if O.hdr(parts) else ""
            d = O.det2(parts, g)[0] if g else None
            return "%s|%s" % t, d
        with ThreadPoolExecutor(max_workers=32) as ex:
            refdet = dict(ex.map(_rd, sorted(set((k[1], k[2]) for k in S))))
        json.dump(refdet, open(RD, "w"))
    CERT = set(tuple(k.split("|", 1)) for k, d in refdet.items() if d == 1.0)
    S = {k: v for k, v in S.items() if (k[1], k[2]) in CERT}
    S_noE = {k: v for k, v in S_noE.items() if (k[1], k[2]) in CERT}
    OUTJ = "/tmp/fix_final5_certified.json"
    print("TASKSET certified: %d tasks with a provably determinate reference %s" % (
        len(CERT), dict(collections.Counter(t[0] for t in CERT))))
elif TASKSET == "described":
    # only the tasks that HAVE a natural-language description: the description -> specification step is only
    # defined there (verified_cogen has none, numpy_simple has one for 26 of 58 tasks)
    _dl = json.load(open("/tmp/desc_len.json"))
    CERT = set(tuple(k.split("|", 1)) for k, n in _dl.items() if n > 0)
    S = {k: v for k, v in S.items() if (k[1], k[2]) in CERT}
    S_noE = {k: v for k, v in S_noE.items() if (k[1], k[2]) in CERT}
    OUTJ = "/tmp/fix_final5_described.json"
    print("TASKSET described: %d tasks with a description %s" % (len(CERT), dict(collections.Counter(t[0] for t in CERT))))

# ---- tasks whose reference contract cannot be posed for ANY model are not part of the measurement (2026-11-19).
# The benchmark entry is a function or a lemma instead of a method (6 verina tasks), or the reference method has no
# postcondition at all (verina_advanced_66). Every accept on them was "not assessable". TASKFILTER=1 leaves them out
# of every view and writes /tmp/fix_final7*.json.
TASKFILTER = os.environ.get("TASKFILTER", "") == "1"
if TASKFILTER:
    PF = "/tmp/posable.json"
    ALLT = sorted(set((k[1], k[2]) for k in S0))          # every task of the big run, whatever TASKSET is
    pos = json.load(open(PF)) if os.path.exists(PF) else {}
    if any("%s|%s" % t not in pos for t in ALLT):
        def _pos(t):
            parts = H.task_parts(t[0], t[1])
            return "%s|%s" % t, bool(O.sig_all(parts) is not None and O.ref_ensures(parts))
        with ThreadPoolExecutor(max_workers=32) as ex:
            pos = dict(ex.map(_pos, ALLT))
        json.dump(pos, open(PF, "w"))
    POS = set(tuple(k.split("|", 1)) for k, v in pos.items() if v)
    dropped = sorted(set((k[1], k[2]) for k in S) - POS)
    print("TASKFILTER: %d tasks without a reference contract left out: %s" % (len(dropped), dropped))
    S = {k: v for k, v in S.items() if (k[1], k[2]) in POS}
    S_noE = {k: v for k, v in S_noE.items() if (k[1], k[2]) in POS}
    CERT = POS if CERT is None else (CERT & POS)
    OUTJ = OUTJ.replace("/tmp/fix_final5", "/tmp/fix_final7")

# ---- witness arm v2 records that match the current state
# EXT=1 also reads the extended-budget pass (wit2.py PASS4, /tmp/wit2x_*.jsonl): the accepts the standard budget left
# unchanged for lack of budget, run again with more re-coding attempts and clause proposals. Separate output file.
EXT = os.environ.get("EXT", "") == "1"
if EXT:
    OUTJ = OUTJ.replace(".json", "_ext.json")
W = {}; W_ALL = []; W_ACT = set()
for f in sorted(glob.glob("/tmp/wit2_*.jsonl")) + (sorted(glob.glob("/tmp/wit2x_*.jsonl")) if EXT else []):
    # /tmp/wit2_rescore.jsonl is THIS script's cache, not a repair record file. Until 2026-11-19 it was read here
    # too: its rows carry no spec_before, so for an accept whose state has no stored specification text they
    # "matched" and replaced the real record (2 accepts, one of them a repair).
    if "smoke" in f or "rescore" in f:
        continue
    for r in jl(f):
        if "stop" not in r:
            continue
        W_ALL.append(r)
        k = (r["model"], r["source"], r["task"])
        if r.get("stop") == "api-fail" or k not in S:
            continue
        if H.nows(r.get("spec_before")) == H.nows(S[k]["spec"]):
            # keep-on-fail across passes: a later pass that starts again from the same accepted state and ends
            # without a change does not undo the strengthening an earlier pass verified (7 accepts)
            if k in W and W[k].get("changed") and not r.get("changed"):
                continue
            W[k] = r                      # the latest pass for the current state
            if r.get("activated"):
                W_ACT.add(k)
# re-score changed specifications with the final oracle (cached)
CACHE = "/tmp/wit2_rescore.jsonl"
cache = {(r["model"], r["source"], r["task"], r["spec"]): r for r in jl(CACHE)}
todo = [k for k, r in W.items() if r.get("changed") and (k[0], k[1], k[2], H.nows(r["final_spec"])) not in cache]
lock = threading.Lock()


def rescore(k):
    r = W[k]; parts = H.task_parts(k[1], k[2])
    rel, rc, _ = O.rel2(parts, r["final_spec"], r.get("final_code")); det, dc, _ = O.det2(parts, r["final_spec"], r.get("final_code"))
    cn, cc = O.canon_check(parts, r.get("final_code"), r["final_spec"])
    o = {"model": k[0], "source": k[1], "task": k[2], "spec": H.nows(r["final_spec"]), "rel": rel, "det": det, "canon": cn}
    with lock:
        with open(CACHE, "a") as f:
            f.write(json.dumps(o) + NL)
    return o


if todo:
    with ThreadPoolExecutor(max_workers=32) as ex:
        for o in ex.map(rescore, todo):
            cache[(o["model"], o["source"], o["task"], o["spec"])] = o


def before(k):
    v = S[k]
    return v["accepted"], v["rel"], v["det"]


BYC = set()      # repaired specifications whose reliability holds by construction but whose lemma did not finish


def after(k):
    v = S[k]; r = W.get(k)
    if v["accepted"] and r and r.get("changed"):
        c = cache.get((k[0], k[1], k[2], H.nows(r["final_spec"])))
        if c and c.get("canon") is True:
            rel = c["rel"]
            # the repaired specification is the original one plus added clauses (S' = S && C), so S' implies S.
            # If S => G was proved, S' => G holds by construction, whether or not the bigger lemma finishes in time.
            if v["rel"] is True and rel is not True and H.nows(r["final_spec"]).startswith(H.nows(O.spec_text(O.spec_ensures(v["spec"])))):
                rel = True; BYC.add(k)
            return True, rel, c["det"]
    return v["accepted"], v["rel"], v["det"]


def paper(k):
    """the state the current paper text reports: first pass, first oracle, no audit"""
    r = base[k]
    if r.get("status") == "accepted":
        return True, r.get("reliable_gt"), r.get("signals", {}).get("determinacy")
    return False, None, None


def noE(k):
    v = S_noE[k]
    return v["accepted"], v["rel"], v["det"]


def stats(keys, f):
    n = len(keys); a = s = t = ck = ct = 0
    for k in keys:
        acc, rel, det = f(k)
        if acc:
            a += 1
            if rel is not None:
                s += 1; t += rel is True
                if det == 1.0:
                    ck += 1; ct += rel is True
    return dict(n=n, acc=a, sc=s, rel=t, weak=s - t, na=a - s, kept=ck, kept_rel=ct, kept_weak=ck - ct, drop_rel=t - ct, drop_weak=(s - t) - (ck - ct),
                accp=100.0 * a / max(1, n), relS=100.0 * t / max(1, s), rvS=100.0 * t / max(1, n), cert=100.0 * ct / max(1, ck), cov=100.0 * ck / max(1, s))


def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); rk = [0.0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for t in range(i, j + 1):
            rk[o[t]] = (i + j) / 2.0 + 1
        i = j + 1
    return rk


def pearson(a, b):
    n = len(a); ma = sum(a) / n; mb = sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** .5; sb = sum((y - mb) ** 2 for y in b) ** .5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


def spearman(a, b, nperm=50000):
    ra, rb = rank(a), rank(b); rho = pearson(ra, rb)
    random.seed(7); cnt = 0; rb2 = rb[:]
    for _ in range(nperm):
        random.shuffle(rb2)
        if abs(pearson(ra, rb2)) >= abs(rho) - 1e-12:
            cnt += 1
    return rho, cnt / nperm


bym = collections.defaultdict(list)
for k in S:
    bym[k[0]].append(k)
out = {"models": {}, "total": {}, "corr": {}, "strata": {}, "meta": {}}
VIEWS = [("paper", paper), ("audit", noE), ("before", before), ("after", after)]
print("views: paper = first pass + first oracle (what the paper text has) | audit = oracle v4 + canonical accepts | before = audit + stage E | after = before + witness repair v2")
print("%-22s %4s | %-21s | %-21s | %-21s | %-21s" % ("model", "n", "paper acc/corr/weak", "audit acc/corr/weak", "before acc/corr/weak", "after acc/corr/weak"))
for m in H.P11:
    ks = bym[m]; row = {}
    for name, f in VIEWS:
        row[name] = stats(ks, f)
        row[name]["by_source"] = {s: stats([k for k in ks if k[1] == s], f) for s in SRC}
    out["models"][m] = row
    print("%-22s %4d | %3d %3d %3d (%4.1f%%) | %3d %3d %3d (%4.1f%%) | %3d %3d %3d (%4.1f%%) | %3d %3d %3d (%4.1f%%)" % (
        m.split(":")[-1], row["paper"]["n"], *[x for name, _ in VIEWS for x in (row[name]["acc"], row[name]["rel"], row[name]["weak"], row[name]["relS"])]))
for name, f in VIEWS:
    st = stats(list(S), f); out["total"][name] = st
    out["total"][name + "_cloud"] = stats([k for k in S if k[0] in CLOUD], f)
    print("TOTAL %-6s accepted %4d assessable %4d correct %4d (%.1f%%) weak %4d (%.1f%%) n/a %3d | certified: kept %4d of which correct %4d (%.1f%%), wrong left %3d ; dropped correct %3d wrong %3d" % (
        name, st["acc"], st["sc"], st["rel"], st["relS"], st["weak"], 100 - st["relS"], st["na"], st["kept"], st["kept_rel"], st["cert"], st["kept_weak"], st["drop_rel"], st["drop_weak"]))
for name, f in VIEWS:
    A = [out["models"][m][name]["accp"] for m in H.P11]; Rr = [out["models"][m][name]["relS"] for m in H.P11]
    G = [out["models"][m][name]["acc"] - out["models"][m][name]["rel"] for m in H.P11]; C = [out["models"][m][name]["rel"] for m in H.P11]
    Wk = [out["models"][m][name]["weak"] for m in H.P11]
    r1, p1 = spearman(A, Rr); r2, p2 = spearman(A, G); r3, p3 = spearman(A, Wk)
    out["corr"][name] = {"acc_rel": [r1, p1], "acc_gap": [r2, p2], "acc_weak": [r3, p3]}
    print("%-6s Spearman acceptance~reliability %+.2f (p=%.3f) | acceptance~(accepted - correct) %+.2f (p=%.4f) | acceptance~weak count %+.2f (p=%.4f)" % (name, r1, p1, r2, p2, r3, p3))
    for s in SRC:
        A2 = [out["models"][m][name]["by_source"][s]["accp"] for m in H.P11]; R2 = [out["models"][m][name]["by_source"][s]["relS"] for m in H.P11]
        r, p = spearman(A2, R2, 20000); out["corr"][name][s] = [r, p]
        print("          %-15s acceptance~reliability %+.2f (p=%.3f)" % (s, r, p))
# difficulty strata (before repair)
for name, f in [("paper", paper), ("before", before)]:
    T = collections.defaultdict(dict)
    for k in S:
        T[(k[1], k[2])][k[0]] = f(k)
    nacc = {t: sum(1 for m in H.P11 if d.get(m, (False,))[0]) for t, d in T.items()}
    rows = []
    for lo, hi in [(1, 2), (3, 4), (5, 7), (8, 10), (11, 11)]:
        L = [d[m] for t, d in T.items() for m in H.P11 if lo <= nacc[t] <= hi and m in d and d[m][0] and d[m][1] is not None]
        rel = 100.0 * sum(1 for x in L if x[1] is True) / max(1, len(L))
        rows.append({"lo": lo, "hi": hi, "n": len(L), "rel": rel, "tasks": sum(1 for t in nacc if lo <= nacc[t] <= hi)})
    out["strata"][name] = rows
    print("strata %-6s " % name + " | ".join("%d-%d models: %d tasks, %d accepts, %.0f%% correct" % (r["lo"], r["hi"], r["tasks"], r["n"], r["rel"]) for r in rows))
    common = [t for t, d in T.items() if all(m in d and d[m][0] and d[m][1] is not None for m in H.P11)]
    A = [out["models"][m][name]["accp"] for m in H.P11]
    RC = [100.0 * sum(1 for t in common if T[t][m][1] is True) / max(1, len(common)) for m in H.P11]
    r, p = spearman(A, RC, 20000)
    out["strata"][name + "_common"] = {"n": len(common), "rho": r, "p": p}
    print("       common tasks (accepted+assessable for all 11): %d, acceptance~reliability there %+.2f (p=%.3f)" % (len(common), r, p))

# ---- repair: witness arm v2 on the final state
rep = collections.Counter()
for k, r in W.items():
    b = before(k); a = after(k)
    rep["targets"] += 1; rep["targets_weak"] += b[1] is False; rep["targets_good"] += b[1] is True
    rep["activated"] += (k in W_ACT); rep["changed"] += bool(r.get("changed"))
    rep["pass%s" % r.get("pass", 1)] += 1
    rep["fixed"] += (b[1] is False and a[1] is True); rep["broke"] += (b[1] is True and a[1] is not True)
    rep["tightened_good"] += (b[1] is True and r.get("changed") and a[1] is True)
    rep["stop:" + str(r.get("stop"))] += 1
    rep["det_gain"] += (b[2] == 0.0 and a[2] == 1.0)
rep["reliable_by_construction_lemma_unfinished"] = len(BYC)
rep["cost_usd"] = round(sum((r.get("cost") or {}).get("cost_usd", 0) for r in W_ALL), 2); rep["calls"] = sum((r.get("cost") or {}).get("calls", 0) for r in W_ALL)
out["repair"] = dict(rep)
print("witness repair v2:", dict(rep))
print("   fixed per model:", dict(collections.Counter(k[0].split(":")[-1] for k in W if before(k)[1] is False and after(k)[1] is True)))

# ---- repair arms on a common record set, uniform keep-on-fail rule
A4 = jl("/tmp/fix_arms6.jsonl") or jl("/tmp/fix_arms4.jsonl")
if A4:
    sc4 = {(r["model"], r["source"], r["task"]): r for r in (jl("/tmp/fix_scores6.jsonl") or jl("/tmp/fix_scores5.jsonl"))}
    common = set(k for k, v in S0.items() if v["accepted"] and v["origin"] == "orig" and k not in E and k in sc4 and sc4[k].get("canon") is True
                 and sc4[k]["rel"] is not None and not sc4[k].get("respec") and (CERT is None or (k[1], k[2]) in CERT))
    for label, keyset in [("all 11 models", common), ("9 cloud models", set(k for k in common if k[0] in CLOUD))]:
        print("repair arms on the common set (%s): %d accepts, weak %d, good %d" % (label, len(keyset), sum(1 for k in keyset if sc4[k]["rel"] is False),
                                                                                    sum(1 for k in keyset if sc4[k]["rel"] is True)))
        res = {}
        # the arms' re-coded bodies come from the first big run, which had no bypass filter. A change whose body
        # verifies only through assume / {:axiom} is not a valid change (conj_arms.py marks them, same rule as ours).
        BYP = set((a["model"], a["source"], a["task"], a["arm"]) for a in jl("/tmp/fix_arms_conj.jsonl") if a.get("plain_bypass"))
        for arm in ["arm_ours", "arm_judge", "arm_determinacy", "arm_witness"]:
            c = collections.Counter()
            for a in A4:
                k = (a["model"], a["source"], a["task"])
                if a["arm"] != arm or k not in keyset:
                    continue
                byp = (k[0], k[1], k[2], arm) in BYP
                c["bypass_body"] += bool(a["changed"] and a.get("canon_after") is True and byp)
                b = sc4[k]["rel"]; valid = a["changed"] and a.get("canon_after") is True and not byp
                c["n"] += 1; c["changed"] += bool(a["changed"]); c["valid_change"] += bool(valid); c["reverted"] += bool(a["changed"] and not valid)
                if valid:
                    c["fixed"] += (b is False and a.get("after") is True); c["broke"] += (b is True and a.get("after") is False)
                    c["unassessable_after"] += (b is True and a.get("after") is None)
            res[arm] = dict(c)
            print("   %-16s n %4d changed %4d valid %4d reverted %4d (of which bypass body %d) | fixed %3d broke %3d (good -> not assessable %d)" % (
                arm, c["n"], c["changed"], c["valid_change"], c["reverted"], c["bypass_body"], c["fixed"], c["broke"], c["unassessable_after"]))
        c = collections.Counter()
        for k in keyset:
            r = W.get(k)
            if not r:
                continue
            b = before(k); a = after(k)
            c["n"] += 1; c["activated"] += (k in W_ACT); c["changed"] += bool(r.get("changed"))
            c["fixed"] += (b[1] is False and a[1] is True); c["broke"] += (b[1] is True and a[1] is not True)
        res["witness_v2"] = dict(c)
        print("   %-16s targets %4d activated %4d changed %4d | fixed %3d broke %3d" % ("witness v2", c["n"], c["activated"], c["changed"], c["fixed"], c["broke"]))
        # ---- the same stored proposals of the other arms under OUR acceptance rule (conj_arms.py): the new
        # specification is the original one AND the proposal, kept only if a stored body verifies under it
        CJ = jl("/tmp/fix_arms_conj.jsonl")
        cand = collections.defaultdict(list)       # accept -> [(arm, verdict after, determinacy after)] of valid conjunctive changes
        for arm in ["arm_ours", "arm_judge", "arm_determinacy"]:
            c = collections.Counter()
            for a in CJ:
                k = (a["model"], a["source"], a["task"])
                if a["arm"] != arm or k not in keyset or "skip" in a or "error" in a:
                    continue
                b = sc4[k]["rel"]; valid = a.get("conj_valid") is True
                c["n"] += 1; c["valid_change"] += bool(valid)
                if valid:
                    c["fixed"] += (b is False and a.get("conj_after") is True); c["broke"] += (b is True and a.get("conj_after") is not True)
                    c["by_construction"] += bool(a.get("by_construction")); c["det_gain"] += (sc4[k].get("det") == 0.0 and a.get("det") == 1.0)
                    cand[k].append((arm, a.get("conj_after"), a.get("det")))
            res[arm + "+conj"] = dict(c)
            print("   %-22s proposals %4d valid %4d | fixed %3d broke %3d (correct by construction, lemma unfinished: %d) | made determinate %d" % (
                arm + " + conj", c["n"], c["valid_change"], c["fixed"], c["broke"], c["by_construction"], c["det_gain"]))
        # every proposer under the conjunctive rule. The choice between several valid strengthenings of one accept
        # uses no reference: one that makes the specification provably determinate first, then a fixed order.
        ORDER = {"witness_v2": 0, "arm_determinacy": 1, "arm_judge": 2, "arm_ours": 3}
        c = collections.Counter()
        for k in keyset:
            cs = list(cand.get(k, []))
            r = W.get(k)
            # only a VALID witness change is a candidate (its body verifies canonically, as for the other proposers);
            # before 2026-11-20 an invalid one was a candidate too and could be chosen over a valid repair
            cw = cache.get((k[0], k[1], k[2], H.nows(r["final_spec"]))) if (r and r.get("changed")) else None
            if cw and cw.get("canon") is True:
                a = after(k); cs.append(("witness_v2", a[1], a[2]))
            if not cs:
                continue
            cs.sort(key=lambda x: (0 if x[2] == 1.0 else 1, ORDER[x[0]]))
            ch = cs[0]; b = sc4[k]["rel"]
            c["changed"] += 1; c["fixed"] += (b is False and ch[1] is True); c["broke"] += (b is True and ch[1] is not True)
            c["det_gain"] += (sc4[k].get("det") == 0.0 and ch[2] == 1.0); c["chosen:" + ch[0]] += 1
            c["fixed_by_any"] += (b is False and any(x[1] is True for x in cs))
        res["portfolio_conj"] = dict(c)
        print("   %-22s changed %4d | fixed %3d broke %3d | made determinate %d | fixed by at least one proposer %d | chosen: %s" % (
            "all proposers + conj", c["changed"], c["fixed"], c["broke"], c["det_gain"], c["fixed_by_any"],
            {kk[7:]: v for kk, v in c.items() if kk.startswith("chosen:")}))
        out.setdefault("arms", {})[label] = {"n": len(keyset), "weak": sum(1 for k in keyset if sc4[k]["rel"] is False), "arms": res}
out["meta"] = {"E_records": len(E), "W_records": len(W), "demoted_noncanonical": sum(1 for v in S.values() if v["note"].startswith("non-canonical")),
               "cloud": CLOUD}
out["meta"]["taskset"] = TASKSET or "all"
json.dump(out, open(OUTJ, "w"), indent=1)
print("wrote", OUTJ)
