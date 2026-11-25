"""Runs the functions of ../pipeline that build the prompts and compares what they send with the prompt files.

    python prompts/test_prompts.py

make_prompts.py copies the text of the prompts out of the code. This check looks at the same files from the
other side: it calls the functions that send the prompts, with the model and the verifier replaced by stand-ins
that return fixed answers, and compares every prompt that arrives at the stand-in with the block of the prompt
file whose slots are filled with the values of the test task. The comparison is exact, and the exit code is 1
if a prompt differs. No model call and no verifier call is made. Needs pyyaml, as the pipeline does.

Some scripts start their run when they are imported. Their functions are taken out of the syntax tree and
executed on their own (see `take`)."""
import ast, difflib, os, re, shutil, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "..", "pipeline")
sys.path.insert(0, PIPE)

import yaml
import vericode_compete as V
import big_run as BR
import fix_harness as H
import fix_canon as C
import fix_cheat as FC
import fix_oracle as O
import wit2 as W
import xlang_bench as X

DIFFER = []
COUNT = [0]


# ------------------------------------------------------------------------------------------- the prompt files
def blocks(name):
    """the prompts of one file by their heading"""
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        text = f.read()
    out = {}
    for section in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = section.partition("\n")
        m = re.search(r"^~~~text\n(.*?)\n~~~$", body, re.S | re.M)
        if m:
            assert title not in out, title
            out[title] = m.group(1)
    return out


def fill(template, slots, conditions=None):
    """the prompt that a block describes, for the given values of its slots and conditions"""
    def conditional(m):
        return m.group(2) if conditions[m.group(1)] else ""
    template = re.sub(r"\{\{if (.+?)\}\}(.*?)\{\{end if\}\}", conditional, template, flags=re.S)
    return re.sub(r"\{\{(.+?)\}\}", lambda m: slots[m.group(1)], template)


def same(label, sent, expected):
    COUNT[0] += 1
    print("  %-4s %s" % ("ok" if sent == expected else "DIFF", label))
    if sent != expected:
        DIFFER.append(label)
        for line in list(difflib.unified_diff(expected.splitlines(), sent.splitlines(), "prompt file", "sent", lineterm=""))[:20]:
            print("       " + line)


# ------------------------------------------------------------------------------------------------- stand-ins
class Model:
    """stands in for the model: hands out the given answers in order and keeps every prompt it is sent"""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent = []
        self.model = "stand-in"

    def ask(self, prompt, *rest):
        self.sent.append(prompt)
        return self.answers.pop(0)


def verifier(*results):
    """stands in for a verifier call: hands out the given (verified, output) pairs in order"""
    left = list(results)
    return lambda *args, **kw: left.pop(0)


def take(script, names, namespace):
    """defines the named functions and constants of a script in `namespace`, without running the script"""
    with open(os.path.join(PIPE, script), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    body = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names) or
            (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names)]
    assert len(body) == len(names), (script, names)
    exec(compile(ast.Module(body=body, type_ignores=[]), script, "exec"), namespace)
    return namespace


# ---------------------------------------------------------------------------------------------- the test task
PARTS = {"vc-description": "DESCRIPTION", "vc-preamble": "function F(x: int): int { x }", "vc-helpers": "",
         "vc-spec": "method M(a: int) returns (r: int)\n  requires a > 0\n  ensures r == a", "vc-code": "",
         "vc-postamble": ""}
HEAD = V.sig_head(PARTS["vc-spec"])
PROGRAM = "```dafny\nmethod M(a: int) returns (r: int)\n  requires a > 0\n  ensures r == %s\n{ %s }\n```"
KEEPS = PROGRAM % ("a", "r := 0;")              # keeps the ensures line
CHANGES = PROGRAM % ("0", "r := 0;")            # changes the ensures line
ASSUMES = PROGRAM % ("a", "assume false;")      # keeps it and uses a bypass
NO_METHOD = "```dafny\nlemma L() {}\n```"
BYPASS = {"the bypasses that were found, for example: uses 'assume'": "uses 'assume'"}


def step1():
    print("step1_specification.md")
    B = blocks("step1_specification.md")
    BR.WR.spec_syntax_ok = lambda parts, gen: (gen == "ensures r == a", "DAFNY-OUT")
    m = Model("no clause here", "ensures bad", "ensures r == a")
    BR.gen_spec_raw(PARTS, HEAD, m)
    first = m.sent[0]
    same("first call", first, fill(B["First call"], {
        "preamble of the task, at most 1500 characters": PARTS["vc-preamble"],
        "signature and requires lines of the method": HEAD,
        "task description, at most 1500 characters": "DESCRIPTION"}))
    same("the answer has no ensures line", m.sent[1], fill(B["When the answer has no ensures line"], {"the first prompt": first}))
    same("Dafny rejects the postcondition", m.sent[2], fill(B["When Dafny rejects the postcondition"], {
        "the first prompt": first,
        "the last 1200 characters of the output of Dafny, cut after the first 900": "DAFNY-OUT",
        "the postcondition of the previous answer": "ensures bad"}))


def step2():
    print("step2_code.md")
    B = blocks("step2_code.md")
    spec = HEAD + "\n    ensures r == a"
    slots = {"preamble and helper declarations of the task": V.pre(PARTS),
             "signature, requires lines and the ensures lines of S": spec}
    BR.ITERS = 2
    V.dverify = verifier((False, "DAFNY-OUT"), (False, "DAFNY-OUT"))
    m = Model(KEEPS, KEEPS)
    BR.gen_code_raw(PARTS, spec, m)
    same("first pass, first call", m.sent[0], fill(B["First pass, first call"], slots))
    same("first pass, failed verification", m.sent[1], fill(B["First pass, after a failed verification"], {
        "the first prompt": m.sent[0], "the end of the output of Dafny, at most 1200 characters": "DAFNY-OUT"}))
    for wording in ("orig", "v2"):
        # five answers: no method, a bypass, a changed ensures line, a failed verification, and one more to end the loop
        H.dverify2 = verifier((True, "verified"), (True, "verified"), (False, "DAFNY-OUT"))
        m = Model(NO_METHOD, ASSUMES, CHANGES, KEEPS, NO_METHOD)
        H.gen_code_fixed(PARTS, spec, m, iters=5, variant=wording, enforce_ens=["r == a"], guard=True)
        first = m.sent[0]
        failed = B["Wording `%s`, after a failed verification" % wording]
        out = "the end of the output of Dafny, at most 1500 characters"
        same("wording %s, first call" % wording, first, fill(B["Wording `%s`, first call" % wording], slots))
        same("wording %s, no method in the answer" % wording, m.sent[1],
             fill(failed, {"the first prompt": first, out: "the answer did not contain the method"}))
        same("wording %s, bypass" % wording, m.sent[2], fill(
            B["Both wordings, when the program verifies only through a bypass"], dict(BYPASS, **{"the first prompt": first})))
        same("wording %s, ensures line changed" % wording, m.sent[3], fill(
            B["Both wordings, when the program verifies but an ensures line was changed"], {"the first prompt": first}))
        same("wording %s, failed verification" % wording, m.sent[4], fill(failed, {"the first prompt": first, out: "DAFNY-OUT"}))


def compared_repairs():
    print("compared_repairs.md")
    B = blocks("compared_repairs.md")
    m = Model("a reason\nWEAK")
    BR.judge_reason(PARTS, "ensures r >= 0", m)
    same("LLM judge", m.sent[0], fill(B["LLM judge: is the postcondition complete?"], {
        "task description, at most 1000 characters": "DESCRIPTION", "the ensures lines of S": "ensures r >= 0"}))
    for arm, answer_of_the_judge in (("judge", "ANSWER-OF-THE-JUDGE"), ("det", None)):
        m = Model("ensures r == a")
        BR._llm_strengthen(PARTS, HEAD, "ensures r >= 0", m, arm, answer_of_the_judge)
        same("stronger postcondition, %s" % ("LLM judge" if arm == "judge" else "determinacy flag"), m.sent[0],
             fill(B["The stronger postcondition (LLM judge and determinacy flag)"], {
                 "signature and requires lines of the method": HEAD,
                 "task description, at most 1000 characters": "DESCRIPTION",
                 "the ensures lines of S": "ensures r >= 0",
                 "the answer of the judge, at most 400 characters": "ANSWER-OF-THE-JUDGE"},
                 {"the repair is the LLM judge": arm == "judge"}))


def step3():
    print("step3_witness_repair.md")
    B = blocks("step3_witness_repair.md")
    W.WR = None                                                  # no enumeration after the model's answers
    H.dverify2 = lambda src, timeout=90: (False, "x.dfy(1,1): Error: BAD")    # every added clause is rejected
    S = "ensures r >= 0"
    rejected = "the additional ensures lines are not valid Dafny in this method (Error: BAD)"
    for with_preamble in (True, False):
        tag = "with declarations" if with_preamble else "without declarations"
        parts = dict(PARTS) if with_preamble else dict(PARTS, **{"vc-preamble": ""})
        conditions = {"the task has declarations above the method": with_preamble,
                      "the task declares functions": with_preamble}
        slots = {"task description, at most 1500 characters": "DESCRIPTION",
                 "these declarations, at most 3000 characters": V.pre(parts).strip(),
                 "signature and requires lines of the method": O.head(parts),
                 "the ensures lines of the current postcondition S": S,
                 "names of at most 12 of these functions": "F"}

        m = Model("not in the format", "DETERMINATE")
        W.find_witness2(parts, S, "CODE", m, [])
        same("witness search, first call, " + tag, m.sent[0], fill(B["Witness search, first call"], dict(slots, **{
            "the parameters with their types, or (none)": "a: int",
            "the return variables with their types": "r: int"}), conditions))
        same("witness search, rejected answer, " + tag, m.sent[1], fill(B["Witness search, after a rejected answer"], {
            "the first prompt": m.sent[0],
            "the reason the checker gives": "the answer was not in the INPUT / OUTPUT1 / OUTPUT2 format",
            "the previous answer, at most 700 characters": "not in the format"}))

        witness = {"input": "var a: int := 1;", "o1": "var r: int := 1;", "o2": "var r: int := 2;"}
        answer = "UNINTENDED\nCORRECT: A\n```dafny\nensures r == a\n```"
        m = Model(answer, answer)
        W.arbiter(parts, S, "CODE", witness, m)
        same("arbiter, first call, " + tag, m.sent[0], fill(B["Arbiter, first call"], dict(slots, **{
            "the input of the witness as Dafny statements, or (no parameters)": witness["input"],
            "the first output of the witness as Dafny statements": witness["o1"],
            "the second output of the witness as Dafny statements": witness["o2"]}), conditions))
        again = {"the previous answer, at most 1200 characters": answer, "the reason of the rejection": rejected}
        same("arbiter, rejected clause, " + tag, m.sent[1],
             fill(B["Arbiter, after a rejected clause"], dict(again, **{"the first prompt": m.sent[0]})))

        answer = "UNINTENDED\n```dafny\nensures r == a\n```"
        again["the previous answer, at most 1200 characters"] = answer
        m = Model(answer, answer)
        W.flag_strengthen(parts, S, "CODE", m)
        same("flag only, first call, " + tag, m.sent[0], fill(B["Flag only, first call"], slots, conditions))
        same("flag only, rejected answer, " + tag, m.sent[1],
             fill(B["Flag only, after a rejected answer"], dict(again, **{"the first prompt": m.sent[0]})))

        answer = "```dafny\nensures r == a\n```"
        again["the previous answer, at most 1200 characters"] = answer
        m = Model(answer, answer)
        W.force_det(parts, S, "CODE", m)
        same("solver decides, first call, " + tag, m.sent[0], fill(B["Solver decides, first call"], slots, conditions))
        same("solver decides, rejected answer, " + tag, m.sent[1],
             fill(B["Solver decides, after a rejected answer"], dict(again, **{"the first prompt": m.sent[0]})))

    passed = {}
    H.gen_code_fixed = lambda parts, spec, asker, **kw: (passed.update(spec=spec, kw=kw) or (None, []))
    W.recode(PARTS, O.head(PARTS), "M", S + "\n    ensures r == a", "method M() {}\n", None)
    same("the specification that goes into the code prompt", passed["spec"], fill(B["Specification part of the code prompt"], {
        "signature and requires lines of the method": O.head(PARTS),
        "the ensures lines of S followed by the added clauses C": S + "\n    ensures r == a",
        "the accepted program for S": "method M() {}"}))
    assert passed["kw"]["variant"] == "v2" and passed["kw"]["guard"] is True, passed["kw"]


def mbpp_dfy():
    print("mbpp_dfy.md")
    B = blocks("mbpp_dfy.md")
    examples = {str(i): ("DESCRIPTION %d" % i, "method E%d() returns (r: int)" % i, "ensures e%d\nensures f%d" % (i, i))
                for i in range(1, 6)}
    ns = take("mbpp_boost.py", {"fewshot_block", "gen_spec_cands", "ens_norm", "code_loop"}, {
        "re": re, "V": V, "KSPEC": 2, "ITERS": 4, "exdb": {"2": None}, "FEWSHOT": examples,
        "WR": types.SimpleNamespace(spec_syntax_ok=lambda parts, gen: (gen == "ensures r == a", "DAFNY-OUT")),
        "det_gate": types.SimpleNamespace(completeness_determinacy=lambda parts, gen: 1.0)})
    # the task is example 2 itself, so the examples are 1, 3 and 4
    block = "\n\n".join(fill(B["Form of one example"], {
        "description of the example task": examples[i][0], "its method signature": examples[i][1],
        "its ensures lines": examples[i][2]}) for i in ("1", "3", "4"))
    same("three examples", ns["fewshot_block"]("2"), block)
    m = Model("ensures bad", "ensures r == a", "ensures r == a")
    ns["gen_spec_cands"](PARTS, HEAD, "2", m)
    first = m.sent[0]
    same("candidate postcondition", first, fill(B["Candidate postcondition"], {
        "three examples in the form shown below, separated by empty lines": block,
        "task description, at most 1500 characters": "DESCRIPTION",
        "signature and requires lines of the reference method": HEAD}))
    same("Dafny rejects a candidate", m.sent[1], fill(B["When Dafny rejects a candidate"], {
        "the first prompt": first,
        "the last 1200 characters of the output of Dafny, cut after the first 800": "DAFNY-OUT",
        "the postcondition of the previous answer": "ensures bad"}))
    same("the next candidate is asked for with the first prompt", m.sent[2], first)

    V.dverify = verifier((False, "DAFNY-OUT"), (False, "DAFNY-OUT"), (True, "verified"), (False, "DAFNY-OUT"))
    m = Model(CHANGES, KEEPS, CHANGES, KEEPS)
    ns["code_loop"](PARTS, HEAD, "ensures r == a", m)
    first = m.sent[0]
    same("code loop, first call", first, fill(B["Code loop, first call"], {
        "signature and requires lines of the reference method": HEAD,
        "the ensures lines of the candidate": "ensures r == a"}))
    for i, (answer, changed, fails) in enumerate([(CHANGES, True, True), (KEEPS, False, True), (CHANGES, True, False)]):
        same("code loop, failed attempt (ensures line changed: %s, does not verify: %s)" % (changed, fails), m.sent[i + 1],
             fill(B["Code loop, after a failed attempt"], {
                 "the first prompt": first,
                 "the program of the previous answer, at most 3500 characters": V.code_of(answer),
                 "the end of the output of Dafny, at most 1200 characters": "DAFNY-OUT"},
                 {"an ensures line was changed": changed, "the program does not verify": fails}))


def given_specification():
    print("given_specification.md")
    B = blocks("given_specification.md")

    # Dafny: no method, a failed verification, a bypass, and one more answer to end the loop
    H.dverify2 = verifier((False, "DAFNY-OUT"), (True, "verified"), (False, "DAFNY-OUT"))
    ns = take("cfs_v2.py", {"BASE", "FIX", "solve"}, {"re": re, "V": V, "H": H, "C": C, "FC": FC, "ITERS": 4})
    m = Model(NO_METHOD, KEEPS, ASSUMES, KEEPS)
    ns["solve"](PARTS, m)
    first = m.sent[0]
    out = "the end of the output of Dafny, at most 1500 characters"
    same("Dafny, first call", first, fill(B["Dafny, first call"], {
        "preamble and helper declarations of the task": V.pre(PARTS),
        "the specification of the benchmark: signature, requires and ensures lines": PARTS["vc-spec"]}))
    same("Dafny, no method in the answer", m.sent[1], fill(B["Dafny, after a failed verification"], {
        "the first prompt": first, out: "the answer did not contain the method M with a body"}))
    same("Dafny, failed verification", m.sent[2],
         fill(B["Dafny, after a failed verification"], {"the first prompt": first, out: "DAFNY-OUT"}))
    same("Dafny, bypass", m.sent[3],
         fill(B["Dafny, when the program verifies only through a bypass"], dict(BYPASS, **{"the first prompt": first})))

    # Verus and Lean: the first runner (xlang_bench.py) and the one of the reported runs (xlang_v3.py)
    folder = tempfile.mkdtemp()
    preamble = "use vstd::prelude::*;\n\nverus! {"
    spec = "fn f(x: u32) -> (r: u32)\n    requires x < 10,\n    ensures r == x,\n    ensures r < 10,\n    ensures r >= 0,\n"
    verus_task = os.path.join(folder, "task.yaml")
    with open(verus_task, "w", encoding="utf-8") as f:
        yaml.safe_dump({"vc-preamble": preamble, "vc-spec": spec, "vc-helpers": "", "vc-postamble": "\n}\nfn main() {}"}, f)
    lean_file = ("def f (x : Nat) : Nat :=\n  sorry\n-- <vc-theorems>\ntheorem f_spec (x : Nat) : f x = x :=\n  sorry\n"
                 "theorem f_two (x : Nat) : f x + 0 = x :=\n  sorry\ntheorem f_three (x : Nat) : 0 + f x = x :=\n  sorry\n"
                 "-- </vc-theorems>\n")
    lean_task = os.path.join(folder, "task.lean")
    with open(lean_task, "w", encoding="utf-8") as f:
        f.write(lean_file)
    verus = {"keeps": "```rust\n" + spec + "{ x }\n```", "assumes": "```rust\n" + spec + "{ assume(false); x }\n```",
             "changes": "```rust\nfn g() {}\n```"}
    proved = lean_file.replace("sorry", "by simp")
    lean = {"keeps": "```lean\n" + proved + "```", "assumes": "```lean\n" + proved + "axiom cheat : False\n```",
            "changes": "```lean\ndef f := 1\n```"}
    missing_verus = str([X.nows(line) for line in spec.splitlines()][:3])
    missing_lean = str([X.nows(line) for line in lean_file.splitlines() if line.startswith("theorem")][:2])

    def run(runner, language, function):
        # the specification is changed, the verifier fails, and in xlang_v3.py the answer then verifies through a bypass
        answers = [language["changes"], language["keeps"]]
        if runner == "xlang_v3.py":
            answers.append(language["assumes"])
        answers.append(language["keeps"])
        m = Model(*answers)
        V.ask = lambda model, prompt: m.ask(prompt)
        check = verifier((False, "VERIFIER-OUT"), (True, "verified"), (True, "verified"))
        X.verify_verus = X.verify_lean = check
        if runner == "xlang_v3.py":
            function = take(runner, {"NL", function}, {"X": X, "FC": FC, "yaml": yaml, "re": re, "ask": m.ask})[function]
        else:
            function = getattr(X, function)
        function(verus_task if language is verus else lean_task)
        return m.sent

    for runner, function in (("xlang_bench.py", "run_verus_task"), ("xlang_v3.py", "run_verus")):
        sent = run(runner, verus, function)
        same("Verus, first call (%s)" % runner, sent[0], fill(B["Verus, first call"], {
            "preamble of the task file": preamble, "the specification section of the task file": spec}))
        same("Verus, specification changed (%s)" % runner, sent[1], fill(B["Verus, when the answer changed the specification"], {
            "the first prompt": sent[0],
            "a Python list of at most three of the missing lines, without their whitespace": missing_verus}))
        same("Verus, failed verification (%s)" % runner, sent[2], fill(B["Verus, after a failed verification"], {
            "the first prompt": sent[0], "output of Verus, last 900 characters": "VERIFIER-OUT"}))
        if runner == "xlang_v3.py":
            same("Verus, bypass (%s)" % runner, sent[3], fill(
                B["Verus, when the program verifies only through a bypass"], dict(BYPASS, **{"the first prompt": sent[0]})))
    for runner, function in (("xlang_bench.py", "run_lean_task"), ("xlang_v3.py", "run_lean")):
        sent = run(runner, lean, function)
        same("Lean, first call (%s)" % runner, sent[0], fill(B["Lean, first call"], {"the task file": lean_file}))
        same("Lean, theorem statement changed (%s)" % runner, sent[1],
             fill(B["Lean, when the answer changed a theorem statement"], {
                 "the first prompt": sent[0],
                 "a Python list of at most two of the missing lines, without their whitespace": missing_lean}))
        same("Lean, failed check (%s)" % runner, sent[2], fill(B["Lean, after a failed check"], {
            "the first prompt": sent[0], "output of Lean, last 1000 characters": "VERIFIER-OUT"}))
        if runner == "xlang_v3.py":
            same("Lean, bypass (%s)" % runner, sent[3], fill(B["Lean, when the file checks only through a bypass"], {
                "the first prompt": sent[0],
                "the bypasses that were found, for example: uses 'assume'": "introduces an axiom"}))
    shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    for section in (step1, step2, compared_repairs, step3, mbpp_dfy, given_specification):
        section()
    if DIFFER:
        print("%d of %d prompts differ from their blocks." % (len(DIFFER), COUNT[0]))
        sys.exit(1)
    print("All %d prompts that the code sent are equal to their blocks." % COUNT[0])
