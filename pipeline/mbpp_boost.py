"""MBPP-DFY acceptance-BOOST arm: our pipeline with the search frame widened to match
dafny-synthesis' K=5 resampling, while the trust layer moves INSIDE the search:
  - up to KSPEC=5 candidate postconditions onto the curated signature (few-shot examples
    taken from the public 50-example DB, leave-one-out; k=1 at temp 0.3, rest at 0.8);
  - every candidate is syntax-gated (witness_repair.spec_syntax_ok) and ranked KEY-FREE by
    the determinacy signal: determinate specs tried first, weak-flagged last;
  - per candidate (max TRY_CAND) our usual verifier-feedback code loop (ITERS<=5), with a
    looser prompt (helpers/predicates/lemmas allowed, any loop style), ensures-integrity
    enforced (the accepted code must carry the candidate ensures verbatim);
  - post-accept measurement identical to mbpp_ours: entailment vs curated spec (reliable_gt),
    determinacy of the winning spec, the dataset's own tests.
Env: MODEL, OUT, LIMIT, ONLY_FAILED (path to an mbpp_ours jsonl: only its non-accepted
tasks are run), KSPEC, TRY_CAND, ITERS. Resumable by task."""
import os, sys, re, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import nl_gated_compare as NG
import det_gate
import witness_repair as WR
import big_run as BR

D = os.path.expanduser("~/clover/dataset/MBPP-DFY-153")
DS = os.path.expanduser("~/dafny-synthesis")
MODEL = os.environ.get("MODEL", "claude:claude-haiku-4-5")
OUT = os.environ.get("OUT", "/tmp/mbpp_boost.jsonl")
LIMIT = int(os.environ.get("LIMIT", "0"))
KSPEC = int(os.environ.get("KSPEC", "5"))
TRY_CAND = int(os.environ.get("TRY_CAND", "5"))
ITERS = int(os.environ.get("ITERS", "5"))
ONLY_FAILED = os.environ.get("ONLY_FAILED", "")
PRICE = {"claude:claude-haiku-4-5": (0.8, 4)}

db = json.load(open(glob.glob(D + "/*.json")[0]))
exdb = json.load(open(DS + "/Scripts/data/mbpp-dfy-50-examples-db.json"))


def ask_t(prompt, temp):
    if MODEL.startswith("claude:"):
        b = json.dumps({"model": MODEL[7:], "max_tokens": 10000, "temperature": temp,
                        "messages": [{"role": "user", "content": prompt}]})
        out = V._post("%s/anthropic/v1/messages" % V.AZ_EP,
                      {"x-api-key": V.AZ_KEY, "anthropic-version": "2023-06-01",
                       "Content-Type": "application/json"}, b)
        return "".join(x.get("text", "") for x in json.loads(out)["content"])
    return V.ask(MODEL, prompt, temp=temp)


class Cost:
    def __init__(self):
        self.calls = 0; self.tin = 0; self.tout = 0
    def ask(self, prompt, temp):
        r = ask_t(prompt, temp)
        self.calls += 1; self.tin += len(prompt) // 4; self.tout += len(r) // 4
        return r
    def summ(self):
        pi, po = PRICE.get(MODEL, (0, 0))
        return {"calls": self.calls, "tok_in": self.tin, "tok_out": self.tout,
                "cost_usd": round(self.tin / 1e6 * pi + self.tout / 1e6 * po, 4)}


# ---------- few-shot examples: description -> Dafny ensures, from their public 50-DB ----------
def ex_ensures(code):
    """ensures of the example method, ONLY if self-contained: an example whose ensures
    calls the example's own helper predicates teaches a style that cannot parse in our
    bare context (this killed 10 tasks in the v1 run)."""
    m = re.search(r"(method\s+\w+\s*\([^)]*\)\s*returns\s*\([^)]*\))", code)
    if not m:
        return None
    bpos = code.find("{", m.end())
    ens = V.ensures_list(code[:bpos] if bpos > 0 else code)
    if not ens:
        return None
    helpers = set(re.findall(r"(?:function|predicate)\s+(\w+)", code))
    joined = " ".join(ens)
    if any(re.search(r"\b%s\s*\(" % re.escape(h), joined) for h in helpers):
        return None
    return "\n".join("ensures " + e for e in ens)


FEWSHOT = {}
for i in exdb:
    e = ex_ensures(exdb[i]["code"])
    if e:
        FEWSHOT[i] = (exdb[i]["task_description"],
                      exdb[i]["specification"]["method_signature"], e)


def fewshot_block(exclude):
    ids = [i for i in FEWSHOT if i != exclude][:3]
    out = []
    for i in ids:
        d, s, e = FEWSHOT[i]
        out.append("Task:\n%s\nSignature:\n%s\nPostcondition:\n%s" % (d, s, e))
    return "\n\n".join(out)


# ---------- gt loading (same as mbpp_ours) ----------
def gt_parts(tid):
    f = D + "/src/task_id_%s.dfy" % tid
    if not os.path.exists(f):
        return None
    strong = open(f).read()
    m = re.search(r"(method\s+\w+\s*\([^)]*\)\s*returns\s*\([^)]*\)(?:\s*requires[^\n]*)*)", strong)
    if not m:
        return None
    head = m.group(1).rstrip()
    last_kw = max(strong.rfind("ensures"), strong.rfind("requires"))
    bpos = strong.find("{", last_kw) if last_kw >= 0 else -1
    spec_part = strong[:bpos] if bpos > 0 else strong
    gt_ens = V.ensures_list(spec_part)
    if not gt_ens:
        return None
    parts = {"vc-preamble": "", "vc-helpers": "", "vc-code": "", "vc-postamble": "",
             "vc-description": "", "vc-spec": head + "\n  " + "\n  ".join("ensures " + e for e in gt_ens)}
    return head, parts


def test_oracle(parts, code, tests):
    try:
        body = "\n".join("  { %s }" % t.replace("assert ", "expect ").replace("\n", " ")
                         for t in list(tests.values())[:3])
        src = V.assemble(parts, code) + "\nmethod Main() {\n" + body + "\n}\n"
        out = V.drun(src)
        if "expectation violation" in out:
            return False
        if "Error" in out:
            return None
        return True
    except Exception:
        return None


# ---------- stages ----------
def gen_spec_cands(parts, head, tid, cost):
    nl = parts["vc-description"].strip()
    base = ("Given a Dafny method signature and a natural-language description, write the "
            "POSTCONDITION (one or more 'ensures ...' lines) capturing FULL correctness: it must "
            "pin down the output uniquely wherever the description does. Use ONLY the signature's "
            "parameters and result variable with plain Dafny expressions and quantifiers; do NOT "
            "call helper functions or predicates. Return ONLY the ensures "
            "lines.\n\nExamples:\n%s\n\nTask:\n%s\nSignature:\n%s\nPostcondition:\n"
            % (fewshot_block(tid if tid in exdb else None), nl[:1500], head))
    cands, seen = [], set()
    for k in range(1, KSPEC + 1):
        txt = cost.ask(base, 0.3 if k == 1 else 0.8)
        ens = [re.sub(r";\s*$", "", e).rstrip() for e in re.findall(r"ensures[^\n]*", txt)]
        gen = "\n    ".join(ens) if ens else None
        if not gen or gen in seen:
            continue
        seen.add(gen)
        ok, err = WR.spec_syntax_ok(parts, gen)
        if not ok:  # one corrective round with the verifier's syntax error (v1 lacked this)
            fix = cost.ask(base + "\nYour previous postcondition is NOT valid Dafny here. "
                           "Dafny reports:\n" + (err or "")[:800] + "\nPrevious attempt:\n" + gen +
                           "\nRewrite it as self-contained, syntactically valid ensures lines only.",
                           0.3)
            ens = [re.sub(r";\s*$", "", e).rstrip() for e in re.findall(r"ensures[^\n]*", fix)]
            gen2 = "\n    ".join(ens) if ens else None
            if gen2 and gen2 not in seen:
                gen = gen2
                seen.add(gen)
                ok, err = WR.spec_syntax_ok(parts, gen)
        det = None
        if ok:
            try:
                det = det_gate.completeness_determinacy(parts, gen)
            except Exception:
                det = None
        cands.append({"k": k, "spec": gen, "syntax_ok": bool(ok), "det": det})
    rank = {1.0: 0, None: 1, 0.0: 2}
    return sorted([c for c in cands if c["syntax_ok"]], key=lambda c: rank[c["det"]]), cands


def ens_norm(s):
    return [re.sub(r"\s+", "", x) for x in re.findall(r"ensures[^\n]*", s)]


def code_loop(parts, head, spec, cost):
    base = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures "
            "EXACTLY as given. You may add helper functions, predicates and lemmas before the "
            "method, and any loop style with the invariants and asserts the verifier needs. "
            "Return ONLY a ```dafny code block.\n\n" + head + "\n    " + spec + "\n")
    p = base
    attempts = []
    for it in range(1, ITERS + 1):
        out_txt = cost.ask(p, 0.3)
        block = V.code_of(out_txt)
        ok, err = V.dverify(V.assemble(parts, block))
        integ = set(ens_norm(spec)) <= set(ens_norm(block))
        attempts.append({"iter": it, "verified": bool(ok), "ensures_kept": integ,
                         "dafny_out": err[:600], "code": block})
        if ok and integ:
            return block, attempts
        fb = ""
        if not integ:
            fb += "You changed or dropped the given ensures lines; keep them EXACTLY.\n"
        if not ok:
            fb += "Verification failed:\n" + err[:2000] + "\n"
        p = base + "\nPrevious attempt:\n```dafny\n" + block[:3500] + "\n```\n" + fb + \
            "Fix it. Return ONLY a ```dafny code block."
    return None, attempts


# ---------- task list ----------
only = None
if ONLY_FAILED:
    only = set()
    for l in open(ONLY_FAILED):
        try:
            r = json.loads(l)
            if r.get("status") != "accepted":
                only.add(r["task"])
        except Exception:
            pass
    print("ONLY_FAILED: %d tasks from %s" % (len(only), ONLY_FAILED), flush=True)

done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            done.add(json.loads(l)["task"])
        except Exception:
            pass
fout = open(OUT, "a")

n = 0
for tid in sorted(db, key=int):
    if LIMIT and n >= LIMIT:
        break
    name = "task_id_" + tid
    if name in done or (only is not None and name not in only):
        continue
    gp = gt_parts(tid)
    if not gp:
        continue
    head, parts = gp
    parts["vc-description"] = db[tid].get("task_description", "")
    cost = Cost()
    rec = {"task": name, "model": MODEL, "method": "boost", "kspec": KSPEC,
           "try_cand": TRY_CAND, "iters": ITERS}
    try:
        ranked, allc = gen_spec_cands(parts, head, tid, cost)
        rec["n_cands"] = len(allc)
        rec["cand_summary"] = [{"k": c["k"], "syntax_ok": c["syntax_ok"], "det": c["det"]}
                               for c in allc]
        accepted = None
        for ci, c in enumerate(ranked[:TRY_CAND]):
            code, attempts = code_loop(parts, head, c["spec"], cost)
            rec.setdefault("code_attempts", []).append(
                {"cand_k": c["k"], "det": c["det"], "n_iters": len(attempts),
                 "verified": code is not None})
            if code is not None:
                accepted = (c, code, attempts)
                break
        if accepted is None:
            # FALLBACK: one plain base-style spec (no few-shot, no uniqueness push) so the
            # boost search space is a superset of the base pipeline's; a weak fallback
            # accept is then flagged by the determinacy signal, not hidden.
            class _T:  # Tracker shim onto our Cost
                def ask(self, prompt, label=""):
                    return cost.ask(prompt, 0.3)
            fspec, _ = BR.gen_spec_raw(parts, head, _T())
            if fspec and fspec not in [c["spec"] for c in ranked]:
                try:
                    fdet = det_gate.completeness_determinacy(parts, fspec)
                except Exception:
                    fdet = None
                code, attempts = code_loop(parts, head, fspec, cost)
                rec.setdefault("code_attempts", []).append(
                    {"cand_k": 0, "fallback": True, "det": fdet,
                     "n_iters": len(attempts), "verified": code is not None})
                if code is not None:
                    accepted = ({"k": 0, "spec": fspec, "det": fdet, "fallback": True},
                                code, attempts)
        rec["accepted"] = accepted is not None
        if accepted is None:
            rec["status"] = "no-verify"
        else:
            c, code, attempts = accepted
            rec["status"] = "accepted"
            rec["gen_spec"] = c["spec"]
            rec["spec_det"] = c["det"]
            rec["code"] = code
            rec["reliable_gt"] = NG.reliable_gt(parts, c["spec"])
            rec["tests_pass"] = test_oracle(parts, code, db[tid].get("test_cases", {}))
        rec["cost"] = cost.summ()
    except Exception as e:
        rec["status"] = "error"
        rec["error"] = str(e)[:200]
    fout.write(json.dumps(rec) + "\n")
    fout.flush()
    done.add(name)
    n += 1
    print("  %-14s %-9s cands=%s rel=%s det=%s tests=%s $%.3f" % (
        name, rec.get("status"), rec.get("n_cands"), rec.get("reliable_gt"),
        rec.get("spec_det"), rec.get("tests_pass"),
        rec.get("cost", {}).get("cost_usd", 0)), flush=True)
print("DONE %d" % n, flush=True)
