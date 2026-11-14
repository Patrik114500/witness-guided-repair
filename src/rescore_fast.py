"""FAST value-core re-scoring: per task, FIXED inputs + GT-admitted computed ONCE (cached);
per spec, ALL inputs x candidates batched into ONE dafny run. ~4 drun/record instead of ~32."""
import os, sys, re, json, random
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
random.seed(17)
CANDS = list(range(-2, 14))
NIN = 4


def gen_inputs(params, n=NIN):
    outs = []
    for _ in range(n):
        decls = []; pyv = {}; ok = True
        for pn, pt in params:
            ptc = pt.replace(" ", "")
            if ptc == "array<int>":
                m = random.randint(2, 4); base = random.randint(-3, 3)
                vals = [base + random.choice([-2, -1, 0, 0, 1, 2]) for _ in range(m)]
                if random.random() < 0.5 and m >= 2:
                    vals[1] = vals[0]
                pyv[pn] = vals
                decls.append("var %s := new int[%d];" % (pn, m) + "".join(" %s[%d] := %d;" % (pn, i, x) for i, x in enumerate(vals)))
            elif ptc in ("int", "nat"):
                x = random.randint(0, 5); pyv[pn] = x; decls.append("var %s := %d;" % (pn, x))
            else:
                ok = False
        if ok:
            outs.append((pyv, " ".join(decls)))
    return outs


def admitted_multi(parts, ens_str, inputs, rvar):
    """ONE dafny run: for every (input i, candidate c) evaluate the spec predicate. -> {i: set(c)}"""
    ens = V.ensures_list("method _() returns ()\n  " + ens_str)
    if not ens:
        return None
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    pred = "(" + " && ".join("(%s)" % e for e in ens) + ")"
    prec = "(" + " && ".join("(%s)" % r for r in reqs) + ")" if reqs else "true"
    blocks = []
    for i, (pyv, decls) in enumerate(inputs):
        for c in CANDS:
            blocks.append("  { %s if %s { var %s := %d; var ok := %s; print \"I%d_%d=\", ok, \"\\n\"; } }"
                          % (decls, prec, rvar, c, pred, i, c))
    out = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(blocks) + "\n}\n")
    res = {i: set() for i in range(len(inputs))}
    for m in re.finditer(r"I(\d+)_(-?\d+)=true", out):
        res[int(m.group(1))].add(int(m.group(2)))
    return res


def main():
    recs = []
    for f in ["/tmp/big_run_local.jsonl", "/tmp/big_run_closed.jsonl"]:
        try:
            for l in open(f):
                try: recs.append(json.loads(l))
                except: pass
        except: pass
    acc = [r for r in recs if r.get("status") == "accepted" and r.get("gen_spec")]
    wb = {}
    try:
        for l in open("/tmp/witness_backfill.jsonl"):
            w = json.loads(l); wb[(w["model"], w["source"], w["task"])] = w["arm_witness"]
    except Exception:
        pass
    for r in acc:
        if "arm_witness" not in r:
            r["arm_witness"] = wb.get((r["model"], r["source"], r["task"]), {})
    # index-returning tasks
    cache = {}
    idx = []
    for r in acc:
        key = (r["source"], r["task"])
        if key not in cache:
            try:
                p = V.load(V.BENCH + "/%s/yaml/%s" % key)
                sig = V.parse_sig(p["vc-spec"])
                isidx = bool(sig and sig[2] and sig[2][1].replace(" ", "") in ("int", "nat")
                             and any(pt.replace(" ", "") == "array<int>" for _, pt in sig[1]))
                cache[key] = {"parts": p, "isidx": isidx}
            except Exception:
                cache[key] = {"isidx": False}
        if cache[key]["isidx"]:
            idx.append((r, key))
    print("index-returning accepts: %d" % len(idx), flush=True)

    # per-task fixture: fixed inputs + GT-admitted + correct value sets
    for key, c in cache.items():
        if not c.get("isidx"):
            continue
        p = c["parts"]; sig = V.parse_sig(p["vc-spec"])
        name, params, (rvar, rt) = sig
        arr = next(pn for pn, pt in params if pt.replace(" ", "") == "array<int>")
        inputs = gen_inputs(params)
        gt_str = "\n    ".join("ensures " + e for e in V.ensures_list(p["vc-spec"]))
        gt_adm = admitted_multi(p, gt_str, inputs, rvar)
        cv = {}
        for i, (pyv, _) in enumerate(inputs):
            a = pyv[arr]
            outs = {o for o in (gt_adm or {}).get(i, set()) if 0 <= o < len(a)}
            if outs:
                cv[i] = ({a[o] for o in outs}, a)
        c.update({"inputs": inputs, "cv": cv, "rvar": rvar, "arr": arr})
        print("  fixture %s/%s: %d usable inputs" % (key[0], key[1][:28], len(cv)), flush=True)

    def vc_score(key, ens):
        c = cache[key]
        if not c.get("cv"):
            return None
        adm = admitted_multi(c["parts"], ens, c["inputs"], c["rvar"])
        if adm is None:
            return None
        checked = bad = 0
        for i, (vals, a) in c["cv"].items():
            s_outs = adm.get(i, set())
            checked += 1
            for o in s_outs:
                if not (0 <= o < len(a)) or a[o] not in vals:
                    bad += 1; break
        return (bad == 0) if checked else None

    cols = {"baseline": lambda r: r.get("gen_spec"),
            "ours": lambda r: r.get("arm_ours", {}).get("final_spec"),
            "judge": lambda r: r.get("arm_judge", {}).get("final_spec"),
            "determinacy": lambda r: r.get("arm_determinacy", {}).get("final_spec"),
            "witness": lambda r: r.get("arm_witness", {}).get("final_spec")}
    strict = {"baseline": 0, "ours": 0, "judge": 0, "determinacy": 0, "witness": 0}
    vc = {"baseline": 0, "ours": 0, "judge": 0, "determinacy": 0, "witness": 0}
    rescued = 0; n = 0
    for r, key in idx:
        v0 = vc_score(key, r["gen_spec"])
        if v0 is None:
            continue
        n += 1
        if r.get("reliable_gt") is not True and v0 is True:
            rescued += 1
        for cname, get in cols.items():
            ens = get(r) or r["gen_spec"]
            st = r.get("reliable_gt") if cname == "baseline" else r.get("arm_%s" % cname, {}).get("reliable_gt_after")
            strict[cname] += (st is True)
            v = v0 if cname == "baseline" else vc_score(key, ens)
            vc[cname] += (v is True)
        print("  scored %d/%d" % (n, len(idx)), flush=True)
    print("\n=== value-core re-scoring (index-returning subset, n=%d) ===" % n)
    print("value-core RESCUES %d baseline accepts that strict called unreliable" % rescued)
    print("%-12s %10s %14s" % ("arm", "strict-rel", "valuecore-rel"))
    for cname in cols:
        print("  %-12s %8d %12d" % (cname, strict[cname], vc[cname]))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
