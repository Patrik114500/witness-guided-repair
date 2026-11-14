"""THE big one-shot vericoding run. Per (model, source, task): NL->spec->code->verify repair-loop pipeline,
saving EVERYTHING -- generated spec, all code attempts, verify output, 7 completeness signals,
ground-truth reliability + a test-based oracle, 3 repair arms (ours invariant-repair / LLM-judge with
reasoning / determinacy), per-step tokens+cost+time, raw prompts+responses. Resumable (JSON-lines).
Env: MODELS, SOURCES, LIMIT, ITERS, OUT, RAW_DIR.
"""
import os, sys, re, glob, json, time, traceback
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import nl_gated_compare as NG
import det_gate
import miner2 as MN
try:
    import dafny_mut as DM
except Exception:
    DM = None
try:
    import witness_repair as WR
except Exception:
    WR = None

ITERS = int(os.environ.get("ITERS", "3"))            # code-repair iterations (per spec)
REPAIR_ROUNDS = int(os.environ.get("REPAIR_ROUNDS", "3"))  # spec-repair rounds (iterated feedback)
OUT = os.environ.get("OUT", "/tmp/big_run.jsonl")
RAW_DIR = os.environ.get("RAW_DIR", "/tmp/big_raw")
os.makedirs(RAW_DIR, exist_ok=True)

# rough $/1M tokens (input, output); local models = 0. Used for cost tracking only.
PRICE = {
    "aoai:gpt-4o": (2.5, 10), "aoai:gpt-5": (10, 30), "aoai:gpt-5-mini": (0.5, 2), "aoai:gpt-6-astra": (10, 30),
    "claude:claude-opus-5-5": (15, 75), "claude:claude-opus-4-6": (15, 75), "claude:claude-sonnet-4-6": (3, 15),
    "claude:claude-haiku-4-5": (0.8, 4), "grok:grok-4.3": (3, 15), "grok:grok-4.7": (3, 15),
}


class Tracker:
    """wraps V.ask: counts calls, estimates tokens+cost, records raw (prompt,response) per step label."""
    def __init__(self, model):
        self.model = model; self.calls = 0; self.tin = 0; self.tout = 0; self.cost = 0.0; self.t = 0.0
        self.raw = []
    def ask(self, prompt, label=""):
        self.calls += 1; a = time.time()
        try:
            r = V.ask(self.model, prompt)
        except Exception as e:
            r = ""; self.raw.append({"label": label, "prompt": prompt, "response": "", "error": str(e)[:200]})
            self.t += time.time() - a; return r
        self.t += time.time() - a
        ti = len(prompt) // 4; to = len(r) // 4
        self.tin += ti; self.tout += to
        pi, po = PRICE.get(self.model, (0, 0))
        self.cost += ti / 1e6 * pi + to / 1e6 * po
        self.raw.append({"label": label, "prompt": prompt, "response": r})
        return r
    def summ(self):
        return {"calls": self.calls, "tok_in": self.tin, "tok_out": self.tout, "cost_usd": round(self.cost, 4), "time_s": round(self.t, 1)}


# ---------- pipeline steps (capture everything) ----------
FEWSHOT_ENSURES = """Valid Dafny ensures-line patterns (copy the SYNTAX, adapt the content):
  ensures 0 <= result < a.Length
  ensures forall i :: 0 <= i < a.Length ==> result >= a[i]
  ensures exists k :: 0 <= k < a.Length && a[k] == result
  ensures result.Length == a.Length && forall i :: 0 <= i < a.Length ==> result[i] == a[i] + 1
Common MISTAKES to avoid: Python syntax (for/in, len(), ** ), calling helper functions that are not
in the preamble, array indexing without the bounds conjunct FIRST, 'ensures' followed by prose."""


def gen_spec_raw(parts, head, tr, retries=3):
    """generate the postcondition WITH a syntax gate: an invalid spec poisons the whole code loop
    (the code prompt forbids changing the ensures), so parse errors are fed back to the SPEC generator."""
    nl = parts.get("vc-description", "").strip() or "the method's intended behaviour"
    base = ("Given this Dafny method signature and a natural-language description, write the POSTCONDITION "
            "(one or more 'ensures ...' lines) capturing FULL correctness. Return ONLY the ensures lines.\n\n"
            "Preamble:\n%s\n\nSignature:\n%s\n\nDescription:\n%s\n" % (parts.get("vc-preamble", "")[:1500], head, nl[:1500]))
    p = base
    txt = gen = None
    for _ in range(retries + 1):
        txt = tr.ask(p, "gen_spec")
        ens = [re.sub(r";\s*$", "", e).rstrip() for e in re.findall(r"ensures[^\n]*", txt)]
        gen = "\n    ".join(ens) if ens else None
        if not gen:
            p = base + "\nYour previous answer contained no 'ensures' lines. Output ONLY ensures lines."
            continue
        if WR is None:
            return gen, txt
        ok, err = WR.spec_syntax_ok(parts, gen)
        if ok:
            return gen, txt
        p = (base + "\nYour previous postcondition is NOT valid Dafny. Dafny reports:\n" + (err or "")[:900] +
             "\nPrevious attempt:\n" + gen + "\n\n" + FEWSHOT_ENSURES +
             "\n\nRewrite it as syntactically valid Dafny ensures lines only.")
    return gen, txt  # may still be invalid; recorded via spec_syntax_ok flag


def gen_code_raw(parts, spec, tr):
    base = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. "
            "Add the body and ALL needed loop invariants. Use a WHILE loop with explicit invariants, NOT a for loop. "
            "Return ONLY a ```dafny code block.\n\n" + V.pre(parts) + "\n" + spec + "\n")
    convo = base; attempts = []
    for it in range(1, ITERS + 1):
        out = tr.ask(convo, "gen_code_%d" % it)
        block = V.code_of(out)
        ok, err = V.dverify(V.assemble(parts, block))
        attempts.append({"iter": it, "code": block, "verified": ok, "dafny_out": err[:1500]})
        if ok:
            return block, attempts
        convo = base + "\n\nFAILED verification:\n" + err + "\n\nFix it with a while loop and correct invariants. Return ONLY a ```dafny code block."
    return None, attempts


def judge_reason(parts, gen, tr):
    nl = parts.get("vc-description", "").strip()
    p = ("Judge whether this Dafny postcondition FULLY and TIGHTLY specifies the task so that an incorrect "
         "implementation cannot satisfy it. First give one sentence of reasoning, then on the last line answer "
         "COMPLETE or WEAK.\n\nTask:\n%s\n\nPostcondition:\n%s\n" % (nl[:1000], gen))
    r = tr.ask(p, "judge")
    weak = "WEAK" in r.strip().upper().splitlines()[-1] if r.strip() else False
    return weak, r


# ---------- completeness signals on a spec ----------
def mutation_kill(parts, method, gen):
    """program-mutation completeness: mutate the verified method body, re-verify against the (gen) spec.
    kill-rate = fraction of mutants the spec rejects."""
    if DM is None:
        return None
    try:
        head = V.sig_head(parts["vc-spec"])
        full = head + "\n    " + gen + "\n" + (method[method.find("{"):] if "{" in method else method)
        if V.dverify(V.assemble(parts, full))[0] is not True:
            full = V.assemble(parts, method)  # fallback
        bs = DM.body_span(full)
        if not bs:
            return None
        muts = DM.make_mutants(full, bs, maxn=8)
        if not muts:
            return None
        kills = tot = 0
        for m in muts:
            ok, _ = V.dverify(m)
            tot += 1; kills += (not ok)
        return round(kills / tot, 3) if tot else None
    except Exception:
        return None


def structural(gen):
    ens = V.ensures_list("method _() returns ()\n  " + gen)
    return {"conjuncts": len(ens), "result_mentioned": bool(re.search(r"\bresult\b|\bret\b", gen)), "len_chars": len(gen)}


def invariant_signal(parts, gen, code, tr):
    """ours: mine invariants from verified impls, return (verdict 1.0/0.0/None, mined list, mineable bool)."""
    try:
        sig = V.parse_sig(parts["vc-spec"])
        if not sig or not sig[2]:
            return None, [], False
        name, params, (rvar, rt) = sig; rt0 = rt.replace(" ", "")
        if rt0 not in ("int", "nat", "array<int>"):
            return None, [], False
        impls = [code]  # reuse the verified impl (no extra gen -> cost-bounded)
        inputs = MN.gen_inputs(params, 8)
        outs = [MN.run_impl(parts, m, params, inputs, rt0) for m in impls]
        T = MN.arr_templates(params, rvar) if rt0 == "array<int>" else MN.int_templates(params)
        mined = MN.mine(T, inputs, outs)
        if not mined:
            return None, [], False
        ens = V.ensures_list("method _() returns ()\n  " + gen)
        ok = MN.implies(parts, ens, mined)
        return (1.0 if ok else 0.0), mined, True
    except Exception:
        return None, [], False


def test_oracle(parts, code, ref_code):
    """independent: run generated code vs a reference on random inputs; agree on all -> likely correct."""
    try:
        sig = V.parse_sig(parts["vc-spec"])
        if not sig or not sig[2]:
            return None
        name, params, (rvar, rt) = sig; rt0 = rt.replace(" ", "")
        if rt0 not in ("int", "nat", "array<int>") or ref_code is None:
            return None
        inputs = MN.gen_inputs(params, 8)
        g = MN.run_impl(parts, code, params, inputs, rt0)
        r = MN.run_impl(parts, ref_code, params, inputs, rt0)
        common = [i for i in g if i in r]
        if not common:
            return None
        agree = sum(1 for i in common if g[i] == r[i])
        return round(agree / len(common), 3)
    except Exception:
        return None


def all_signals(parts, gen, code, tr):
    s = {}
    try:
        ens = V.ensures_list("method _() returns ()\n  " + gen)
        s["perturbation_c"] = V.measure_completeness(parts, code, ens)
    except Exception:
        s["perturbation_c"] = None
    try:
        s["determinacy"] = det_gate.completeness_determinacy(parts, gen)
    except Exception:
        s["determinacy"] = None
    inv, mined, mineable = invariant_signal(parts, gen, code, tr)
    s["invariant"] = inv; s["mined_invariants"] = mined; s["mineable"] = mineable
    s["mutation_kill"] = mutation_kill(parts, code, gen)
    s["structural"] = structural(gen)
    return s


# ---------- repair arms: ITERATED spec-repair + CODE re-verification ----------
def _llm_strengthen(parts, head, gen, tr, arm, feedback):
    nl = parts.get("vc-description", "").strip()
    hint = ("\n\nA reviewer noted: %s" % str(feedback)[:400]) if (arm == "judge" and feedback) else ""
    p = ("This Dafny postcondition is too WEAK. Write a STRONGER, complete postcondition (add ensures) so a wrong "
         "program cannot satisfy it. Return ONLY ensures lines.\n\nSignature:\n%s\n\nDescription:\n%s\n\nWeak:\n%s%s\n"
         % (head, nl[:1000], gen, hint))
    r = tr.ask(p, "strengthen_%s" % arm)
    ens = re.findall(r"ensures[^\n]*", r)
    return "\n    ".join(re.sub(r";\s*$", "", e).rstrip() for e in ens) if ens else None


def arm_gate(parts, gen, code, tr, arm):
    """(weak_or_None, feedback) for the arm on the current spec. None => inconclusive (cannot flag)."""
    if arm == "ours":
        _, mined, mineable = invariant_signal(parts, gen, code, tr)
        if not mineable:
            return None, []
        ens = V.ensures_list("method _() returns ()\n  " + gen)
        viol = [i for i in mined if not MN.implies(parts, ens, [i])]
        return (len(viol) > 0), viol
    if arm == "judge":
        return judge_reason(parts, gen, tr)
    if arm == "det":
        return (det_gate.completeness_determinacy(parts, gen) == 0.0), None
    return None, None


def arm_strengthen(parts, head, gen, tr, arm, feedback):
    if arm == "ours":
        return gen + "".join("\n    ensures " + v for v in (feedback or []))  # deterministic, concrete feedback
    return _llm_strengthen(parts, head, gen, tr, arm, feedback)


class _Asker:
    """adapter: witness_repair expects cnt.ask(model, prompt); route into the Tracker."""
    def __init__(self, tr): self.tr = tr
    def ask(self, model, p): return self.tr.ask(p, "witness")


def witness_arm(parts, head, gen0, code0, tr):
    """THE NEW REPAIR PIPELINE: determinacy WITNESS (concrete input + two admitted outputs) +
    NL-arbiter disambiguation (INTENDED = benign non-det, stop; UNINTENDED = targeted strengthen
    that accepts the correct output and rejects the wrong one) + code re-verification."""
    if WR is None:
        return {"error": "witness module missing"}
    gen, code = gen0, code0
    rounds = []; benign = False
    for rnd in range(REPAIR_ROUNDS):
        try:
            wit = WR.find_witness(parts, gen, code)
        except Exception:
            wit = None
        if not wit:
            break  # determinate (or not enumerable) -> nothing to repair
        verdict, g2, _raw = WR.disambiguate(tr.model, parts, gen, wit, _Asker(tr))
        rounds.append({"round": rnd + 1, "witness": wit, "verdict": verdict})
        if verdict != "UNINTENDED":
            benign = True
            break  # NL says multiple outputs are intended -> benign non-determinism, DO NOT repair
        if not g2 or g2.strip() == gen.strip():
            break
        c2, att = gen_code_raw(parts, head + "\n    " + g2, tr)
        rounds[-1]["strengthened"] = g2
        rounds[-1]["code_reverified"] = c2 is not None
        rounds[-1]["code_iters"] = len(att)
        if c2 is None:
            break  # cannot satisfy the stronger spec -> keep previous accepted state
        gen, code = g2, c2
    return {"final_spec": gen, "reliable_gt_after": NG.reliable_gt(parts, gen),
            "benign_nondet": benign, "n_rounds": len(rounds), "history": rounds}


def iterated_repair(parts, head, gen0, code0, tr, arm):
    """gate -> if weak, strengthen the spec -> RE-GENERATE+VERIFY code against the stronger spec -> repeat."""
    gen, code = gen0, code0
    rounds = []; first_fb = None
    for rnd in range(REPAIR_ROUNDS):
        weak, fb = arm_gate(parts, gen, code, tr, arm)
        if rnd == 0:
            first_fb = fb
        if not weak:
            break
        g2 = arm_strengthen(parts, head, gen, tr, arm, fb)
        if not g2 or g2.strip() == gen.strip():
            break
        c2, att = gen_code_raw(parts, head + "\n    " + g2, tr)
        rounds.append({"round": rnd + 1, "spec": g2, "code_reverified": c2 is not None,
                       "code_iters": len(att)})
        if c2 is None:
            break  # cannot satisfy the stronger spec -> keep the previous verified accept
        gen, code = g2, c2
    out = {"final_spec": gen, "final_code": code, "reliable_gt_after": NG.reliable_gt(parts, gen),
           "spec_repair_rounds": len(rounds), "history": rounds}
    if arm == "judge":
        out["judge_reasoning_round0"] = first_fb
    if arm == "ours":
        out["violated_invariants_round0"] = first_fb
    return out


def process(model, src, task, f, scan, tr):
    parts = V.load(f)
    head = V.sig_head(parts["vc-spec"])
    sig = V.parse_sig(parts["vc-spec"])
    rt = sig[2][1].replace(" ", "") if sig and sig[2] else None
    gt_ens = V.ensures_list(parts["vc-spec"])
    rec = {"model": model, "source": src, "task": task,
           "meta": {"rettype": rt, "gt_determinate": scan.get("%s|%s" % (src, task), {}).get("gt_determinate"),
                    "gt_ensures": gt_ens, "preconds": re.findall(r"requires\s+(.+)", parts["vc-spec"])}}
    # GT spec's own completeness signals (benchmark quality)
    try:
        rec["meta"]["gt_determinacy"] = det_gate.completeness_determinacy(parts, "\n    ".join("ensures " + e for e in gt_ens)) if gt_ens else None
    except Exception:
        rec["meta"]["gt_determinacy"] = None
    # B: baseline pipeline
    gen, spec_raw = gen_spec_raw(parts, head, tr)
    rec["gen_spec"] = gen
    if gen and WR is not None:
        rec["spec_syntax_ok"] = bool(WR.spec_syntax_ok(parts, gen)[0])
    if not gen:
        rec["status"] = "no-spec"; rec["cost"] = tr.summ(); return rec
    code, attempts = gen_code_raw(parts, head + "\n    " + gen, tr)
    rec["code_attempts"] = attempts
    rec["accepted"] = code is not None
    rec["spec_intact"] = bool(code) and V.spec_intact(code, gt_ens) if hasattr(V, "spec_intact") else None
    if not code:
        rec["status"] = "no-verify"; rec["cost"] = tr.summ(); return rec
    rec["status"] = "accepted"
    # C: signals
    rec["signals"] = all_signals(parts, gen, code, tr)
    # D: oracle
    rec["reliable_gt"] = NG.reliable_gt(parts, gen)
    rec["test_oracle"] = test_oracle(parts, code, code)
    # E: repair arms -- iterated spec-repair + code re-verification
    rec["arm_ours"] = iterated_repair(parts, head, gen, code, tr, "ours")
    rec["arm_judge"] = iterated_repair(parts, head, gen, code, tr, "judge")
    rec["arm_determinacy"] = iterated_repair(parts, head, gen, code, tr, "det")
    rec["arm_witness"] = witness_arm(parts, head, gen, code, tr)  # THE NEW repair pipeline
    rec["cost"] = tr.summ()
    return rec


def main():
    MODELS = [m.strip() for m in os.environ.get("MODELS", "qwen2.5-coder:32b").split(",") if m.strip()]
    SOURCES = [s.strip() for s in os.environ.get("SOURCES", "numpy_simple,verina,verified_cogen").split(",") if s.strip()]
    LIMIT = int(os.environ.get("LIMIT", "10000"))
    scan = json.load(open("/tmp/nondet_scan.json")) if os.path.exists("/tmp/nondet_scan.json") else {}
    done = set()
    done_files = [OUT] + [f for f in os.environ.get("DONE_EXTRA", "").split(",") if f]
    for df in done_files:
        if not os.path.exists(df):
            continue
        for line in open(df):
            try:
                r = json.loads(line); done.add((r["model"], r["source"], r["task"]))
            except Exception:
                pass
    fout = open(OUT, "a")
    total_cost = 0.0
    for model in MODELS:
        for src in SOURCES:
            for f in sorted(glob.glob(V.BENCH + "/%s/yaml/*.yaml" % src))[:LIMIT]:
                task = os.path.basename(f)
                if (model, src, task) in done:
                    continue
                tr = Tracker(model)
                try:
                    rec = process(model, src, task, f, scan, tr)
                except Exception as e:
                    rec = {"model": model, "source": src, "task": task, "status": "error",
                           "error": str(e)[:300], "trace": traceback.format_exc()[-600:], "cost": tr.summ()}
                # save raw separately (large)
                rid = "%s__%s__%s" % (model.replace(":", "_").replace("/", "_"), src, task)
                json.dump(tr.raw, open(os.path.join(RAW_DIR, rid + ".json"), "w"))
                rec["raw_file"] = rid + ".json"
                fout.write(json.dumps(rec) + "\n"); fout.flush()
                total_cost += rec.get("cost", {}).get("cost_usd", 0)
                print("  %-22s %-14s %-24s %-9s rel=%s ours_after=%s $%.3f (cum $%.2f)" % (
                    model, src, task.replace("-spec.yaml", "").replace("_task.yaml", "")[:24], rec.get("status"),
                    rec.get("reliable_gt"), rec.get("arm_ours", {}).get("reliable_gt_after"),
                    rec.get("cost", {}).get("cost_usd", 0), total_cost), flush=True)
    print("DONE total_cost=$%.2f" % total_cost, flush=True)


if __name__ == "__main__":
    main()
