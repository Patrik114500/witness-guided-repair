"""Witness-guided spec repair, first version: when the determinacy flag fires, do not feed back the
flag -- extract the WITNESS (a concrete input x and two distinct outputs r1!=r2 both satisfying the
generated postcondition), show it to the model TOGETHER WITH the NL description, and ask whether the
second output is intended. INTENDED -> benign non-determinism, do NOT repair (saves good specs).
UNINTENDED -> targeted strengthen: accept the correct output, reject the witness's wrong one; then
re-generate+re-verify code. Prototype on int-returning tasks (enumeration machinery exists)."""
import os, sys, re, glob, json, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import nl_gated_compare as NG
random.seed(11)

CANDS = list(range(-3, 16))


def concrete_inputs(params, tries=8):
    outs = []
    for _ in range(tries):
        decls = []; pyv = {}; ok = True
        for pn, pt in params:
            ptc = pt.replace(" ", "")
            if ptc == "array<int>":
                n = random.randint(2, 4); base = random.randint(-3, 3)
                vals = [base] * n
                for i in range(n):
                    if random.random() < 0.5:
                        vals[i] = base + random.choice([-2, -1, 1, 2])
                pyv[pn] = vals
                decls.append("var %s := new int[%d];" % (pn, n) + "".join(" %s[%d] := %d;" % (pn, i, v) for i, v in enumerate(vals)))
            elif ptc in ("int", "nat"):
                x = random.randint(0, 5); pyv[pn] = x
                decls.append("var %s := %d;" % (pn, x))
            else:
                ok = False
        if ok:
            outs.append((pyv, " ".join(decls)))
    return outs


def find_witness(parts, gen_ens, code=None):
    """concrete witness for non-determinacy of the GENERATED spec: (input, r1, r2) both admitted.
    int/nat returns: candidate enumeration. array<int> returns (needs the accepted code): the code's own
    output o plus perturbed variants o' as candidates -- an admitted o' != o is a witness."""
    sig = V.parse_sig(parts["vc-spec"])
    if not sig or not sig[2]:
        return None
    name, params, (rvar, rt) = sig
    rt0 = rt.replace(" ", "")
    if rt0 in ("array<int>", "seq<int>") and code is not None:
        return _find_witness_struct(parts, gen_ens, code, name, params, rvar, rt0)
    if rt0 == "bool":
        return _find_witness_scalar(parts, gen_ens, params, rvar, rt0, [True, False])
    if rt0 not in ("int", "nat"):
        return None
    ens = V.ensures_list("method _() returns ()\n  " + gen_ens)
    if not ens:
        return None
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    pred = "(" + " && ".join("(%s)" % e for e in ens) + ")"
    prec = "(" + " && ".join("(%s)" % r for r in reqs) + ")" if reqs else "true"
    best = None
    for pyv, decls in concrete_inputs(params):
        blocks = []
        for c in CANDS:
            blocks.append("  { %s if %s { var %s := %d; var ok := %s; print \"R%d=\", ok, \"\\n\"; } }"
                          % (decls, prec, rvar, c, pred, c))
        out = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(blocks) + "\n}\n")
        sat = sorted(set(int(m.group(1)) for m in re.finditer(r"R(-?\d+)=true", out)))
        if len(sat) >= 2:
            # most-informative witness: the input admitting the MOST outputs, farthest pair within it
            cand = {"input": pyv, "r1": sat[0], "r2": sat[-1], "nsat": len(sat)}
            if best is None or cand["nsat"] > best["nsat"]:
                best = cand
    return best


def extract_ensures(parts, txt):
    """robust ensures extraction: prefer code blocks, then per-line SYNTAX-VALIDATE each candidate
    (models mix prose mentioning `ensures` into answers); keep only lines Dafny accepts."""
    src = "\n".join(re.findall(r"```(?:dafny)?\s*(.*?)```", txt, re.S)) or txt
    cands = [re.sub(r";\s*$", "", l).rstrip() for l in re.findall(r"ensures[^\n]*", src)]
    cands = [c for c in cands if "`" not in c and len(c) > 10]
    if not cands:
        return None
    whole = "\n    ".join(cands)
    if spec_syntax_ok(parts, whole)[0]:
        return whole
    # cumulative prefix filtering: a line may need earlier lines for well-formedness (e.g. bounds before a[result])
    kept = []
    for c in cands:
        trial = "\n    ".join(kept + [c])
        if spec_syntax_ok(parts, trial)[0]:
            kept.append(c)
    return "\n    ".join(kept) if kept else None


def _pred_prec(parts, gen_ens):
    ens = V.ensures_list("method _() returns ()\n  " + gen_ens)
    if not ens or any("old(" in e for e in ens):
        return None, None
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    pred = "(" + " && ".join("(%s)" % e for e in ens) + ")"
    prec = "(" + " && ".join("(%s)" % r for r in reqs) + ")" if reqs else "true"
    return pred, prec


def _find_witness_scalar(parts, gen_ens, params, rvar, rt0, cands):
    """scalar-returning witness (bool etc.) via explicit candidate list bound with ret_bind."""
    pred, prec = _pred_prec(parts, gen_ens)
    if pred is None:
        return None
    for pyv, decls in concrete_inputs(params, tries=6):
        blocks = []
        for ci, c in enumerate(cands):
            blocks.append("  { %s if %s { %s var ok := %s; print \"W%d=\", ok, \"\\n\"; } }"
                          % (decls, prec, V.ret_bind(rvar, c, rt0), pred, ci))
        out = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(blocks) + "\n}\n")
        adm = sorted(set(int(m.group(1)) for m in re.finditer(r"W(\d+)=true", out)))
        if len(adm) >= 2:
            return {"input": pyv, "r1": cands[adm[0]], "r2": cands[adm[1]]}
    return None


def _run_struct(parts, code, params, inputs, name, rt0):
    """run the accepted code on inputs, parse array<int>/seq<int> outputs."""
    ln = "r.Length" if rt0 == "array<int>" else "|r|"
    pb = []
    for i, (pyv, decls) in enumerate(inputs):
        args = ", ".join(pn for pn, _ in params)
        pb.append('  { %s var r := %s(%s); print "I%d:["; var j:=0; while j<%s{print r[j]; if j<%s-1{print ",";} j:=j+1;} print "]\\n"; }'
                  % (decls, name, args, i, ln, ln))
    out = V.drun(V.assemble(parts, code) + "\nmethod Main() {\n" + "\n".join(pb) + "\n}\n")
    res = {}
    for i, _ in enumerate(inputs):
        m = re.search(r"I%d:\[([^\]]*)\]" % i, out)
        if m:
            res[i] = [int(x) for x in m.group(1).split(",") if x.strip().lstrip("-").isdigit()] if m.group(1).strip() else []
    return res


def _valid_inputs(parts, params, tries=14):
    """generate inputs and keep only those satisfying the task's preconditions (evaluated by execution)."""
    _p, prec = _pred_prec(parts, "ensures true")
    cands = concrete_inputs(params, tries=tries)
    if not cands:
        return []
    if prec == "true":
        return cands
    blocks = ["  { %s var ok := %s; print \"P%d=\", ok, \"\\n\"; }" % (decls, prec, i)
              for i, (pyv, decls) in enumerate(cands)]
    out = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(blocks) + "\n}\n")
    okset = set(int(m.group(1)) for m in re.finditer(r"P(\d+)=true", out))
    return [cands[i] for i in sorted(okset)]


def _find_witness_struct(parts, gen_ens, code, name, params, rvar, rt0):
    """array<int>/seq<int>-returning witness via output perturbation of the accepted code's own output."""
    pred, _prec = _pred_prec(parts, gen_ens)
    if pred is None:
        return None
    inputs = _valid_inputs(parts, params)
    if not inputs:
        return None
    outs = _run_struct(parts, code, params, inputs, name, rt0)
    outs = {i: o for i, o in outs.items() if o}  # need non-empty output to perturb
    for i, (pyv, decls) in enumerate(inputs):
        o = outs.get(i)
        if o is None or not isinstance(o, list):
            continue
        cands = [c for c in V.perturb(o, rt0) if c != o][:14]
        if not cands:
            continue
        blocks = []
        for ci, c in enumerate([o] + cands):
            blocks.append("  { %s %s var ok := %s; print \"W%d_%d=\", ok, \"\\n\"; }"
                          % (decls, V.ret_bind(rvar, list(c), rt0), pred, i, ci))
        out = V.drun(V.pre(parts) + "\nmethod Main() {\n" + "\n".join(blocks) + "\n}\n")
        adm = set(int(m.group(1)) for m in re.finditer(r"W%d_(\d+)=true" % i, out))
        if 0 in adm:
            for ci in sorted(adm):
                if ci > 0:
                    return {"input": pyv, "r1": o, "r2": ([o] + cands)[ci]}
    return None


def spec_syntax_ok(parts, gen_ens):
    """does the strengthened spec PARSE/resolve? verify sig+ensures with an assume-false body."""
    head = V.sig_head(parts["vc-spec"])
    m = V.pre(parts) + "\n" + head + "\n    " + gen_ens + "\n{\n  assume {:axiom} false;\n}\n"
    ok, err = V.dverify(m)
    return ok, err


def disambiguate(model, parts, gen_ens, wit, cnt):
    nl = parts.get("vc-description", "").strip()
    inp = ", ".join("%s = %s" % (k, v) for k, v in wit["input"].items())
    p = ("A method's postcondition was generated from this description:\n%s\n\n"
         "Generated postcondition:\n%s\n\n"
         "For the concrete input (%s), BOTH result = %s AND result = %s satisfy this postcondition.\n"
         "According to the description, is it INTENDED that more than one of these results is acceptable?\n"
         "Answer on the first line with exactly INTENDED or UNINTENDED.\n"
         "If UNINTENDED: state which of the two results is correct for this input, and then write the "
         "complete STRENGTHENED postcondition (only 'ensures ...' lines) that still accepts the correct "
         "result but rejects the wrong one. Use ONLY the method's parameters and the result variable with "
         "quantifiers, indexing and arithmetic; do NOT call any helper function.\n"
         % (nl[:1200], gen_ens, inp, wit["r1"], wit["r2"]))
    r = cnt.ask(model, p)
    first = r.strip().splitlines()[0].upper() if r.strip() else ""
    verdict = "INTENDED" if "UNINTENDED" not in first else "UNINTENDED"
    if "INTENDED" not in first and "UNINTENDED" not in first:
        verdict = "UNINTENDED" if "UNINTENDED" in r.upper() else ("INTENDED" if "INTENDED" in r.upper() else "UNCLEAR")
    g2 = extract_ensures(parts, r)
    # SYNTAX LOOP: if nothing valid extracted, feed the failure back (<=2 retries)
    if verdict == "UNINTENDED":
        for _ in range(2):
            if g2:
                break
            p2 = ("Your previous answer contained no syntactically valid Dafny 'ensures' lines. "
                  "Output ONLY ensures lines, one per line, valid Dafny. Quantifier syntax: "
                  "'ensures forall k :: 0 <= k < a.Length ==> ...'. No prose, no helper functions.\n")
            r2 = cnt.ask(model, p2)
            g2 = extract_ensures(parts, r2)
    return verdict, g2, r


class C:
    def __init__(s): s.calls = 0
    def ask(s, m, p): s.calls += 1; return V.ask(m, p)


def run_case(label, parts, gen_ens, model):
    cnt = C()
    rel0 = NG.reliable_gt(parts, gen_ens)
    wit = find_witness(parts, gen_ens)
    print("== %s ==" % label)
    print("   rel(before)=%s  witness=%s" % (rel0, wit))
    if not wit:
        print("   (no witness found -> determinate or not enumerable)"); return
    verdict, g2, raw = disambiguate(model, parts, gen_ens, wit, cnt)
    print("   verdict=%s" % verdict)
    if verdict == "INTENDED":
        print("   -> NO repair (benign non-det preserved). rel stays %s  [GOOD if rel=True]" % rel0)
    elif g2:
        head = V.sig_head(parts["vc-spec"])
        code2 = NG.code_for(model, parts, head + "\n    " + g2, cnt)
        rel2 = NG.reliable_gt(parts, g2)
        print("   -> repaired spec: %s" % g2.replace("\n", " ")[:120])
        print("   -> code re-verified=%s  rel(after)=%s  [GOOD if False->True]" % (code2 is not None, rel2))
    else:
        print("   -> UNINTENDED but no strengthened ensures returned")
    print("   llm_calls=%d" % cnt.calls)


def main():
    model = os.environ.get("MODEL", "qwen2.5-coder:32b")
    # case A (benign non-det): a task whose GROUND-TRUTH spec is confirmed genuinely non-deterministic;
    # candidate = the GT spec itself (entails itself -> rel=True). Expect INTENDED -> no repair, rel stays True.
    fa = glob.glob(V.BENCH + "/verina/yaml/verina_advanced_8_task.yaml")[0]
    pa = V.load(fa)
    gt_ens = "\n    ".join("ensures " + e for e in V.ensures_list(pa["vc-spec"]))
    run_case("verina_adv_8 GT-as-candidate, genuine non-det (expect INTENDED, no repair)", pa, gt_ens, model)
    # case B (true weakness): NpArgmax with a bounds-only spec. Expect UNINTENDED -> targeted repair.
    fb = glob.glob(V.BENCH + "/numpy_simple/yaml/NpArgmax-spec.yaml")[0]
    pb = V.load(fb)
    run_case("NpArgmax WEAK spec (expect UNINTENDED, targeted repair)", pb,
             "ensures 0 <= result < arr.Length", model)


if __name__ == "__main__":
    main()
