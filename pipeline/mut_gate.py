"""Mutation-differential key-free completeness gate (SOTA-grounded: mutation model checking + differential
equivalent-mutant filtering). Wrong outputs come from REAL program mutants of the verified reference, not
arbitrary perturbation. A mutant output is used only where it genuinely differs from the reference (M(x)!=R(x)),
which filters equivalent mutants. completeness = fraction of genuine wrong outputs the spec REJECTS.
Type-general (compares outputs), works wherever the reference executes.
"""
import os, sys, re, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import dafny_mut as DM

KRUN = int(os.environ.get("MUTKRUN", "6"))


def _run_method_on_inputs(method_src, parts, name, params, rt0, inputs):
    """run `name` on each input (list of (decls,args)), return {idx: output} by parsing printed I{idx}:."""
    pb = []
    for idx, decls, args in inputs:
        if rt0 in ("array<int>", "seq<int>"):
            ln = "r.Length" if rt0 == "array<int>" else "|r|"
            body = ('var r := %s(%s); print "I%d:["; var i:=0; while i<%s{print r[i]; if i<%s-1{print ",";} i:=i+1;} print "]\\n";'
                    % (name, args, idx, ln, ln))
        else:
            body = 'var r := %s(%s); print "I%d:", r, "\\n";' % (name, args, idx)
        pb.append("  { %s %s }" % (decls, body))
    out = V.drun(method_src + "\nmethod Main() {\n" + "\n".join(pb) + "\n}\n")
    res = {}
    for idx, _, _ in inputs:
        if rt0 in ("array<int>", "seq<int>"):
            m = re.search(r"I%d:\[([^\]]*)\]" % idx, out)
            if m:
                res[idx] = tuple(int(x) for x in m.group(1).split(",") if x.strip().lstrip("-").isdigit()) if m.group(1).strip() else ()
        else:
            m = re.search(r"I%d:(-?\d+(?:\.\d+)?|true|false)" % idx, out)
            if m:
                g = m.group(1); res[idx] = (g == "true") if rt0 == "bool" else int(float(g))
    return res


def measure_completeness_mut(parts, method, ens_exprs, maxmut=10):
    sig = V.parse_sig(parts["vc-spec"])
    if not sig or not sig[2]:
        return None
    name, params, (rvar, rt) = sig
    rt0 = rt.replace(" ", "")
    if rt0 not in ("int", "nat", "bool", "real", "seq<int>", "array<int>"):
        return None
    ptypes = [pt.replace(" ", "") for _, pt in params]
    if any(V.gen_val(pt)[1] is None for pt in ptypes):
        return None
    if not ens_exprs or any("old(" in e for e in ens_exprs):
        return None
    full = V.assemble(parts, method)

    # random inputs (shared length so equal-length preconditions hold)
    inputs = []
    for ki in range(KRUN):
        kn = random.randint(2, 4)
        vals = [V.gen_val(pt, kn) for pt in ptypes]
        decls = " ".join(V.lit_param(pn, v, t) for (pn, _), (v, t) in zip(params, vals))
        args = ", ".join(pn for pn, _ in params)
        inputs.append((ki, decls, args))

    # reference outputs
    ref = _run_method_on_inputs(full, parts, name, params, rt0, inputs)
    if not ref:
        return None

    # program mutants of the reference method body
    bs = DM.body_span(method)
    if not bs:
        return None
    mutants = DM.make_mutants(method, bs, maxn=maxmut)
    if not mutants:
        return None

    # collect genuine wrong outputs: (input_decls, wrong_output) where mutant(x) != ref(x)
    wrong = []  # (decls, output_value)
    for mi, mut in enumerate(mutants):
        mfull = V.assemble(parts, mut)
        mo = _run_method_on_inputs(mfull, parts, name, params, rt0, inputs)
        for idx, decls, args in inputs:
            if idx in ref and idx in mo and mo[idx] != ref[idx]:
                wrong.append((decls, mo[idx]))
    if not wrong:
        return None  # all mutants equivalent on these inputs -> cannot probe (inconclusive)

    # does the spec REJECT each genuine wrong output?
    pred = "(" + " && ".join("(%s)" % e for e in ens_exprs) + ")"
    cb = []
    for cid, (decls, ov) in enumerate(wrong):
        mo = list(ov) if rt0 in ("array<int>", "seq<int>") else ov
        cb.append("  { %s %s var ok := %s; print \"C%d=\", ok, \"\\n\"; }" % (decls, V.ret_bind(rvar, mo, rt0), pred, cid))
    out2 = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(cb) + "\n}\n")
    k = t = 0
    for m in re.finditer(r"C\d+=(true|false)", out2):
        t += 1; k += (m.group(1) == "false")
    return (k / t) if t else None


if __name__ == "__main__":
    import glob
    import nl_gated_compare as NG
    M = os.environ.get("SPEC_MODEL", "qwen2.5-coder:32b")
    tasks = os.environ.get("TASKS", "NpArange,NpArgmax,NpBitwiseXor,NpClip,NpSign,NpSquare,NpAbs,NpAdd,NpMaximum,NpCumsum").split(",")
    print("%-14s %7s %7s %7s  %s" % ("task", "c_pert", "c_mut", "rel", "verdict"))
    hit = miss = 0
    for tsk in tasks:
        fs = glob.glob(V.BENCH + "/numpy_simple/yaml/%s-spec.yaml" % tsk)
        if not fs:
            continue
        parts = V.load(fs[0]); head = V.sig_head(parts["vc-spec"])

        class C:
            def __init__(s): s.calls = 0
            def ask(s, m, p): s.calls += 1; return V.ask(m, p)
        cnt = C()
        gen = NG.gen_spec(M, parts, head, cnt)
        if not gen:
            print("%-14s (no spec)" % tsk); continue
        code = NG.code_for(M, parts, head + "\n    " + gen, cnt)
        if code is None:
            print("%-14s (no accept)" % tsk); continue
        ens = NG.ens_exprs(gen)
        c_pert = V.measure_completeness(parts, code, ens)
        c_mut = measure_completeness_mut(parts, code, ens)
        rel = NG.reliable_gt(parts, gen)
        v = ""
        if rel is False and c_mut is not None and c_mut < 0.8:
            v = "CAUGHT (mut)"; hit += 1
        elif rel is False:
            v = "missed"; miss += 1
        elif rel is True:
            v = "strong ok"
        def f(x): return round(x, 2) if x is not None else None
        print("%-14s %7s %7s %7s  %s" % (tsk, f(c_pert), f(c_mut), rel, v), flush=True)
    print("\nmut-gate caught weak:", hit, "| missed:", miss)
