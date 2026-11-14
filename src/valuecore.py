"""Value-core non-determinism-aware oracle for INDEX-returning tasks (result:int indexing an array param).
Correctness is judged by the OBSERVABLE VALUE a[result], not by the GT's arbitrary tie-breaking position.
  - Enumerate the GT-admitted outputs for a concrete input; their observable values {a[o] : GT(x,o)} are
    the CORRECT values.
  - The candidate spec S is RELIABLE (sound) iff every output S admits is in bounds and has an observable
    value in the correct set. S is UNRELIABLE iff it admits an output whose a[result] is not a correct value.
This credits any-max (same max value) while rejecting bounds-only (admits non-max values). No model needed.
"""
import os, sys, re, glob, random
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
random.seed(17)
CANDS = list(range(-2, 14))


def gen_inputs(params, n=8):
    outs = []
    for _ in range(n):
        decls = []; pyv = {}; ok = True
        for pn, pt in params:
            ptc = pt.replace(" ", "")
            if ptc == "array<int>":
                m = random.randint(2, 4); base = random.randint(-3, 3)
                vals = [base + random.choice([-2, -1, 0, 0, 1, 2]) for _ in range(m)]
                # force some ties to exercise non-determinism
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


def admitted(parts, ens_str, pyv, decls, rvar):
    ens = V.ensures_list("method _() returns ()\n  " + ens_str)
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    pred = "(" + " && ".join("(%s)" % e for e in ens) + ")"
    prec = "(" + " && ".join("(%s)" % r for r in reqs) + ")" if reqs else "true"
    blocks = ["  { %s if %s { var %s := %d; var ok := %s; print \"R%d=\", ok, \"\\n\"; } }"
              % (decls, prec, rvar, c, pred, c) for c in CANDS]
    out = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(blocks) + "\n}\n")
    return set(int(m.group(1)) for m in re.finditer(r"R(-?\d+)=true", out))


def valuecore_reliable(parts, gen_ens):
    sig = V.parse_sig(parts["vc-spec"])
    if not sig or not sig[2]:
        return None, "nosig"
    name, params, (rvar, rt) = sig
    if rt.replace(" ", "") not in ("int", "nat"):
        return None, "rettype"
    arr = next((pn for pn, pt in params if pt.replace(" ", "") == "array<int>"), None)
    if arr is None:
        return None, "noarray"
    gt_str = "\n    ".join("ensures " + e for e in V.ensures_list(parts["vc-spec"]))
    checked = bad = 0
    for pyv, decls in gen_inputs(params):
        a = pyv[arr]
        gt_outs = admitted(parts, gt_str, pyv, decls, rvar)
        gt_outs = {o for o in gt_outs if 0 <= o < len(a)}
        if not gt_outs:
            continue
        correct_vals = {a[o] for o in gt_outs}           # observable values of correct outputs
        s_outs = admitted(parts, gen_ens, pyv, decls, rvar)
        checked += 1
        # S unsound if it admits an in-range output with a wrong value, OR an out-of-range index
        for o in s_outs:
            if not (0 <= o < len(a)) or a[o] not in correct_vals:
                bad += 1; break
    if checked == 0:
        return None, "noeval"
    return (bad == 0), "valuecore(%d/%d clean)" % (checked - bad, checked)


def main():
    import nl_gated_compare as NG
    pb = V.load(glob.glob(V.BENCH + "/numpy_simple/yaml/NpArgmax-spec.yaml")[0])
    gt = "\n    ".join("ensures " + e for e in V.ensures_list(pb["vc-spec"]))
    cases = [
        ("any-max (opus repair; should be RELIABLE)",
         "ensures 0 <= result < arr.Length\n    ensures forall i :: 0 <= i < arr.Length ==> arr[i] <= arr[result]"),
        ("first-max (GT itself; RELIABLE)", gt),
        ("bounds-only (WEAK; should be UNRELIABLE)", "ensures 0 <= result < arr.Length"),
        ("wrong: any MIN index (should be UNRELIABLE)",
         "ensures 0 <= result < arr.Length\n    ensures forall i :: 0 <= i < arr.Length ==> arr[i] >= arr[result]"),
    ]
    print("task: NpArgmax")
    for lab, gen in cases:
        strict = NG.reliable_gt(pb, gen)
        vc, detail = valuecore_reliable(pb, gen)
        print("  %-46s strict=%-5s  value-core=%-5s (%s)" % (lab, strict, vc, detail), flush=True)


if __name__ == "__main__":
    main()
