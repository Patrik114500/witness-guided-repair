"""Aktiv reliability-gated NL->spec->code pipeline, 3 karral, osszevetve koltseg/sebesseg/megbizhatosag mentén.
  B0  baseline      : NL->spec->code, elfogad a verified-nel.
  B1  OURS (gate)   : verified utan kulcs nelkuli completeness (dafny-exec, 0 extra LLM); ha gyenge -> megerosit + ujragenerál.
  B2  LLM-judge     : verified utan egy LLM megitéli a specet; ha gyenge -> megerosit + ujragenerál.
Kiertekeles (FUGGETLEN, nem korkoros): a vegso elfogadott spec VALODI completeness-e a benchmark REFERENCIA
  implementaciojaval (vc-code) mint oracle. reliable := c_gt >= THR.
Metrikak karonkent: accepted, reliable, llm_calls, wall_time.
Env: MODELS, SOURCES, LIMIT, ITERS, THR, OUT.
"""
import os, sys, re, json, glob, time
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
sys.path.insert(0, os.path.expanduser("~/verina-lab/pylibs"))
import vericode_compete as V
try:
    from mut_gate import measure_completeness_mut
except Exception:
    measure_completeness_mut = None
try:
    from det_gate import completeness_determinacy
except Exception:
    completeness_determinacy = None
try:
    import miner2 as MN
except Exception:
    MN = None

ITERS = int(os.environ.get("ITERS", "4"))
THR = float(os.environ.get("THR", "0.8"))
GATE_ROUNDS = int(os.environ.get("GATE_ROUNDS", "2"))  # max strengthen rounds


def ens_exprs(spec):
    return V.ensures_list(spec)  # multi-line / conjunct-aware extraction


def reliable_gt(parts, gen_spec):
    """GROUND TRUTH (formal, deterministic): does OUR generated spec IMPLY the benchmark's intended spec?
    If yes, any code verifying our spec also satisfies the intent -> the accept is trustworthy.
    Returns True/False, or None if not checkable."""
    sig = V.parse_sig(parts["vc-spec"])
    if not sig:
        return None
    # multi-return guard: parse_sig keeps only the first return value, so the lemma would reference
    # undefined identifiers and spuriously fail -> UNSCORABLE (None), not weak (False)
    m = re.search(r"returns\s*\(([^)]*)\)", parts["vc-spec"])
    if m and m.group(1).count(":") > 1:
        return None
    name, params, ret = sig
    args = list(params) + ([ret] if ret else [])
    our = ens_exprs(gen_spec)
    orig = ens_exprs(parts["vc-spec"])
    if not our or not orig:
        return None
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    lem = V.pre(parts) + "\nlemma GTcheck(%s)\n" % ", ".join("%s: %s" % (n, t) for n, t in args)
    for r in reqs:
        lem += "  requires %s\n" % r
    for e in our:
        lem += "  requires %s\n" % e
    for e in orig:
        lem += "  ensures %s\n" % e
    lem += "{}\n"
    try:
        ok, _ = V.dverify(lem)
        return ok
    except Exception:
        return None


class Counter:
    def __init__(self): self.calls = 0; self.t = 0.0
    def ask(self, model, prompt):
        self.calls += 1; a = time.time()
        try:
            return V.ask(model, prompt)
        finally:
            self.t += time.time() - a


def gen_spec(model, parts, head, cnt):
    nl = parts["vc-description"].strip() or "the method's intended behaviour"
    p = ("Given this Dafny method signature and a natural-language description, write the POSTCONDITION "
         "(one or more 'ensures ...' lines) capturing FULL correctness. Return ONLY the ensures lines.\n\n"
         "Preamble:\n%s\n\nSignature:\n%s\n\nDescription:\n%s\n" % (parts["vc-preamble"][:1200], head, nl[:1200]))
    try:
        ens = re.findall(r"ensures[^\n]*", cnt.ask(model, p))
        return "\n    ".join(ens) if ens else None
    except Exception:
        return None


def strengthen(model, parts, head, prev, cnt):
    nl = parts["vc-description"].strip()
    p = ("This Dafny postcondition is too WEAK — a wrong implementation can still satisfy it. Write a STRONGER, "
         "complete postcondition (add ensures clauses) that a wrong program cannot satisfy. Return ONLY ensures lines.\n\n"
         "Signature:\n%s\n\nDescription:\n%s\n\nWeak postcondition:\n%s\n" % (head, nl[:1000], prev))
    try:
        ens = re.findall(r"ensures[^\n]*", cnt.ask(model, p))
        return "\n    ".join(ens) if ens else None
    except Exception:
        return None


def judge_weak(model, parts, gen_spec, cnt):
    nl = parts["vc-description"].strip()
    p = ("Judge whether this Dafny postcondition FULLY and TIGHTLY specifies the task (so that a wrong "
         "implementation cannot satisfy it). Answer with ONLY one word: COMPLETE or WEAK.\n\n"
         "Task:\n%s\n\nPostcondition:\n%s\n" % (nl[:1000], gen_spec))
    try:
        return "WEAK" in cnt.ask(model, p).strip().upper()
    except Exception:
        return False


def code_for(model, parts, spec, cnt):
    """repair loop: generate code against spec, verify. returns (verified_method or None)."""
    base = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. "
            "Add the body and ALL needed loop invariants. Use a WHILE loop with explicit invariants. "
            "Return ONLY a ```dafny code block.\n\n" + V.pre(parts) + "\n" + spec + "\n")
    convo = base
    for _ in range(ITERS):
        try:
            block = V.code_of(cnt.ask(model, convo))
        except Exception:
            return None
        ok, err = V.dverify(V.assemble(parts, block))
        if ok:
            return block
        convo = base + "\n\nFAILED:\n" + err + "\n\nFix it with a while loop and correct invariants. Return ONLY a ```dafny code block."
    return None



def head_of(parts):
    return V.sig_head(parts["vc-spec"])


def _inv_gate(parts, gen, code, model, cnt):
    """Non-det-aware invariant-anchored completeness: mine invariants from verified impls, check the spec
    implies them. 1.0 = adequate (accept, incl. benign non-determinism), 0.0 = admits a violating output
    (weak), None = no invariants mined (inconclusive)."""
    try:
        sig = V.parse_sig(parts["vc-spec"])
        if not sig or not sig[2]:
            return None
        name, params, (rvar, rt) = sig
        rt0 = rt.replace(" ", "")
        if rt0 not in ("int", "nat", "array<int>"):
            return None
        impls = [code]
        for _ in range(2):
            b = code_for(model, parts, head_of(parts) + "\n    " + gen, cnt)
            if b:
                impls.append(b)
        inputs = MN.gen_inputs(params, 8)
        outs = [MN.run_impl(parts, m, params, inputs, rt0) for m in impls]
        T = MN.arr_templates(params, rvar) if rt0 == "array<int>" else MN.int_templates(params)
        mined = MN.mine(T, inputs, outs)
        if not mined:
            return None
        ens = V.ensures_list("method _() returns ()\n  " + gen)
        return 1.0 if MN.implies(parts, ens, mined) else 0.0
    except Exception:
        return None


def gated_run(model, parts, head, how, cnt):
    """how in {'our','judge'}: verified -> measure/judge -> if weak strengthen & re-run. returns final gen_spec or None."""
    spec0 = gen_spec(model, parts, head, cnt)
    if not spec0:
        return None, None
    spec = head + "\n    " + spec0
    code = code_for(model, parts, spec, cnt)
    if code is None:
        return None, None
    gen = spec0
    for _ in range(GATE_ROUNDS):
        if how == "our":
            if os.environ.get("GATE_KIND") == "inv" and MN is not None:
                c = _inv_gate(parts, gen, code, model, cnt)
            elif os.environ.get("GATE_KIND") == "det" and completeness_determinacy is not None:
                c = completeness_determinacy(parts, gen)
            elif os.environ.get("GATE_KIND") == "mut" and measure_completeness_mut is not None:
                c = measure_completeness_mut(parts, code, ens_exprs(gen))
            else:
                c = V.measure_completeness(parts, code, ens_exprs(gen))
            weak = (c is not None and c < THR)
        else:  # judge
            weak = judge_weak(model, parts, gen, cnt)
        if not weak:
            break
        ng = strengthen(model, parts, head, gen, cnt)
        if not ng:
            break
        nspec = head + "\n    " + ng
        ncode = code_for(model, parts, nspec, cnt)
        if ncode is None:
            break  # could not satisfy stronger spec -> keep previous accept
        gen, code = ng, ncode
    if os.environ.get("REJECT_WEAK") == "1":
        if how == "our":
            if os.environ.get("GATE_KIND") == "det" and completeness_determinacy is not None:
                cf = completeness_determinacy(parts, gen)
            elif os.environ.get("GATE_KIND") == "mut" and measure_completeness_mut is not None:
                cf = measure_completeness_mut(parts, code, ens_exprs(gen))
            else:
                cf = V.measure_completeness(parts, code, ens_exprs(gen))
            if cf is not None and cf < THR:
                return None, None
        elif how == "judge" and judge_weak(model, parts, gen, cnt):
            return None, None
    return gen, code


def main():
    MODELS = [m.strip() for m in os.environ.get("MODELS", "gpt-oss:20b,qwen2.5:7b").split(",") if m.strip()]
    SOURCES = [s.strip() for s in os.environ.get("SOURCES", "numpy_simple").split(",") if s.strip()]
    LIMIT = int(os.environ.get("LIMIT", "10"))
    OUT = os.environ.get("OUT", "/tmp/nl_gated.json")
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for source in SOURCES:
        _filt = os.environ.get("TASK_FILTER", "")
        files = [f for f in sorted(glob.glob(V.BENCH + "/%s/yaml/*.yaml" % source)) if _filt in os.path.basename(f)][:LIMIT]
        for model in MODELS:
            for f in files:
                task = os.path.basename(f)
                key = "%s|%s|%s" % (model, source, task)
                if key in res:
                    continue
                try:
                    parts = V.load(f)
                    head = V.sig_head(parts["vc-spec"])
                    rec = {"model": model, "source": source, "task": task, "arms": {}}
                    # B0 baseline
                    c0 = Counter(); s0 = gen_spec(model, parts, head, c0)
                    code0 = code_for(model, parts, head + "\n    " + s0, c0) if s0 else None
                    acc0 = code0 is not None
                    r0 = reliable_gt(parts, s0) if acc0 else None
                    rec["arms"]["B0"] = {"accepted": acc0, "reliable": r0, "llm_calls": c0.calls, "time": round(c0.t, 1)}
                    # B1 ours
                    c1 = Counter(); g1, cd1 = gated_run(model, parts, head, "our", c1)
                    r1 = reliable_gt(parts, g1) if g1 else None
                    rec["arms"]["B1_ours"] = {"accepted": g1 is not None, "reliable": r1, "llm_calls": c1.calls, "time": round(c1.t, 1)}
                    # B2 judge
                    c2 = Counter(); g2, cd2 = gated_run(model, parts, head, "judge", c2)
                    r2 = reliable_gt(parts, g2) if g2 else None
                    rec["arms"]["B2_judge"] = {"accepted": g2 is not None, "reliable": r2, "llm_calls": c2.calls, "time": round(c2.t, 1)}
                except Exception as e:
                    rec = {"model": model, "source": source, "task": task, "error": str(e)[:100]}
                res[key] = rec
                json.dump(res, open(OUT, "w"), indent=1)
                a = rec.get("arms", {})
                def fmt(x): return "acc=%s rel=%s calls=%s" % (x.get("accepted"), x.get("reliable"), x.get("llm_calls"))
                print("  %-14s %-18s | B0 %s | B1 %s | B2 %s" % (
                    model, task, fmt(a.get("B0", {})), fmt(a.get("B1_ours", {})), fmt(a.get("B2_judge", {}))), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
