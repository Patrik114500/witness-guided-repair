"""Expanded key-free multi-impl invariant miner: now covers int/nat AND array<int> returns with a richer
template library. Goal: cover more real non-deterministic benchmark tasks (not just argmax-pattern)."""
import os, sys, re, glob, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
random.seed(7)
KIMPL = int(os.environ.get("KIMPL", "3"))
NIN = int(os.environ.get("NIN", "8"))


def int_templates(params):
    arr = [pn for pn, pt in params if pt.replace(" ", "") == "array<int>"]
    scal = [pn for pn, pt in params if pt.replace(" ", "") in ("int", "nat")]
    T = []
    for a in arr:
        T += [
            (lambda v, r, a=a: 0 <= r < len(v[a]), "0 <= result < %s.Length" % a),
            (lambda v, r, a=a: all(v[a][r] >= x for x in v[a]), "forall k :: 0 <= k < %s.Length ==> %s[result] >= %s[k]" % (a, a, a)),
            (lambda v, r, a=a: all(v[a][r] <= x for x in v[a]), "forall k :: 0 <= k < %s.Length ==> %s[result] <= %s[k]" % (a, a, a)),
            (lambda v, r, a=a: all(r >= x for x in v[a]), "forall k :: 0 <= k < %s.Length ==> result >= %s[k]" % (a, a)),
            (lambda v, r, a=a: all(r <= x for x in v[a]), "forall k :: 0 <= k < %s.Length ==> result <= %s[k]" % (a, a)),
            (lambda v, r, a=a: any(r == x for x in v[a]), "exists k :: 0 <= k < %s.Length && result == %s[k]" % (a, a)),
            (lambda v, r, a=a: r == sum(v[a]), "result == %s_sum" % a),  # placeholder (needs helper); kept for reference
            (lambda v, r, a=a: 0 <= r <= len(v[a]), "0 <= result <= %s.Length" % a),
        ]
        for s in scal:
            T.append((lambda v, r, a=a, s=s: 0 <= r < len(v[a]) and v[a][r] == v[s], "0 <= result < %s.Length && %s[result] == %s" % (a, a, s)))
    for s in scal:
        T += [(lambda v, r, s=s: r == v[s], "result == %s" % s),
              (lambda v, r, s=s: r >= v[s], "result >= %s" % s),
              (lambda v, r, s=s: r <= v[s], "result <= %s" % s)]
    T.append((lambda v, r: r >= 0, "result >= 0"))
    return [(f, e) for f, e in T if "_sum" not in e]  # drop placeholder templates needing helpers


def arr_templates(params, rvar):
    arr = [pn for pn, pt in params if pt.replace(" ", "") == "array<int>"]
    scal = [pn for pn, pt in params if pt.replace(" ", "") in ("int", "nat")]
    T = [
        (lambda v, r: all(r[i] >= 0 for i in range(len(r))), "forall i :: 0 <= i < result.Length ==> result[i] >= 0"),
        (lambda v, r: all(r[i] <= r[i + 1] for i in range(len(r) - 1)), "forall i :: 0 <= i < result.Length - 1 ==> result[i] <= result[i+1]"),
        (lambda v, r: all(r[i] >= r[i + 1] for i in range(len(r) - 1)), "forall i :: 0 <= i < result.Length - 1 ==> result[i] >= result[i+1]"),
    ]
    for a in arr:
        T += [
            (lambda v, r, a=a: len(r) == len(v[a]), "result.Length == %s.Length" % a),
            (lambda v, r, a=a: len(r) == len(v[a]) and all(r[i] == v[a][i] for i in range(len(r))), "result.Length == %s.Length && forall i :: 0 <= i < result.Length ==> result[i] == %s[i]" % (a, a)),
            (lambda v, r, a=a: len(r) == len(v[a]) and all(r[i] == v[a][i] + 1 for i in range(len(r))), "result.Length == %s.Length && forall i :: 0 <= i < result.Length ==> result[i] == %s[i] + 1" % (a, a)),
            (lambda v, r, a=a: len(r) == len(v[a]) and all(r[i] == -v[a][i] for i in range(len(r))), "result.Length == %s.Length && forall i :: 0 <= i < result.Length ==> result[i] == -%s[i]" % (a, a)),
            (lambda v, r, a=a: len(r) == len(v[a]) and all(r[i] >= v[a][i] for i in range(len(r))), "result.Length == %s.Length && forall i :: 0 <= i < result.Length ==> result[i] >= %s[i]" % (a, a)),
        ]
        for s in scal:
            T.append((lambda v, r, a=a, s=s: len(r) == v[s], "result.Length == %s" % s))
    return T


def gen_inputs(params, n):
    outs = []
    for _ in range(n):
        v = {}; decls = []
        okk = True
        for pn, pt in params:
            ptc = pt.replace(" ", "")
            if ptc == "array<int>":
                ln = random.randint(2, 4); base = random.randint(-3, 3)
                arr = [base + random.choice([-2, -1, 0, 0, 1, 2]) for _ in range(ln)]
                v[pn] = arr
                decls.append("var %s := new int[%d];" % (pn, ln) + "".join(" %s[%d] := %d;" % (pn, i, x) for i, x in enumerate(arr)))
            elif ptc in ("int", "nat"):
                x = random.randint(0, 4); v[pn] = x; decls.append("var %s := %d;" % (pn, x))
            else:
                okk = False
        if okk:
            outs.append((v, " ".join(decls)))
    return outs


def run_impl(parts, method, params, inputs, rt0):
    name = V.parse_sig(parts["vc-spec"])[0]
    pb = []
    for i, (v, decls) in enumerate(inputs):
        args = ", ".join(pn for pn, _ in params)
        if rt0 == "array<int>":
            pb.append('  { %s var r := %s(%s); print "I%d:["; var j:=0; while j<r.Length{print r[j]; if j<r.Length-1{print ",";} j:=j+1;} print "]\\n"; }' % (decls, name, args, i))
        else:
            pb.append('  { %s var r := %s(%s); print "I%d:", r, "\\n"; }' % (decls, name, args, i))
    out = V.drun(V.assemble(parts, method) + "\nmethod Main() {\n" + "\n".join(pb) + "\n}\n")
    res = {}
    for i, _ in enumerate(inputs):
        if rt0 == "array<int>":
            m = re.search(r"I%d:\[([^\]]*)\]" % i, out)
            if m:
                res[i] = [int(x) for x in m.group(1).split(",") if x.strip().lstrip("-").isdigit()] if m.group(1).strip() else []
        else:
            m = re.search(r"I%d:(-?\d+)" % i, out)
            if m:
                res[i] = int(m.group(1))
    return res


def mine(T, inputs, impl_outs):
    mined = []
    for pyf, dexpr in T:
        ok = True
        for outs in impl_outs:
            for i, r in outs.items():
                try:
                    if not pyf(inputs[i][0], r):
                        ok = False; break
                except Exception:
                    ok = False; break
            if not ok:
                break
        if ok:
            mined.append(dexpr)
    return mined


def implies(parts, spec_ens, invs):
    sig = V.parse_sig(parts["vc-spec"]); name, params, (rvar, rt) = sig
    plist = ", ".join("%s: %s" % (n, t) for n, t in params) + (", " if params else "") + "result: %s" % rt
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    lem = V.pre(parts) + "\nlemma Chk(%s)\n" % plist
    for r in reqs: lem += "  requires %s\n" % r
    for e in spec_ens: lem += "  requires %s\n" % e
    for e in invs: lem += "  ensures %s\n" % e
    lem += "{}\n"
    ok, _ = V.dverify(lem); return ok


def weak_spec_for(parts, params, rt0):
    arr = [pn for pn, pt in params if pt.replace(" ", "") == "array<int>"]
    if rt0 in ("int", "nat") and arr:
        return ["0 <= result < %s.Length" % arr[0]]
    if rt0 == "array<int>" and arr:
        return ["result.Length == %s.Length" % arr[0]]
    return ["true"]


def main():
    from det_gate import completeness_determinacy
    scan = json.load(open("/tmp/nondet_scan.json"))
    tasks = os.environ.get("TASKS", "")
    if tasks:
        items = [(k, v) for k, v in scan.items() if any(t in k for t in tasks.split(","))]
    else:
        items = [(k, v) for k, v in scan.items() if v.get("gt_determinate") is False and v.get("rettype") in ("int", "nat", "array<int>")]
    MODEL = os.environ.get("MODEL", "qwen2.5-coder:32b")
    OUT = os.environ.get("OUT", "/tmp/miner2_res.json")
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for key, v in items:
        if key in res: continue
        src, task = v["src"], v["task"]
        f = V.BENCH + "/%s/yaml/%s" % (src, task)
        rec = {"task": task, "src": src}
        try:
            parts = V.load(f); sig = V.parse_sig(parts["vc-spec"])
            rt0 = sig[2][1].replace(" ", "") if sig and sig[2] else None
            if rt0 not in ("int", "nat", "array<int>"):
                rec["skip"] = "rettype %s" % rt0
            else:
                name, params, (rvar, rt) = sig
                gt = V.ensures_list(parts["vc-spec"])
                impls = []
                for k in range(KIMPL + 3):
                    r = V.run_cfs(MODEL, parts)
                    if r.get("success"): impls.append(r["method"])
                    if len(impls) >= KIMPL: break
                if not impls:
                    rec["skip"] = "no verifying impl"
                else:
                    inputs = gen_inputs(params, NIN)
                    impl_outs = [run_impl(parts, m, params, inputs, rt0) for m in impls]
                    T = arr_templates(params, rvar) if rt0 == "array<int>" else int_templates(params)
                    mined = mine(T, inputs, impl_outs)
                    rec["nimpl"] = len(impls); rec["mined"] = mined
                    if mined:
                        rec["ours_gt"] = bool(implies(parts, gt, mined))
                        rec["ours_weak"] = bool(implies(parts, weak_spec_for(parts, params, rt0), mined))
                    rec["det_gt"] = (completeness_determinacy(parts, "\n    ".join("ensures " + e for e in gt)) == 1.0)
        except Exception as e:
            rec["err"] = str(e)[:100]
        res[key] = rec
        json.dump(res, open(OUT, "w"), indent=1)
        print("  %-26s mined=%s ours_gt=%s ours_weak=%s det_gt=%s %s" % (
            task.replace("-spec.yaml", "").replace("_task.yaml", ""), len(rec.get("mined", [])),
            rec.get("ours_gt"), rec.get("ours_weak"), rec.get("det_gt"), rec.get("skip", rec.get("err", ""))), flush=True)
    cov = sum(1 for r in res.values() if r.get("mined"))
    print("\nDONE | tasks with mined invariants (covered): %d / %d" % (cov, len(res)))


if __name__ == "__main__":
    main()
