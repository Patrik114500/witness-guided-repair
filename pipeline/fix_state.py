"""Final state of every big-run task after the harness fixes (stages A-D): is it accepted, with which code,
against which specification of record, and how it scored. One loader so that later stages (witness arm v2,
tables) all read the same state. Read-only."""
import os, sys, re, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H

NL = chr(10)


def _jsonl(path):
    out = []
    if os.path.exists(path):
        for l in open(path):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def load(models=None):
    """key -> dict(accepted, rel, det, code, spec, origin, gen_verbatim). key = (model, source, task)."""
    base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(models or H.P11))}
    sc = {}
    for r in _jsonl("/tmp/fix_scores.jsonl"):
        sc[(r["model"], r["source"], r["task"])] = r
    resc = {}
    for f in ["/tmp/fix_rescueA.jsonl"] + sorted(glob.glob("/tmp/fix_rescueB_*.jsonl")):
        for r in _jsonl(f):
            k = (r["model"], r["source"], r["task"])
            if r.get("rescued") and k not in resc:
                resc[k] = r["code"]
    rescD = {}
    for f in sorted(glob.glob("/tmp/fix_rescueD_*.jsonl")):
        for r in _jsonl(f):
            if r.get("rescued"):
                rescD[(r["model"], r["source"], r["task"])] = r["code"]
    out = {}
    for k, r in base.items():
        s = sc.get(k)
        o = {"accepted": False, "rel": None, "det": None, "code": None, "spec": None, "origin": "orig", "gen": r.get("gen_spec") or ""}
        if s is not None:
            o["origin"] = s.get("origin")
            if s.get("accepted"):
                o["accepted"] = True; o["rel"] = s.get("reliable_gt"); o["det"] = s.get("determinacy")
                if o["origin"] == "rescueD":
                    o["code"] = rescD.get(k)
                elif o["origin"] in ("rescueA", "rescueB"):
                    o["code"] = resc.get(k)
                else:
                    o["code"] = (r.get("code_attempts") or [{}])[-1].get("code")
                o["gen_verbatim"] = s.get("gen_verbatim")
        elif r.get("status") == "accepted":
            o["accepted"] = True; o["rel"] = r.get("reliable_gt"); o["det"] = r.get("signals", {}).get("determinacy")
            o["code"] = (r.get("code_attempts") or [{}])[-1].get("code"); o["gen_verbatim"] = True
        if o["accepted"]:
            if o.get("gen_verbatim"):
                o["spec"] = o["gen"]
            else:
                try:
                    parts = H.task_parts(k[1], k[2]); sig = V.parse_sig(parts["vc-spec"])
                    ce = H.method_ensures(o["code"] or "", sig[0]) if sig else None
                    o["spec"] = (NL + "    ").join("ensures " + e for e in ce) if ce else ""
                except Exception:
                    o["spec"] = ""
        out[k] = o
    return out


if __name__ == "__main__":
    import collections
    S = load()
    acc = {k: v for k, v in S.items() if v["accepted"]}
    print("tasks %d accepted %d scorable %d reliable %d" % (len(S), len(acc), sum(1 for v in acc.values() if v["rel"] is not None),
                                                          sum(1 for v in acc.values() if v["rel"] is True)))
    print("accepted without code:", sum(1 for v in acc.values() if not v["code"]), "| without spec:", sum(1 for v in acc.values() if not (v["spec"] or "").strip()))
    # flagged = determinacy says non-determinate
    print("%-26s %5s %5s | flagged: weak good n/a | old( in spec: weak good n/a | old( in G" % ("model", "acc", "flag"))
    partsc = {}
    tot = collections.Counter()
    for m in H.P11:
        c = collections.Counter()
        for k, v in acc.items():
            if k[0] != m:
                continue
            c["acc"] += 1
            if (k[1], k[2]) not in partsc:
                partsc[(k[1], k[2])] = H.task_parts(k[1], k[2])
            g = partsc[(k[1], k[2])]["vc-spec"]
            oldS = "old(" in (v["spec"] or ""); oldG = "old(" in g
            if v["det"] in (0, 0.0):
                c["flag"] += 1
                c["f_" + str(v["rel"])] += 1
            if oldS:
                c["oS_" + str(v["rel"])] += 1
            if oldG:
                c["oG"] += 1; c["oG_" + str(v["rel"])] += 1
            if re.search(r"decreases\s*\*", v["code"] or ""):
                c["decstar"] += 1
        tot.update(c)
        print("%-26s %5d %5d | %4d %4d %4d | %4d %4d %4d | G: %d (rel F/T/None %d/%d/%d) | decreases* %d" % (
            m, c["acc"], c["flag"], c["f_False"], c["f_True"], c["f_None"], c["oS_False"], c["oS_True"], c["oS_None"],
            c["oG"], c["oG_False"], c["oG_True"], c["oG_None"], c["decstar"]))
    print("TOTAL", dict(tot))
    # tasks whose reference spec uses old(: how do accepts score there?
    T = collections.defaultdict(list)
    for k, v in acc.items():
        if "old(" in partsc[(k[1], k[2])]["vc-spec"]:
            T[(k[1], k[2])].append(v["rel"])
    print("tasks with old( in the reference spec: %d ; accepts there by rel:" % len(T), dict(collections.Counter(str(x) for L in T.values() for x in L)))
    for t, L in sorted(T.items())[:40]:
        print("   %-50s %s" % (t[1][:50], dict(collections.Counter(str(x) for x in L))))
