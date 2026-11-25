"""Harness fixes (2026-11-18), kept in a separate module so the original pipeline files stay untouched.

Three artifacts found in the first results, each fixed here:
  1. duplicate members: the model repeats a preamble helper in its code block and assemble() adds the
     preamble again -> "Duplicate member name". dedupe_block() drops the model's copy, the benchmark's
     definition stays authoritative.
  2. empty responses: reasoning models exhaust max_completion_tokens (content == "") or the request times
     out, and the code loop aborted the task. ask_robust() raises the budget and retries.
  3. forced while loop: the code prompt demanded a while loop even for loop-free tasks. gen_code_fixed()
     has the original wording (variant="orig", for rescuing big-run tasks) and a loop-neutral one ("v2").
Also: dverify2() kills the whole process group on timeout (no orphaned z3) and does not read "10 errors"
as "0 errors"; reliable_gt_mr() scores multi-return signatures instead of returning None.
"""
import os, sys, re, json, time, signal, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V

_KW = (r"(?:function(?:\s+method)?|predicate(?:\s+method)?|lemma|method|datatype|codatatype|"
       r"type|newtype|const|class|trait|module)")
_MOD = r"(?:(?:ghost|opaque|static|twostate|least|greatest|abstract)\s+)*"
_ATTR = r"(?:\s*\{:[^}]*\})*"
DECL_ANY = re.compile(r"^[ \t]*" + _MOD + r"(" + _KW + r")\b" + _ATTR + r"\s+(\w+)", re.M)
DECL_TOP = re.compile(r"^" + _MOD + r"(" + _KW + r")\b" + _ATTR + r"\s+(\w+)", re.M)


def declared_names(text):
    return set(m.group(2) for m in DECL_ANY.finditer(text or ""))


def dedupe_block(parts, block):
    """drop top-level declarations of the model's block whose name the benchmark preamble/postamble
    already declares (the benchmark's own definition is kept)."""
    pre_names = declared_names(V.pre(parts)) | declared_names(parts.get("vc-postamble", ""))
    sig = V.parse_sig(parts.get("vc-spec", "") or "")
    target = sig[0] if sig else None
    pre_names.discard(target)
    if not pre_names:
        return block
    ms = list(DECL_TOP.finditer(block))
    if not ms:
        return block
    out = [block[:ms[0].start()]]
    dropped = 0
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(block)
        if m.group(2) in pre_names:
            dropped += 1
            continue
        out.append(block[m.start():end])
    return "".join(out) if dropped else block


def dverify2(src, timeout=90):
    with tempfile.NamedTemporaryFile("w", suffix=".dfy", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        pr = subprocess.Popen([V.DAFNY, "verify", p], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, start_new_session=True)
        try:
            o, _ = pr.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pr.pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                pr.communicate(timeout=10)
            except Exception:
                pass
            return False, "TIMEOUT"
        # STRICT (2026-11-18 evening): Dafny reports a method whose proof ran into its own time limit as
        # "N verified, 0 errors, 1 time out". That is NOT a verified program. Before this fix the summary line
        # was read as success ("0 errors"), so time-outs counted as accepts and as proved lemmas.
        unfinished = bool(re.search(r"[1-9]\d* (?:time ?outs?|out of resource|inconclusive)", o)) or "timed out" in o
        ok = bool(re.search(r"(?<!\d)0 errors", o)) and bool(re.search(r"[1-9]\d* verified", o)) and not unfinished
        if unfinished and not ok:
            return False, "TIMEOUT"
        return ok, o[-1500:]
    finally:
        try:
            os.unlink(p)
        except Exception:
            pass


BIG_TOKENS = {"aoai:gpt-5": 32000, "aoai:gpt-5-mini": 32000}
# $ per 1M tokens (input, output), list prices; reasoning tokens are billed as output
PRICE_REAL = {"aoai:gpt-5": (1.25, 10), "aoai:gpt-5-mini": (0.25, 2), "aoai:gpt-4o": (2.5, 10), "aoai:gpt-6-astra": (10, 30),
              "claude:claude-opus-5-5": (15, 75), "claude:claude-opus-4-6": (15, 75), "claude:claude-sonnet-4-6": (3, 15),
              "claude:claude-haiku-4-5": (0.8, 4), "grok:grok-4.3": (3, 15)}


def ask_once(model, prompt, timeout=900):
    if model.startswith("aoai:"):
        b = json.dumps({"messages": [{"role": "user", "content": prompt}],
                        "max_completion_tokens": BIG_TOKENS.get(model, 10000)})
        out = V._post("%s/openai/deployments/%s/chat/completions?api-version=2024-10-21" % (V.AZ_EP, model[5:]),
                      {"api-key": V.AZ_KEY, "Content-Type": "application/json"}, b, timeout=timeout)
        d = json.loads(out)
        return (d["choices"][0]["message"]["content"] or ""), (d.get("usage") or {})
    if model.startswith("claude:"):
        b = json.dumps({"model": model[7:], "max_tokens": 10000, "messages": [{"role": "user", "content": prompt}]})
        out = V._post("%s/anthropic/v1/messages" % V.AZ_EP,
                      {"x-api-key": V.AZ_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                      b, timeout=timeout)
        d = json.loads(out); u = d.get("usage") or {}
        return "".join(x.get("text", "") for x in d["content"]), {"prompt_tokens": u.get("input_tokens", 0),
                                                                   "completion_tokens": u.get("output_tokens", 0)}
    if ":" not in model or model.split(":", 1)[0] not in ("grok", "gemini"):
        # local Ollama model: same payload as V.ask_ollama, but a longer limit than its 300 s
        import urllib.request
        data = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}).encode()
        req = urllib.request.Request(V.OLLAMA, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        return (d["choices"][0]["message"]["content"] or ""), (d.get("usage") or {})
    return (V.ask(model, prompt) or ""), {}


class Asker:
    """robust ask: an empty / failed response is retried and is NOT a verification attempt."""
    def __init__(self, model, tries=3):
        self.model = model; self.tries = tries
        self.calls = 0; self.empties = 0; self.tin = 0; self.tout = 0; self.t = 0.0; self.errors = []
        self.real_in = 0; self.real_out = 0
    def ask(self, prompt):
        for t in range(self.tries):
            a = time.time(); self.calls += 1
            try:
                r, u = ask_once(self.model, prompt)
                self.real_in += int(u.get("prompt_tokens") or 0); self.real_out += int(u.get("completion_tokens") or 0)
            except Exception as e:
                r = ""; self.errors.append(str(e)[:100])
            self.t += time.time() - a
            if r and r.strip():
                self.tin += len(prompt) // 4; self.tout += len(r) // 4
                return r
            self.empties += 1
            time.sleep(25 + 20 * t if (self.errors and "429" in self.errors[-1]) else 2 + 4 * t)
        return ""
    def summ(self):
        pi, po = PRICE_REAL.get(self.model, (0, 0))
        return {"calls": self.calls, "empties": self.empties, "tok_in": self.real_in or self.tin,
                "tok_out": self.real_out or self.tout, "time_s": round(self.t, 1), "errors": self.errors[:3],
                "cost_usd": round((self.real_in or self.tin) / 1e6 * pi + (self.real_out or self.tout) / 1e6 * po, 4)}


def nows(s):
    return re.sub(r"\s+", "", s or "")


def ensures_present(block, ens_exprs):
    b = nows(block)
    return all(nows(e) in b for e in ens_exprs)


PROMPTS = {
    "orig": ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. "
             "Add the body and ALL needed loop invariants. Use a WHILE loop with explicit invariants, NOT a for loop. "
             "Return ONLY a ```dafny code block.\n\n",
             "\n\nFAILED verification:\n%s\n\nFix it with a while loop and correct invariants. Return ONLY a ```dafny code block."),
    "v2": ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. "
           "Add the body. If the body needs a loop, write a WHILE loop with explicit invariants (not a for loop); "
           "if it needs no loop, do not add one. Do not repeat declarations that are already given above the method. "
           "Return ONLY a ```dafny code block.\n\n",
           "\n\nFAILED verification:\n%s\n\nFix it; if there is a loop, correct its invariants. Keep the ensures EXACTLY. "
           "Return ONLY a ```dafny code block."),
}
KEEP_SPEC = ("\n\nYour answer changed or dropped an ensures clause. Keep ALL the given ensures lines EXACTLY as written, "
             "character for character. Return ONLY a ```dafny code block.")


def gen_code_fixed(parts, spec, asker, iters=5, variant="orig", enforce_ens=None, guard=False):
    """the code loop of big_run.gen_code_raw with the artifacts fixed. enforce_ens: list of ensures
    expressions that must appear verbatim in the accepted block (None = original behaviour, no check).
    guard=True: a block that verifies only through a bypass (assume, {:axiom}, ...) is rejected with
    feedback, by the published pipeline's own rules (fix_cheat)."""
    import fix_cheat as FC
    base_txt, fix_txt = PROMPTS[variant]
    base = base_txt + V.pre(parts) + "\n" + spec + "\n"
    convo = base; attempts = []; it = 0; api_fail = 0
    while it < iters:
        out = asker.ask(convo)
        if not out.strip():
            # an API failure is not a verification attempt: it does not consume an iteration
            api_fail += 1
            if api_fail >= 3:
                attempts.append({"iter": it + 1, "code": "", "verified": False, "dafny_out": "API-FAILURE"})
                return None, attempts
            continue
        it += 1
        block = dedupe_block(parts, V.code_of(out))
        if "method" not in block:
            attempts.append({"iter": it, "code": block, "verified": False, "dafny_out": "NO-METHOD"})
            convo = base + fix_txt % "the answer did not contain the method"
            continue
        ok, err = dverify2(V.assemble(parts, block))
        intact = True if enforce_ens is None else ensures_present(block, enforce_ens)
        bypass = FC.cheats(block, "dafny") if guard else []
        attempts.append({"iter": it, "code": block, "verified": ok, "intact": intact, "bypass": bypass, "dafny_out": err[:1500]})
        if ok and intact and not bypass:
            return block, attempts
        if ok and bypass:
            convo = base + "\n\n" + FC.message(bypass) + " Return ONLY a ```dafny code block."
        else:
            convo = base + (KEEP_SPEC if ok else fix_txt % err)
    return None, attempts


def method_ensures(code, name):
    """the ensures expressions the method `name` actually states in `code` (body cut off)."""
    m = re.search(r"method\s+(?:\{:[^}]*\}\s*)*%s\b" % re.escape(name), code or "")
    if not m:
        return None
    lines = code[m.start():].split("\n"); hdr = []
    for i, ln in enumerate(lines):
        if i > 0 and ln.strip().startswith("{"):
            break
        hdr.append(ln)
    h = "\n".join(hdr)
    if len(hdr) == len(lines):            # no line starts with "{": brace sits at the end of a header line
        k = max(h.rfind("ensures"), h.rfind("requires"), 0)
        b = h.find("{", h.find("\n", k) if h.find("\n", k) > 0 else k)
        if b > 0:
            h = h[:b]
    return [re.sub(r"\{\s*$", "", e).strip() for e in V.ensures_list(h)]


def _split_top(s):
    out = []; depth = 0; cur = ""
    for ch in s:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [(x.split(":", 1)[0].strip(), x.split(":", 1)[1].strip()) for x in out if ":" in x]


def reliable_gt_mr(parts, gen_spec, extra_pre=""):
    """entailment S => G for single- AND multi-return signatures. True / False / None (not checkable)."""
    m = re.search(r"method\s+(\w+)\s*\(([^)]*)\)\s*returns\s*\(([^)]*)\)", parts["vc-spec"])
    if not m:
        return None
    args = _split_top(m.group(2)) + _split_top(m.group(3))
    our = V.ensures_list(gen_spec if "ensures" in gen_spec else "ensures " + gen_spec)
    orig = V.ensures_list(parts["vc-spec"])
    if not our or not orig:
        return None
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    lem = (extra_pre + "\n" if extra_pre else "") + V.pre(parts) + "\nlemma GTcheck(%s)\n" % ", ".join("%s: %s" % a for a in args)
    for r in reqs:
        lem += "  requires %s\n" % r
    for e in our:
        lem += "  requires %s\n" % e
    for e in orig:
        lem += "  ensures %s\n" % e
    lem += "{}\n"
    ok, out = dverify2(lem)
    if not ok and ("resolution/type errors" in out or "parse errors" in out):
        return None                       # the lemma itself is ill-formed -> not checkable, not "weak"
    return ok


def load_bigrun(models=None):
    """deduped big-run records, same rule as paper_numbers.py (first record per key, apps excluded)."""
    import glob
    recs = []; seen = set()
    for f in sorted(glob.glob("/tmp/big_run_*.jsonl")):
        if "apps" in f:
            continue
        for l in open(f):
            try:
                r = json.loads(l)
            except Exception:
                continue
            k = (r.get("model"), r.get("source"), r.get("task"))
            if k in seen:
                continue
            seen.add(k)
            if models is None or r.get("model") in models:
                recs.append(r)
    return recs


P11 = ["claude:claude-opus-5-5", "aoai:gpt-6-astra", "claude:claude-sonnet-4-6", "grok:grok-4.3", "qwen2.5-coder:32b",
       "claude:claude-opus-4-6", "aoai:gpt-5", "aoai:gpt-5-mini", "gpt-oss:20b", "claude:claude-haiku-4-5", "aoai:gpt-4o"]


def task_parts(src, task):
    return V.load(os.path.join(V.BENCH, src, "yaml", task))
