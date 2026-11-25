"""Writes the prompt files of this folder from the code in ../pipeline, so that their text is the text the code sends.

    python prompts/make_prompts.py            rewrites the prompt files (every *.md here except README.md)
    python prompts/make_prompts.py --check    changes nothing; exit code 1 if a file differs from what the code gives

A prompt is read from the syntax tree of its script. String constants are copied as they are. Every other part
of the expression (a field of the task, an output of the verifier, an earlier answer of the model) becomes a slot
written {{like this}}, and a part that is only sent under a condition stands between {{if ...}} and {{end if}}.
An expression for which this file names no slot stops the run, so no part of a prompt is dropped silently.
Standard library only."""
import ast, os, re, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "..", "pipeline")


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


class Raw(str):
    """a slot value that is prompt text itself (already rendered), inserted without the slot braces"""


class Script:
    """One script of ../pipeline, with selectors that find a prompt expression in its syntax tree."""

    def __init__(self, name):
        self.name = name
        with open(os.path.join(PIPE, name), encoding="utf-8") as f:
            self.text = f.read()
        self.tree = ast.parse(self.text)
        self.names = {}
        for st in self.tree.body:                       # NL = chr(10) is how several scripts write a line break
            if isinstance(st, ast.Assign) and self.seg(st.value) == "chr(10)":
                self.names[st.targets[0].id] = "\n"

    def seg(self, node):
        return norm(ast.get_source_segment(self.text, node))

    def _nodes(self, func):
        if func is None:
            return list(self.tree.body)
        for n in ast.walk(self.tree):
            if isinstance(n, ast.FunctionDef) and n.name == func:
                inner = [x for x in ast.walk(n) if hasattr(x, "lineno")]
                return sorted(inner, key=lambda x: (x.lineno, x.col_offset))
        raise KeyError("%s has no function %s" % (self.name, func))

    def _pick(self, found, k, what):
        if k >= len(found):
            raise KeyError("%s: %s, occurrence %d not found" % (self.name, what, k))
        return found[k]

    def assign(self, func, target, k=0):
        """the value of the k-th assignment to `target` in `func` (None: at module level), in source order"""
        found = [n.value for n in self._nodes(func) if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == target]
        return self._pick(found, k, "assignment to %s in %s" % (target, func))

    def aug(self, func, target, k=0):
        """the value of the k-th `target += ...` in `func`"""
        found = [n.value for n in self._nodes(func) if isinstance(n, ast.AugAssign)
                 and isinstance(n.target, ast.Name) and n.target.id == target]
        return self._pick(found, k, "augmented assignment to %s in %s" % (target, func))

    def arg(self, func, callee, k=0):
        """the first argument of the k-th call of `callee` in `func`"""
        found = [n.args[0] for n in self._nodes(func) if isinstance(n, ast.Call) and self.seg(n.func) == callee]
        return self._pick(found, k, "call of %s in %s" % (callee, func))

    def ret(self, func, k=0):
        found = [n.value for n in self._nodes(func) if isinstance(n, ast.Return)]
        return self._pick(found, k, "return in %s" % func)

    def item(self, const, key, index):
        """element `index` of the tuple stored under `key` in the module-level dict `const`"""
        d = self.assign(None, const)
        for kn, vn in zip(d.keys, d.values):
            if kn.value == key:
                return vn.elts[index]
        raise KeyError("%s: %s has no key %s" % (self.name, const, key))

    def render(self, node, slots=None, names=None):
        slots = slots or {}
        names = dict(self.names, **(names or {}))

        def r(n):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                assert "{{" not in n.value and "}}" not in n.value and "~~~" not in n.value, n.value
                return n.value
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                return r(n.left) + r(n.right)
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod):
                fmt = r(n.left)
                if isinstance(n.right, ast.Tuple):
                    return fmt % tuple(r(e) for e in n.right.elts)
                if isinstance(n.right, ast.Dict):
                    return fmt % {k.value: r(v) for k, v in zip(n.right.keys, n.right.values)}
                return fmt % (r(n.right),)
            if isinstance(n, ast.IfExp):
                cond = slots["if " + self.seg(n.test)]
                out = "{{if %s}}" % cond + r(n.body)
                if not (isinstance(n.orelse, ast.Constant) and n.orelse.value == ""):
                    out += "{{otherwise}}" + r(n.orelse)
                return out + "{{end if}}"
            if isinstance(n, ast.Name) and n.id in names:
                return names[n.id]
            s = self.seg(n)
            if s not in slots:
                raise KeyError("%s: no slot named for the expression `%s`" % (self.name, s))
            return slots[s] if isinstance(slots[s], Raw) else "{{%s}}" % slots[s]

        return r(node)


# ------------------------------------------------------------------------------------------------------ layout
def para(text):
    return textwrap.fill(norm(text), 112, break_long_words=False, break_on_hyphens=False) + "\n"


def fence(text):
    """the prompt is what stands between the two fence lines, without the line break in front of the closing fence"""
    return "~~~text\n" + text + "\n~~~\n"


def block(title, when, text):
    return "## %s\n\n%s\n%s" % (title, para(when), fence(text))


def doc(title, *parts):
    return "# %s\n\n%s" % (title, "\n".join(parts))


FIRST = "{{the first prompt}}"
DESC = "task description, at most 1500 characters"
BYPASS_SLOT = {'", ".join(found)': "the bypasses that were found, for example: uses 'assume'"}


def bypass_message():
    fc = Script("fix_cheat.py")
    return fc.render(fc.ret("message"), BYPASS_SLOT)


# ------------------------------------------------------------------------------------------------------- step 1
def step1_specification():
    s = Script("big_run.py")
    base = s.render(s.assign("gen_spec_raw", "base"), {
        'parts.get("vc-preamble", "")[:1500]': "preamble of the task, at most 1500 characters",
        "head": "signature and requires lines of the method",
        "nl[:1500]": DESC})
    none = s.render(s.assign("gen_spec_raw", "p", 1), names={"base": FIRST})
    invalid = s.render(s.assign("gen_spec_raw", "p", 2), {
        '(err or "")[:900]': "the last 1200 characters of the output of Dafny, cut after the first 900",
        "gen": "the postcondition of the previous answer"},
        {"base": FIRST, "FEWSHOT_ENSURES": s.render(s.assign(None, "FEWSHOT_ENSURES"))})
    return doc(
        "Step 1: the postcondition from the description",
        para("""Source: `pipeline/big_run.py`, function `gen_spec_raw`. Used in experiment 1 for every model and task
             (K = 1, also where stage E runs a task again from the start), by our pipeline on CloverBench
             (`clover_v2.py`, `MODE=ours`), and as the last candidate on MBPP-DFY when none of the K = 5 candidates
             of `mbpp_dfy.md` leads to an accept. The model sees the description, the preamble and the signature
             with the precondition, never the reference postcondition."""),
        para("""From every `ensures` in the answer to the end of its line is taken as one clause of S, with a closing
             semicolon removed. The postcondition is then checked for well-formedness by verifying the signature
             with it and a body that assumes false (`witness_repair.spec_syntax_ok`). A task without a description
             gets the words "the method's intended behaviour" in the place of the description. There are at most
             four calls (`retries=3`). The postcondition of the last answer is kept even if Dafny still rejects
             it, and a task whose last answer has no ensures line gets no specification."""),
        block("First call", "Sent once per task.", base),
        block("When the answer has no ensures line", "Sent in place of the first prompt.", none),
        block("When Dafny rejects the postcondition", "Sent in place of the first prompt.", invalid))


# ------------------------------------------------------------------------------------------------------- step 2
def step2_code():
    b = Script("big_run.py")
    slots = {"V.pre(parts)": "preamble and helper declarations of the task",
             "spec": "signature, requires lines and the ensures lines of S"}
    raw_base = b.render(b.assign("gen_code_raw", "base"), slots)
    raw_fix = b.render(b.assign("gen_code_raw", "convo", 1),
                       {"err": "the end of the output of Dafny, at most 1200 characters"}, {"base": FIRST})
    h = Script("fix_harness.py")
    parts = [
        para("""The model writes the body and the proof annotations for a fixed signature, precondition and
             postcondition, and gets the output of the verifier back when the program does not verify. Each call
             is a single message: the feedback prompt contains the first prompt again and the output of the
             verifier for the latest attempt. It contains neither the failed program nor the earlier attempts.
             When Dafny does not finish within 90 seconds, the word TIMEOUT stands in the place of its output, in
             the corrected loop also when Dafny reports that a proof ran into its time limit. The loop exists in
             two forms."""),
        "## The loop of the first pass (`pipeline/big_run.py`, function `gen_code_raw`)\n",
        para("""Used in the first pass of experiment 1, and whenever a repair of experiment 2 that comes from
             `big_run.iterated_repair` (LLM judge, determinacy flag, mined invariants) needs a body for a changed
             postcondition. The reported runs allowed five attempts (`ITERS=5`). The answer is the content of the
             first code block."""),
        block("First pass, first call", "Sent once per specification.", raw_base),
        block("First pass, after a failed verification", "Sent in place of the first prompt.", raw_fix),
        "## The corrected loop (`pipeline/fix_harness.py`, function `gen_code_fixed`)\n",
        para("""Written after the first pass of experiment 1 (see the stages A to E in `pipeline/README.md`). It
             removes declarations that the answer repeats from the preamble, retries an empty response without
             counting it as an attempt, uses the strict verifier call, and can reject an answer that verifies
             only through a bypass (`guard=True`) or that does not carry the given ensures lines
             (`enforce_ens`). It has two wordings. The wording `orig` is the one of the first pass and is used
             where tasks of experiment 1 are run again: stage B (`fix_rescue_b.py`, five attempts), stage D
             (`fix_bypass.py`, four attempts, bypasses rejected) and stage E (`fix_rerun_e.py`, function
             `code_loop_locked`, five attempts, bypasses rejected). The wording `v2` does not ask for a loop where
             none is needed. It is used by our pipeline on CloverBench (`clover_v2.py`, five attempts) and for
             the body under S ∧ C in step 3 (`wit2.py`, function `recode`, five attempts, bypasses rejected)."""),
    ]
    for variant in ("orig", "v2"):
        base = h.render(h.assign("gen_code_fixed", "base"), slots, {"base_txt": h.render(h.item("PROMPTS", variant, 0))})
        fix = FIRST + h.render(h.item("PROMPTS", variant, 1)) % "{{the end of the output of Dafny, at most 1500 characters}}"
        parts += [block("Wording `%s`, first call" % variant, "Sent once per specification.", base),
                  block("Wording `%s`, after a failed verification" % variant,
                        """Sent in place of the first prompt. When the answer holds no method, the words "the answer
                        did not contain the method" stand in the place of the output of Dafny.""", fix)]
    keep = FIRST + h.render(h.assign(None, "KEEP_SPEC"))
    byp = h.render(h.assign("gen_code_fixed", "convo", 2), {"FC.message(bypass)": Raw(bypass_message())}, {"base": FIRST})
    parts += [
        block("Both wordings, when the program verifies but an ensures line was changed",
              "Sent in place of the first prompt where the loop enforces the given ensures lines.", keep),
        block("Both wordings, when the program verifies only through a bypass",
              """Sent in place of the first prompt where the loop rejects bypasses. The rules are in
              `pipeline/fix_cheat.py` (assume, `{:axiom}`, `{:verify false}`, `{:extern}`), and step 3 also
              rejects `decreases *` and `expect`.""", byp)]
    return doc("Step 2: the body, with the output of the verifier as feedback", *parts)


# ------------------------------------------------------------------------------------------------------- step 3
def step3_witness_repair():
    w = Script("wit2.py")
    common = {
        '(parts.get("vc-description", "") or "").strip()[:1500]': DESC,
        "if pre": "the task has declarations above the method",
        "pre[:3000]": "these declarations, at most 3000 characters",
        "O.head(parts)": "signature and requires lines of the method",
        "S": "the ensures lines of the current postcondition S",
        "if names": "the task declares functions",
        '", ".join(names[:12])': "names of at most 12 of these functions"}

    def const(name):
        return {name: w.render(w.assign(None, name))}

    wit = w.render(w.assign("find_witness2", "prompt"), dict(common, **{
        '", ".join("%s: %s" % p for p in params) or "(none)"': "the parameters with their types, or (none)",
        '", ".join("%s: %s" % r for r in rets)': "the return variables with their types"}), const("WIT_PROMPT"))
    wit_fb = FIRST + w.render(w.assign("find_witness2", "fb", 1), {
        "why": "the reason the checker gives", "r.strip()[:700]": "the previous answer, at most 700 characters"})
    arb = w.render(w.assign("arbiter", "base"), dict(common, **{
        'wit["input"] or "(no parameters)"': "the input of the witness as Dafny statements, or (no parameters)",
        'wit["o1"]': "the first output of the witness as Dafny statements",
        'wit["o2"]': "the second output of the witness as Dafny statements"}), const("ARB_PROMPT"))
    again = {"why": "the reason of the rejection", "r.strip()[:1200]": "the previous answer, at most 1200 characters"}
    arb_fb = w.render(w.arg("arbiter", "asker.ask", 1), again, {"base": FIRST})
    flag = w.render(w.assign("flag_strengthen", "base"), common, const("FLAG_PROMPT"))
    flag_fb = w.render(w.arg("flag_strengthen", "asker.ask", 1), again, {"base": FIRST})
    force = w.render(w.assign("force_det", "base"), common, const("FORCE_PROMPT"))
    force_fb = w.render(w.arg("force_det", "asker.ask", 1), again, {"base": FIRST})
    recode = w.render(w.assign("recode", "spec"), {
        "head": "signature and requires lines of the method",
        "S2": "the ensures lines of S followed by the added clauses C",
        '(prev_code or "").strip()': "the accepted program for S"})
    return doc(
        "Step 3: witness-guided repair",
        para("""Source: `pipeline/wit2.py`. Used in experiment 2 on every accept whose postcondition S the
             determinacy query flags: on the accepts of experiment 1 by `wit2.py` itself, and on the accepts of
             the two pipelines of experiment 3 by `e2e_repair.py`. The model proposes, and a check decides each
             time: a witness counts only if execution or a proof confirms it, a clause C has to be well-formed in
             the method, and S ∧ C replaces S only if a body verifies under it. The model is never asked to
             rewrite the existing lines of S. The defaults of the script, which it calls the standard budget,
             are three rounds per accept (`ROUNDS`), two answers per witness search (`WIT_TRIES`), two answers
             per clause (`CLAUSE_TRIES`) and five attempts for the body (`ITERS`)."""),
        "## 1. The witness\n",
        para("""Function `find_witness2`. The model is asked for an input and two different outputs that S both
             admits. `check_witness` then confirms that the input satisfies the precondition, that both outputs
             satisfy S and that they differ, by running the compiled predicates or, where they do not compile, by
             a proof of the same facts. When no answer of the model is confirmed, an enumeration over small
             integers, booleans and integer arrays is tried without a model call (`witness_repair.find_witness`,
             for methods with one return value)."""),
        block("Witness search, first call", "Sent once per round.", wit),
        block("Witness search, after a rejected answer",
              """Sent in place of the first prompt. The reason is the one the checker returns, for example that the
              answer was not in the format, that an output does not satisfy the postcondition, or that the two
              outputs are the same value.""", wit_fb),
        "## 2. The clause for a confirmed witness\n",
        para("""Function `arbiter`. The model first says whether the description leaves the choice between the two
             outputs open. If it answers INTENDED, the specification is left as it is. If it answers UNINTENDED,
             it names the correct output and writes additional ensures lines C. The lines that keep S ∧ C
             well-formed are then evaluated on the witness (`check_clause`): they have to accept the output that
             the model called correct and reject the other one, or both if it called neither correct. A clause
             that fails goes back to the model once with the reason. A clause for which the evaluation gives no
             result is passed on to the last test, a body that verifies under S ∧ C."""),
        block("Arbiter, first call", "Sent once per confirmed witness.", arb),
        block("Arbiter, after a rejected clause", "Sent in place of the first prompt.", arb_fb),
        "## 3. The paths without a witness\n",
        para("""Function `flag_strengthen` runs when no witness could be confirmed and only the flag of the
             determinacy query stands. Function `force_det` runs for the accepts whose postcondition the model
             called complete although the solver could not prove that it determines the output. There the
             solver decides: the added lines are kept only if the determinacy query is proved with them. Both
             follow the same rule of adding."""),
        block("Flag only, first call", "Sent when no witness was confirmed.", flag),
        block("Flag only, after a rejected answer", "Sent in place of the first prompt.", flag_fb),
        block("Solver decides, first call", "Sent in the pass over the accepts that the model called complete.", force),
        block("Solver decides, after a rejected answer", "Sent in place of the first prompt.", force_fb),
        "## 4. The body under S ∧ C\n",
        para("""Function `recode`. The accepted body is first verified again under S ∧ C without a model call. Only
             when that fails is the model asked, through the code loop of step 2 in the wording `v2` (see
             `step2_code.md`), where the text below stands in the place of the specification. If no body
             verifies, the accept keeps S and its old body."""),
        block("Specification part of the code prompt", "Placed in the code prompt of step 2.", recode))


# -------------------------------------------------------------------------------------------- compared repairs
def compared_repairs():
    s = Script("big_run.py")
    judge = s.render(s.assign("judge_reason", "p"), {
        "nl[:1000]": "task description, at most 1000 characters", "gen": "the ensures lines of S"})
    hint = s.render(s.assign("_llm_strengthen", "hint"), {
        'if arm == "judge" and feedback': "the repair is the LLM judge",
        "str(feedback)[:400]": "the answer of the judge, at most 400 characters"})
    strengthen = s.render(s.assign("_llm_strengthen", "p"), {
        "head": "signature and requires lines of the method",
        "nl[:1000]": "task description, at most 1000 characters",
        "gen": "the ensures lines of S"}, {"hint": hint})
    return doc(
        "The repairs that step 3 is compared with (experiment 2)",
        para("""Source: `pipeline/big_run.py`, functions `judge_reason`, `_llm_strengthen` and `iterated_repair`.
             The LLM judge and the determinacy flag run as they were designed: when the postcondition is
             flagged, the model writes a stronger postcondition that takes the place of S, and a body is
             generated for it with the code loop of the first pass (`step2_code.md`). This repeats for up to
             five rounds (`REPAIR_ROUNDS=5`) while the new postcondition is flagged again and a body verifies.
             The third repair, mined invariants, makes no model call for the specification. For a method that
             returns an integer or an integer array, `miner2.py` runs the accepted program on generated inputs,
             and the invariants that hold on the outputs but do not follow from S are appended as ensures
             lines."""),
        block("LLM judge: is the postcondition complete?",
              """Sent once per round. The postcondition counts as flagged when the last line of the answer contains
              WEAK.""", judge),
        block("The stronger postcondition (LLM judge and determinacy flag)",
              """Sent when the postcondition is flagged, by the judge or by the determinacy query of `det_gate.py`,
              which is a lemma and has no prompt. The ensures lines of the answer replace S.""", strengthen),
        para("""The rule "add" of Fig. 3 for these proposers is a post-hoc analysis and has no prompt of its own:
             `conj_arms.py` takes the stored stronger postconditions and accepts them by adding instead of
             replacing."""))


# ----------------------------------------------------------------------------------------------------- MBPP-DFY
def mbpp_dfy():
    m = Script("mbpp_boost.py")
    base = m.render(m.assign("gen_spec_cands", "base"), {
        "fewshot_block(tid if tid in exdb else None)": "three examples in the form shown below, separated by empty lines",
        "nl[:1500]": DESC, "head": "signature and requires lines of the reference method"})
    example = m.render(m.arg("fewshot_block", "out.append"), {
        "d": "description of the example task", "s": "its method signature", "e": "its ensures lines"})
    fix = m.render(m.arg("gen_spec_cands", "cost.ask", 1), {
        '(err or "")[:800]': "the last 1200 characters of the output of Dafny, cut after the first 800",
        "gen": "the postcondition of the previous answer"}, {"base": FIRST})
    code = m.render(m.assign("code_loop", "base"), {
        "head": "signature and requires lines of the reference method", "spec": "the ensures lines of the candidate"})
    fb = ("{{if an ensures line was changed}}" + m.render(m.aug("code_loop", "fb", 0)) + "{{end if}}" +
          "{{if the program does not verify}}" + m.render(m.aug("code_loop", "fb", 1), {
              "err[:2000]": "the end of the output of Dafny, at most 1200 characters"}) + "{{end if}}")
    again = m.render(m.assign("code_loop", "p", 1), {
        "block[:3500]": "the program of the previous answer, at most 3500 characters"}, {"base": FIRST, "fb": fb})
    return doc(
        "Our pipeline on MBPP-DFY: five candidate postconditions (experiment 3)",
        para("""Source: `pipeline/mbpp_boost.py`. dafny-synthesis draws up to five fresh attempts per task with
             dynamic few-shot prompting, so on this benchmark our step 1 also draws K = 5 candidate
             postconditions and uses few-shot examples. The examples come from the public 50-example file of
             dafny-synthesis: the first three entries whose postcondition calls no helper function of its own
             example, leaving out the task itself. The model sees the description and the signature of the
             reference method, never its postcondition."""),
        para("""Identical candidates are dropped, a candidate that Dafny rejects gets one corrective call, and the
             well-formed candidates are ordered without the reference: those that the determinacy query proves
             first, those it flags last. The candidates go to the code loop below in this order, with five
             attempts each, until one program verifies with the ensures lines of its candidate unchanged. If
             none does, one more postcondition is generated with the prompt of `step1_specification.md`."""),
        block("Candidate postcondition", "Sent five times per task (see the sampling settings in `pipeline/README.md`).", base),
        block("Form of one example", "Three of these stand in the slot of the examples.", example),
        block("When Dafny rejects a candidate", "Sent once for that candidate, in place of the first prompt.", fix),
        block("Code loop, first call", "Sent once per candidate that is tried.", code),
        block("Code loop, after a failed attempt", "Sent in place of the first prompt.", again))


# ------------------------------------------------------------------------------------------ specification given
def given_specification():
    c = Script("cfs_v2.py")
    base = c.render(c.assign("solve", "base"), {
        "V.pre(parts)": "preamble and helper declarations of the task",
        "spec": "the specification of the benchmark: signature, requires and ensures lines"},
        {"BASE": c.render(c.assign(None, "BASE"))})
    fix = FIRST + c.render(c.assign(None, "FIX")) % "{{the end of the output of Dafny, at most 1500 characters}}"
    byp = FIRST + "\n\n" + bypass_message() + " Return ONLY a ```dafny code block."
    x = Script("xlang_bench.py")
    verus = x.render(x.assign("run_verus_task", "base"), {
        "pre": "preamble of the task file", "spec": "the specification section of the task file"})
    verus_spec = x.render(x.assign("run_verus_task", "convo", 1), {
        "missing[:3]": "a Python list of at most three of the missing lines, without their whitespace"}, {"base": FIRST})
    verus_fix = x.render(x.assign("run_verus_task", "convo", 2), {
        "out[-900:]": "output of Verus, last 900 characters"}, {"base": FIRST})
    lean = x.render(x.assign("run_lean_task", "base"), {"src0": "the task file"})
    lean_spec = x.render(x.assign("run_lean_task", "convo", 1), {
        "missing[:2]": "a Python list of at most two of the missing lines, without their whitespace"}, {"base": FIRST})
    lean_fix = x.render(x.assign("run_lean_task", "convo", 2), {
        "out[-1000:]": "output of Lean, last 1000 characters"}, {"base": FIRST})
    x3 = Script("xlang_v3.py")
    c3 = Script("cfs_v3_cont.py")
    # the two later scripts repeat these texts instead of importing them, so they are compared here
    assert x3.render(x3.assign("run_verus", "base"), {"pre": "preamble of the task file",
                                                        "spec": "the specification section of the task file"}) == verus
    assert x3.render(x3.assign("run_lean", "base"), {"src0": "the task file"}) == lean
    assert c3.render(c3.assign(None, "BASE")) == c.render(c.assign(None, "BASE"))
    assert c3.render(c3.assign(None, "FIX")) == c.render(c.assign(None, "FIX"))
    msg = {"FC.message(byp)": Raw(bypass_message())}
    verus_byp = x3.render(x3.assign("run_verus", "convo", 2), msg, {"base": FIRST})
    lean_byp = x3.render(x3.assign("run_lean", "convo", 2), msg, {"base": FIRST})
    return doc(
        "Step 2 when the benchmark gives the specification (Section 3.1, second paragraph)",
        para("""Here the model writes only the body and the proof, for the specification of the benchmark. In Dafny
             the body of the answer is verified under the benchmark's own specification, and in Verus and Lean
             an answer that changes a line of the given specification is rejected. An answer that verifies only
             through a bypass is rejected with feedback. The comparison is with the published results of the
             vericoding benchmark and of DafnyBench for the same model. The prompts of those published pipelines
             are their own and are not part of this repository."""),
        "## Dafny (`pipeline/cfs_v2.py`, function `solve`)\n",
        para("""Used on numpy_simple and verina with five attempts. `cfs_v3_cont.py` continues the same loop with
             the same texts under the acceptance rule of the published pipeline (exit code of the verifier)."""),
        block("Dafny, first call", "Sent once per task.", base),
        block("Dafny, after a failed verification",
              """Sent in place of the first prompt. When the answer does not hold the method with a body, the
              words "the answer did not contain the method NAME with a body", with the name of the method, stand
              in the place of the output of Dafny.""", fix),
        block("Dafny, when the program verifies only through a bypass", "Sent in place of the first prompt.", byp),
        "## Verus and Lean (`pipeline/xlang_bench.py`, run through `xlang_v3.py`)\n",
        para("""Used on the numpy_simple tasks of the two languages with five calls per task (`ROUNDS=4`).
             `xlang_v3.py` repeats the texts of `xlang_bench.py` and adds the bypass feedback. A run of the
             verifier that takes longer than 200 seconds ends the task."""),
        block("Verus, first call", "Sent once per task.", verus),
        block("Verus, when the answer changed the specification", "Sent in place of the first prompt.", verus_spec),
        block("Verus, after a failed verification", "Sent in place of the first prompt.", verus_fix),
        block("Verus, when the program verifies only through a bypass", "Sent in place of the first prompt.", verus_byp),
        block("Lean, first call", "Sent once per task.", lean),
        block("Lean, when the answer changed a theorem statement", "Sent in place of the first prompt.", lean_spec),
        block("Lean, after a failed check", "Sent in place of the first prompt.", lean_fix),
        block("Lean, when the file checks only through a bypass", "Sent in place of the first prompt.", lean_byp),
        "## DafnyBench\n",
        para("""The runner of the DafnyBench annotation comparison is not in this snapshot (see
             `pipeline/README.md`), so its prompt cannot be given here."""))


FILES = {"step1_specification.md": step1_specification, "step2_code.md": step2_code,
         "step3_witness_repair.md": step3_witness_repair, "compared_repairs.md": compared_repairs,
         "mbpp_dfy.md": mbpp_dfy, "given_specification.md": given_specification}

if __name__ == "__main__":
    check = "--check" in sys.argv[1:]
    differ = 0
    for name, make in FILES.items():
        text = make()
        path = os.path.join(HERE, name)
        if check:
            with open(path, encoding="utf-8", newline="") as f:
                same = f.read() == text
            differ += not same
            print("  %-4s %s" % ("ok" if same else "DIFF", name))
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            print("written", name)
    if check:
        print("All prompt files agree with the code." if not differ else "%d file(s) differ from the code." % differ)
        sys.exit(1 if differ else 0)
