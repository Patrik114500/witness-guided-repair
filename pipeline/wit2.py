"""Witness-guided specification repair, version 2 (2026-11-18 evening).

What changed against version 1 (witness_repair.py + big_run.witness_arm):
  * WITNESS SEARCH. v1 enumerated a few integers or perturbed the code's own output, supported only int, nat,
    bool and int arrays, and found a witness for about 4% of the weak, flagged specifications. v2 asks the
    model to PROPOSE a concrete input and two different outputs as Dafny literals (any types, several return
    values), and uses the proposal only if the tool CONFIRMS it: the precondition holds, both outputs satisfy
    the specification under test, and the outputs differ. Confirmation is by executing the compiled
    predicates or, when the specification is not compilable, by a verifier proof of the same facts. The v1
    enumerator stays as a free fallback.
  * REPAIR IS CONJUNCTIVE. v1 let the model rewrite the whole postcondition. v2 asks only for ADDITIONAL
    ensures C and builds S' = S && C mechanically, so S' implies S: a specification that already implied the
    intended behaviour keeps doing so by construction. C is checked on the witness: it has to reject the
    output the arbiter called wrong and keep the one it called right.
  * CODE. The accepted body is first re-verified under S' without any model call. Only if that fails is the
    model asked, with the old body as a starting point, through the guarded loop (bypasses rejected).
Keep-on-fail as before: if no code verifies against S', the previous accepted state stays.

Run:  MODEL=<id> [WORKERS=8] [LIMIT=n] [CAP=usd] [ONLY=weak|good] python3 -u wit2.py
Reads the audited big-run state (fix_state5: oracle v4 scores, canonical accepts, stage E); targets are the
accepted tasks whose specification the determinacy check flags. Output: /tmp/wit2_<model>.jsonl (resumable).
"""
import os, sys, re, json, time, random, shutil, signal, tempfile, subprocess, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_canon as FCN
import fix_cheat as FC
import fix_oracle as O
try:
    import witness_repair as WR
except Exception:
    WR = None

NL = chr(10); BS = chr(92); DNL = '"' + BS + 'n"'            # DNL is the Dafny string literal for a newline
ROUNDS = int(os.environ.get("ROUNDS", "3")); WIT_TRIES = int(os.environ.get("WIT_TRIES", "2")); ITERS = int(os.environ.get("ITERS", "5"))
CLAUSE_TRIES = int(os.environ.get("CLAUSE_TRIES", "2"))      # proposals of additional clauses per round (2 in the standard budget)
BAD_STMT = re.compile(r"\b(assume|assert|expect|while|for|forall|exists|requires|ensures|method|function|lemma|print|return|"
                      r"modifies|decreases|calc|reveal)\b|:\||:=\s*\*")
EXTRA_BYPASS = [(r"decreases\s*\*", "uses 'decreases *'"), (r"\bexpect\b", "uses 'expect'")]


def bypasses(code):
    return FC.cheats(code, "dafny") + [d for p, d in EXTRA_BYPASS if re.search(p, code or "")]


def conj(exprs):
    return "(" + " && ".join("(%s)" % e for e in exprs) + ")" if exprs else "true"


def one_state(e):
    """for methods without a modifies clause: old(X) == X, and allocation predicates carry no functional content"""
    e = re.sub(r"\bold\s*\(", "(", e)
    return re.sub(r"\b(fresh|unchanged|allocated)\s*\(([^()]*)\)", "true", e)


def drun2(src, timeout=120):
    d = tempfile.mkdtemp(prefix="w2_", dir="/tmp")
    try:
        p = os.path.join(d, "w.dfy")
        with open(p, "w") as f:
            f.write(src)
        pr = subprocess.Popen([V.DAFNY, "run", "--target:py", "--no-verify", p], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, start_new_session=True, cwd=d)
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
            return "TIMEOUT"
        return o
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _file_head(parts, code):
    try:
        hp = O.helpers_from_code(parts, code) if code else ""
    except Exception:
        hp = ""
    return (hp + NL if hp.strip() else "") + V.pre(parts) + NL


def run_flags(parts, code, blocks, bare=False):
    """execute labelled boolean expressions. blocks = [(label, statements, expression)] -> ({label: bool}, output)"""
    body = []
    for lab, st, ex in blocks:
        body.append("  {" + NL + "    " + st + NL + "    var f9z: bool := " + ex + ";" + NL + '    print "' + lab + '=", f9z, ' + DNL + ";" + NL + "  }")
    src = ("" if bare else _file_head(parts, code)) + "method Main() {" + NL + NL.join(body) + NL + "}" + NL
    out = drun2(src)
    fl = {}
    for lab, _, _ in blocks:
        m = re.search(r"\b%s=(true|false)" % lab, out)
        if m:
            fl[lab] = m.group(1) == "true"
    return fl, out


def prove_flag(parts, code, st, ex):
    """the same fact by proof: True if `ex` is proved for the concrete statements, False if its negation is, else None"""
    for neg, val in ((False, True), (True, False)):
        src = _file_head(parts, code) + "method W9check() {" + NL + "  " + st + NL + "  assert " + ("!(%s)" % ex if neg else ex) + ";" + NL + "}" + NL
        ok, _ = H.dverify2(src, 60)
        if ok:
            return val
    return None


def rename(st, rets, tag):
    for rv, _ in rets:
        st = re.sub(r"\b%s\b" % re.escape(rv), rv + tag, st)
    return st


def diff_expr(rets):
    ds = []
    for rv, rt in rets:
        t = rt.replace(" ", "")
        if t.startswith("array<") and not t.startswith("array<array"):
            ds.append("(%s_w1[..] != %s_w2[..])" % (rv, rv))
        elif t.startswith("array"):
            return None
        else:
            ds.append("(%s_w1 != %s_w2)" % (rv, rv))
    return " || ".join(ds) if ds else None


def _first_err(out):
    for ln in (out or "").split(NL):
        if "Error" in ln or "error" in ln:
            return re.sub(r"^\S+\.dfy\(\d+,\d+\):\s*", "", ln.strip())[:160]
    return (out or "").strip()[-160:]


def check_witness(parts, code, S_exprs, inp, o1, o2, rets):
    """is (inp, o1, o2) a witness of non-determinacy? {"ok", "why", "mode"}"""
    prec = conj(O.req_lines(parts)); pred = conj(S_exprs); diff = diff_expr(rets)
    if diff is None:
        return {"ok": False, "why": "unsupported return type", "mode": None}
    dblock = ("WD", inp + " " + rename(o1, rets, "_w1") + " " + rename(o2, rets, "_w2"), diff)
    blocks = [dblock, ("WP", inp, prec), ("WA", inp + " " + o1, pred), ("WB", inp + " " + o2, pred)]
    fl, out = run_flags(parts, code, blocks)
    mode = "run"
    if len(fl) < 4:
        # the file as a whole did not compile or stopped: the literals alone must still run
        fd, outd = run_flags(parts, None, [dblock], bare=True)
        if "WD" not in fd:
            fd, outd = run_flags(parts, code, [dblock])
        if "WD" not in fd:
            return {"ok": False, "why": "the statements are not valid Dafny (%s)" % _first_err(outd), "mode": None}
        fl = {"WD": fd["WD"]}
        if fl["WD"]:
            src = (_file_head(parts, code) + "method W9check() {" + NL + "  " + inp + NL + "  assert " + prec + ";" + NL +
                   "  { " + o1 + NL + "    assert " + pred + "; }" + NL + "  { " + o2 + NL + "    assert " + pred + "; }" + NL + "}" + NL)
            ok, vout = H.dverify2(src, 90)
            if ok:
                fl.update({"WP": True, "WA": True, "WB": True}); mode = "proof"
            else:
                return {"ok": False, "why": "the checker could not confirm that the precondition holds and that both outputs satisfy the "
                        "postcondition (%s)" % _first_err(vout if "rror" in vout else out), "mode": None}
    if not fl.get("WD"):
        return {"ok": False, "why": "OUTPUT1 and OUTPUT2 are the same value", "mode": mode}
    if not fl.get("WP"):
        return {"ok": False, "why": "the input does not satisfy the precondition", "mode": mode}
    if not fl.get("WA"):
        return {"ok": False, "why": "OUTPUT1 does NOT satisfy the postcondition under test for this input", "mode": mode}
    if not fl.get("WB"):
        return {"ok": False, "why": "OUTPUT2 does NOT satisfy the postcondition under test for this input", "mode": mode}
    return {"ok": True, "why": "", "mode": mode}


def split_sections(txt):
    t = re.sub(r"```[a-zA-Z]*", "", txt or "")
    if re.match(r"\s*\W*DETERMINATE\b", t, re.I) and not re.search(r"OUTPUT\s*1", t, re.I):
        return "DETERMINATE"
    sp = re.split(r"^[ \t#*>\-]*(INPUT|OUTPUT[ _]*1|OUTPUT[ _]*2)[ \t*]*:?[ \t*]*", t, flags=re.I | re.M)
    d = {}
    for i in range(1, len(sp) - 1, 2):
        d[re.sub(r"\s+", "", sp[i]).upper()] = sp[i + 1].strip()
    if not all(k in d for k in ("INPUT", "OUTPUT1", "OUTPUT2")):
        return None
    return d


def clean_stmts(text):
    out = []
    for ln in (text or "").split(NL):
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        if ":=" in s or s.endswith(";") or (out and not out[-1].rstrip().endswith(";")):
            out.append(s)
        else:
            break
    return " ".join(out)


def stmts_bad(st, names):
    if BAD_STMT.search(st):
        return "the statements contain a construct that is not allowed (only literal `var` declarations)"
    for n in names:
        if not re.search(r"\bvar\s+%s\b" % re.escape(n), st):
            return "the statements do not declare `%s`" % n
    return None


WIT_PROMPT = (
    "You are checking a Dafny postcondition for under-specification." + NL + NL +
    "Task description:" + NL + "%(nl)s" + NL + NL +
    "%(pre)s"
    "Method signature and precondition:" + NL + "%(head)s" + NL + NL +
    "Postcondition under test:" + NL + "    %(spec)s" + NL + NL +
    "Find ONE concrete input that satisfies the precondition, and TWO DIFFERENT outputs that BOTH satisfy the postcondition "
    "under test for that input. If you can, choose the pair so that one output is what the task description asks for and the "
    "other is clearly wrong: that exposes a missing requirement. Keep it tiny (lengths at most 4, small numbers)." + NL + NL +
    "If the postcondition admits exactly one output for every valid input, answer with the single word DETERMINATE." + NL + NL +
    "Otherwise answer in exactly this format and nothing else:" + NL +
    "INPUT:" + NL + "<Dafny statements declaring every parameter: %(params)s>" + NL +
    "OUTPUT1:" + NL + "<Dafny statements declaring the return variable(s): %(rets)s>" + NL +
    "OUTPUT2:" + NL + "<the same variable(s) with a different value>" + NL + NL +
    "Rules for the statements: one `var name: type := value;` per variable, literal values only. "
    "Sequences: `var s: seq<int> := [1, 2, 3];`. Arrays: `var a: array<int> := new int[3] [1, 2, 3];` (empty: `new int[0]`). "
    "Strings: `var t: string := \"ab\";`. No method calls, no loops, no assume or assert. If the method has no parameters, "
    "leave INPUT empty.")


def find_witness2(parts, S, code, asker, log):
    name, params, rets = O.sig_all(parts)
    S_exprs = [one_state(e) for e in O.spec_ensures(S)]
    pre = V.pre(parts).strip()
    prompt = WIT_PROMPT % {"nl": (parts.get("vc-description", "") or "").strip()[:1500],
                           "pre": ("Declarations available to the specification:" + NL + pre[:3000] + NL + NL) if pre else "",
                           "head": O.head(parts), "spec": S,
                           "params": ", ".join("%s: %s" % p for p in params) or "(none)",
                           "rets": ", ".join("%s: %s" % r for r in rets)}
    fb = ""
    for t in range(WIT_TRIES):
        r = asker.ask(prompt + fb)
        if not r.strip():
            log.append("api-fail"); return None
        sec = split_sections(r)
        if sec == "DETERMINATE":
            log.append("model-determinate"); break
        why = None
        if sec is None:
            why = "the answer was not in the INPUT / OUTPUT1 / OUTPUT2 format"
        else:
            inp, o1, o2 = (clean_stmts(sec[k]) for k in ("INPUT", "OUTPUT1", "OUTPUT2"))
            why = (stmts_bad(inp, [p for p, _ in params]) or stmts_bad(o1, [x for x, _ in rets]) or stmts_bad(o2, [x for x, _ in rets]))
            if not why:
                res = check_witness(parts, code, S_exprs, inp, o1, o2, rets)
                if res["ok"]:
                    return {"input": inp, "o1": o1, "o2": o2, "src": "model", "mode": res["mode"], "try": t + 1}
                why = res["why"]
        log.append(why + (" || RAW: " + r.strip()[:240] if sec is None else ""))
        fb = (NL + NL + "Your previous answer was rejected by the checker: " + why + "." + NL + "Previous answer:" + NL + r.strip()[:700] + NL + NL +
              "Give a corrected answer in the same format, or DETERMINATE.")
    # free fallback: the version-1 enumerator (single return value, int / nat / bool / int arrays)
    if WR is not None and len(rets) == 1 and not O.TWO.search(S):
        try:
            w = WR.find_witness(parts, S, code)
        except Exception:
            w = None
        if w:
            pt = {p: t.replace(" ", "") for p, t in params}
            rv, rt = rets[0]; rt0 = rt.replace(" ", "")
            try:
                inp = " ".join(V.lit_param(pn, v, pt[pn]) for pn, v in w["input"].items())
                return {"input": inp, "o1": V.ret_bind(rv, w["r1"], rt0), "o2": V.ret_bind(rv, w["r2"], rt0), "src": "enum", "mode": "run", "try": 0}
            except Exception:
                pass
    return None


ARB_PROMPT = (
    "A Dafny method has to implement this task:" + NL + "%(nl)s" + NL + NL +
    "%(pre)s"
    "Signature and precondition:" + NL + "%(head)s" + NL + NL +
    "Its current postcondition:" + NL + "    %(spec)s" + NL + NL +
    "For this input" + NL + "    %(inp)s" + NL + "the current postcondition accepts BOTH of the following outputs." + NL +
    "Output A:" + NL + "    %(o1)s" + NL + "Output B:" + NL + "    %(o2)s" + NL + NL +
    "According to the task description, is it INTENDED that both outputs are acceptable for this input (the task leaves the "
    "choice open), or UNINTENDED (the task determines the answer, so at least one of the two is wrong)?" + NL +
    "Line 1: exactly INTENDED or UNINTENDED." + NL +
    "If UNINTENDED, line 2: `CORRECT: A`, `CORRECT: B` or `CORRECT: NEITHER`. Then, in a ```dafny block, write ADDITIONAL "
    "postcondition lines (each starting with `ensures`) that every correct output of the task satisfies for every valid input, and "
    "that reject the wrong output above. The existing ensures lines stay exactly as they are: do not repeat or rewrite them. "
    "Use only the method's parameters, its return variable(s)%(fn)s. Do not introduce new functions.")


def parse_arbiter(r):
    lines = [l.strip() for l in (r or "").strip().split(NL) if l.strip()]
    first = re.sub(r"[^A-Z]", "", lines[0].upper()) if lines else ""
    if first.startswith("UNINTENDED"):
        v = "UNINTENDED"
    elif first.startswith("INTENDED"):
        v = "INTENDED"
    else:
        up = (r or "").upper()
        v = "UNINTENDED" if "UNINTENDED" in up else ("INTENDED" if "INTENDED" in up else "UNCLEAR")
    m = re.search(r"CORRECT\s*:\s*`?\s*(A|B|NEITHER)\b", r or "", re.I)
    return v, (m.group(1).upper() if m else None)


def extract_clauses(r, S):
    blocks = re.findall(r"```(?:dafny)?\s*(.*?)```", r or "", re.S)
    if blocks:
        cut = []
        for b in blocks:
            keep = []
            for ln in b.split(NL):
                if ln.strip().startswith("{"):
                    break
                keep.append(ln)
            cut.append(NL.join(keep))
        src = NL.join(cut)
    else:
        src = NL.join(l for l in (r or "").split(NL) if l.strip().startswith("ensures"))
    have = set(H.nows(e) for e in O.spec_ensures(S))
    out = []
    for e in V.ensures_list(src):
        e = re.sub(r";\s*$", "", e).strip()
        if e and "`" not in e and H.nows(e) not in have and H.nows(e) not in [H.nows(x) for x in out]:
            out.append(e)
    return out


def spec_ok(parts, spec_text):
    src = (V.pre(parts) + NL + O.head(parts) + NL + "    " + spec_text + NL + "{" + NL + "  assume {:axiom} false;" + NL + "}" + NL)
    return H.dverify2(src, 60)


def join_spec(S, C):
    return S.rstrip() + "".join(NL + "    ensures " + c for c in C)


def well_formed_clauses(parts, S, C):
    """the additional clauses that keep S && C well-formed (all of them, or the largest prefix-closed subset)"""
    if not C:
        return [], ""
    ok, err = spec_ok(parts, join_spec(S, C))
    if ok:
        return C, ""
    kept = []
    for c in C:
        if spec_ok(parts, join_spec(S, kept + [c]))[0]:
            kept.append(c)
    return kept, _first_err(err)


def check_clause(parts, code, C, wit, correct):
    """does C separate the two witness outputs the way the arbiter said? (status, feedback)"""
    predC = conj([one_state(e) for e in C])
    blocks = [("CA", wit["input"] + " " + wit["o1"], predC), ("CB", wit["input"] + " " + wit["o2"], predC)]
    fl, _ = run_flags(parts, code, blocks)
    a = fl.get("CA"); b = fl.get("CB")
    if a is None:
        a = prove_flag(parts, code, blocks[0][1], predC)
    if b is None:
        b = prove_flag(parts, code, blocks[1][1], predC)
    if a is None or b is None:
        return "unknown", "", (a, b)
    want = {"A": (True, False), "B": (False, True), "NEITHER": (False, False)}.get(correct)
    if want is None:
        ok = not (a and b)
    else:
        ok = (a, b) == want
    if ok:
        return "ok", "", (a, b)
    msg = []
    if a and b:
        msg.append("they still accept both Output A and Output B")
    else:
        if correct == "A" and not a:
            msg.append("they reject Output A, which you called correct")
        if correct == "B" and not b:
            msg.append("they reject Output B, which you called correct")
        if correct in ("B", "NEITHER") and a:
            msg.append("they still accept Output A")
        if correct in ("A", "NEITHER") and b:
            msg.append("they still accept Output B")
    return "bad", "; ".join(msg) or "they do not separate the two outputs", (a, b)


def arbiter(parts, S, code, wit, asker):
    pre = V.pre(parts).strip()
    names = sorted(H.declared_names(pre))
    base = ARB_PROMPT % {"nl": (parts.get("vc-description", "") or "").strip()[:1500],
                         "pre": ("Declarations available to the specification:" + NL + pre[:3000] + NL + NL) if pre else "",
                         "head": O.head(parts), "spec": S, "inp": wit["input"] or "(no parameters)",
                         "o1": wit["o1"], "o2": wit["o2"],
                         "fn": (" and the functions already declared for this task (%s)" % ", ".join(names[:12])) if names else ""}
    r = asker.ask(base)
    if not r.strip():
        return "API-FAIL", None, [], {}
    verdict, correct = parse_arbiter(r)
    info = {"clause_tries": 0}
    if verdict != "UNINTENDED":
        return verdict, correct, [], info
    C = []
    for t in range(CLAUSE_TRIES):
        info["clause_tries"] = t + 1
        cand = extract_clauses(r, S)
        C, err = well_formed_clauses(parts, S, cand)
        if C:
            st, fb, ab = check_clause(parts, code, C, wit, correct)
            info["clause_check"] = st; info["clause_ab"] = ab
            if st in ("ok", "unknown"):
                return verdict, correct, C, info
            why = "on the input above " + fb
        else:
            info["clause_check"] = "none"
            why = ("it contained no additional ensures line" if not cand else "the additional ensures lines are not valid Dafny in this method (%s)" % err)
        if t == CLAUSE_TRIES - 1:
            break
        r = asker.ask(base + NL + NL + "Your previous answer:" + NL + r.strip()[:1200] + NL + NL + "It was rejected: " + why + "." + NL +
                      "Answer again in the same format (line 1 UNINTENDED, line 2 CORRECT: ..., then the ```dafny block with corrected "
                      "ADDITIONAL ensures lines only).")
        if not r.strip():
            break
        v2, c2 = parse_arbiter(r)
        correct = c2 or correct
        C = []
    return verdict, correct, [], info


def recode(parts, head, name, S2, prev_code, asker):
    """code for the strengthened specification: (code or None, how). The old body first, without a model call."""
    S2_exprs = O.spec_ensures(S2)
    prog = FCN.canonical_program(prev_code, name, head, S2)
    if prog:
        blk = H.dedupe_block(parts, prog)
        ok, _ = H.dverify2(V.assemble(parts, blk))
        if ok and not bypasses(blk):
            return blk, "free"
    spec = (head + NL + "    " + S2 + NL + NL + "A previous version of this method verified against the postcondition WITHOUT its last ensures "
            "line(s). Reuse and adapt it (strengthen the loop invariants if needed):" + NL + "```dafny" + NL + (prev_code or "").strip() + NL + "```")
    code, att = H.gen_code_fixed(parts, spec, asker, iters=ITERS, variant="v2", enforce_ens=S2_exprs, guard=True)
    if code is not None and bypasses(code):
        code = None
    return code, "model:%d" % len(att)


FLAG_PROMPT = (
    "A Dafny method has to implement this task:" + NL + "%(nl)s" + NL + NL +
    "%(pre)s"
    "Signature and precondition:" + NL + "%(head)s" + NL + NL +
    "Its current postcondition:" + NL + "    %(spec)s" + NL + NL +
    "A solver check could NOT prove that this postcondition determines the output uniquely for every valid input, so it may be "
    "missing a requirement of the task." + NL +
    "According to the task description, is the output of the method uniquely determined by its input?" + NL +
    "Line 1: exactly one of" + NL +
    "  INTENDED    (the description leaves the choice open, several different outputs are acceptable)" + NL +
    "  COMPLETE    (the output is unique and the current postcondition already pins it down)" + NL +
    "  UNINTENDED  (the output is unique but the current postcondition does not pin it down)" + NL +
    "If UNINTENDED, then write, in a ```dafny block, ADDITIONAL postcondition lines (each starting with `ensures`) that every "
    "correct output of the task satisfies for every valid input and that state the missing requirement(s). The existing ensures "
    "lines stay exactly as they are: do not repeat or rewrite them. Use only the method's parameters, its return variable(s)%(fn)s. "
    "Do not introduce new functions.")


def flag_strengthen(parts, S, code, asker):
    """no witness could be confirmed, only the flag stands: ask whether the task fixes the output, and if so
    for ADDITIONAL clauses. Same conjunctive rule as the witness path. (verdict, clauses, info)"""
    pre = V.pre(parts).strip(); names = sorted(H.declared_names(pre))
    base = FLAG_PROMPT % {"nl": (parts.get("vc-description", "") or "").strip()[:1500],
                          "pre": ("Declarations available to the specification:" + NL + pre[:3000] + NL + NL) if pre else "",
                          "head": O.head(parts), "spec": S,
                          "fn": (" and the functions already declared for this task (%s)" % ", ".join(names[:12])) if names else ""}
    r = asker.ask(base)
    if not r.strip():
        return "API-FAIL", [], {}
    lines = [l.strip() for l in r.strip().split(NL) if l.strip()]
    first = re.sub(r"[^A-Z]", "", lines[0].upper()) if lines else ""
    up = r.upper()
    if first.startswith("UNINTENDED"):
        verdict = "UNINTENDED"
    elif first.startswith("INTENDED"):
        verdict = "INTENDED"
    elif first.startswith("COMPLETE"):
        verdict = "COMPLETE"
    else:
        verdict = "UNINTENDED" if "UNINTENDED" in up else ("COMPLETE" if "COMPLETE" in up else ("INTENDED" if "INTENDED" in up else "UNCLEAR"))
    info = {"clause_tries": 0}
    if verdict != "UNINTENDED":
        return verdict, [], info
    for t in range(CLAUSE_TRIES):
        info["clause_tries"] = t + 1
        cand = extract_clauses(r, S)
        C, err = well_formed_clauses(parts, S, cand)
        if C:
            return verdict, C, info
        if t == CLAUSE_TRIES - 1:
            break
        why = ("it contained no additional ensures line" if not cand else "the additional ensures lines are not valid Dafny in this method (%s)" % err)
        r = asker.ask(base + NL + NL + "Your previous answer:" + NL + r.strip()[:1200] + NL + NL + "It was rejected: " + why + "." + NL +
                      "Answer again in the same format (line 1 UNINTENDED, then the ```dafny block with corrected ADDITIONAL ensures lines only).")
        if not r.strip():
            break
    return verdict, [], info


FORCE_PROMPT = (
    "A Dafny method has to implement this task:" + NL + "%(nl)s" + NL + NL +
    "%(pre)s"
    "Signature and precondition:" + NL + "%(head)s" + NL + NL +
    "Its current postcondition:" + NL + "    %(spec)s" + NL + NL +
    "A solver was asked to prove that this postcondition admits at most one output for every valid input, and it could NOT. "
    "So either the postcondition leaves something open, or it pins the output down only in a way the solver cannot follow." + NL +
    "If the task description itself leaves the choice open (several different outputs are acceptable), answer with the single "
    "word INTENDED." + NL +
    "Otherwise write, in a ```dafny block, ADDITIONAL postcondition lines (each starting with `ensures`) that every correct output "
    "satisfies and that make the unique output explicit: state directly what is still open (for example the exact length, the "
    "value of every element, which index is returned when several qualify, the order of the elements). The existing ensures lines "
    "stay exactly as they are: do not repeat or rewrite them. Use only the method's parameters, its return variable(s)%(fn)s. "
    "Do not introduce new functions.")


def force_det(parts, S, code, asker):
    """the model called the postcondition complete, the solver could not prove uniqueness: the SOLVER decides.
    Additional clauses are accepted only if, with them, uniqueness of the output is proved. (verdict, C, info)"""
    pre = V.pre(parts).strip(); names = sorted(H.declared_names(pre))
    base = FORCE_PROMPT % {"nl": (parts.get("vc-description", "") or "").strip()[:1500],
                           "pre": ("Declarations available to the specification:" + NL + pre[:3000] + NL + NL) if pre else "",
                           "head": O.head(parts), "spec": S,
                           "fn": (" and the functions already declared for this task (%s)" % ", ".join(names[:12])) if names else ""}
    r = asker.ask(base)
    if not r.strip():
        return "API-FAIL", [], {}
    info = {"clause_tries": 0}
    for t in range(CLAUSE_TRIES):
        lines = [l.strip() for l in r.strip().split(NL) if l.strip()]
        first = re.sub(r"[^A-Z]", "", lines[0].upper()) if lines else ""
        if first.startswith("INTENDED") and "ensures" not in r:
            return "INTENDED", [], info
        info["clause_tries"] = t + 1
        cand = extract_clauses(r, S)
        C, err = well_formed_clauses(parts, S, cand)
        if C:
            d, _, _ = O.det2(parts, join_spec(S, C), code)
            info["det_with_clauses"] = d
            if d == 1.0:
                return "UNINTENDED", C, info
            why = "with these lines added the solver still cannot prove that the output is unique"
        else:
            why = ("it contained no additional ensures line" if not cand else "the additional ensures lines are not valid Dafny in this method (%s)" % err)
        if t == CLAUSE_TRIES - 1:
            break
        r = asker.ask(base + NL + NL + "Your previous answer:" + NL + r.strip()[:1200] + NL + NL + "It was rejected: " + why + "." + NL +
                      "Answer again: a ```dafny block with corrected ADDITIONAL ensures lines only, or the single word INTENDED.")
        if not r.strip():
            break
    return "UNINTENDED", [], info


FLAGPATH = os.environ.get("FLAGPATH", "1") == "1"


def witness_arm2(parts, S0, code0, asker, rounds=ROUNDS, flag_first=False, force_first=False):
    sg = O.sig_all(parts); name = sg[0]; head = O.head(parts)
    S, code = S0, code0; hist = []; benign = False; stop = "rounds"
    for rnd in range(rounds):
        if rnd > 0:
            d, _, _ = O.det2(parts, S, code)
            if d == 1.0:
                stop = "determinate"; break
        log = []; wit = None
        if force_first and rnd == 0:
            verdict, C, info = force_det(parts, S, code, asker)
            h = {"round": 1, "witness": None, "wlog": [], "path": "force", "verdict": verdict, "info": info}
            hist.append(h)
            if verdict == "API-FAIL":
                stop = "api-fail"; break
            if verdict == "INTENDED":
                benign = True; stop = "benign-flag"; break
            if not C:
                stop = "no-proof"; break
            S2 = join_spec(S, C)
            c2, how = recode(parts, head, name, S2, code, asker)
            h.update({"added": C, "code": how, "code_reverified": c2 is not None})
            if c2 is None:
                stop = "code-failed"; break
            S, code = S2, c2
            continue
        if not (flag_first and rnd == 0):
            wit = find_witness2(parts, S, code, asker, log)
        h = {"round": rnd + 1, "witness": wit, "wlog": log}
        hist.append(h)
        if wit:
            verdict, correct, C, info = arbiter(parts, S, code, wit, asker)
            h.update({"path": "witness", "verdict": verdict, "correct": correct, "info": info})
            if verdict == "API-FAIL":
                stop = "api-fail"; break
            if verdict != "UNINTENDED":
                benign = verdict == "INTENDED"; stop = "benign" if benign else "unclear"; break
        else:
            if "api-fail" in log:
                stop = "api-fail"; break
            if not FLAGPATH:
                stop = "no-witness"; break
            verdict, C, info = flag_strengthen(parts, S, code, asker)
            h.update({"path": "flag", "verdict": verdict, "info": info})
            if verdict == "API-FAIL":
                stop = "api-fail"; break
            if verdict == "INTENDED":
                benign = True; stop = "benign-flag"; break
            if verdict != "UNINTENDED":
                stop = "complete" if verdict == "COMPLETE" else "unclear"; break
        if not C:
            stop = "no-clause"; break
        S2 = join_spec(S, C)
        c2, how = recode(parts, head, name, S2, code, asker)
        h.update({"added": C, "code": how, "code_reverified": c2 is not None})
        if c2 is None:
            stop = "code-failed"; break            # keep the previous accepted state
        S, code = S2, c2
    return {"final_spec": S, "final_code": code, "changed": H.nows(S) != H.nows(S0), "benign_nondet": benign, "stop": stop,
            "n_rounds": len(hist), "activated": any(h.get("witness") for h in hist), "history": hist}


def _jsonl(path):
    out = []
    if os.path.exists(path):
        for l in open(path):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


if __name__ == "__main__":
    import fix_state
    MODEL = os.environ["MODEL"]
    OUT = os.environ.get("OUT", "/tmp/wit2_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_"))
    CAP = float(os.environ.get("CAP", "60")); LIMIT = int(os.environ.get("LIMIT", "0")); ONLY = os.environ.get("ONLY", "")
    import fix_state5
    S = fix_state5.load5([MODEL])
    # resumable by (key, specification): a task whose state was replaced by a later stage is processed again
    prev = {}
    for r in _jsonl(OUT):
        if r.get("stop") != "api-fail":
            prev[(r["model"], r["source"], r["task"], H.nows(r.get("spec_before")))] = r
    PASS2 = os.environ.get("PASS2", "") == "1"      # second pass: flag path for the tasks the first pass left at "no-witness"
    PASS3 = os.environ.get("PASS3", "") == "1"      # third pass: the model said "complete", the solver decides
    # extended budget (2026-11-19): the accepts that the standard budget left UNCHANGED because it ran out (no code
    # under the stronger specification within ITERS attempts, no usable clause within CLAUSE_TRIES, no witness, rounds)
    # are run again from the same state, in the same mode, with the larger ITERS / CLAUSE_TRIES of this call.
    # Reads the standard-budget records from PREV_FROM and writes to its own OUT, so both budgets stay reportable.
    PASS4 = os.environ.get("PASS4", "") == "1"
    RETRY = ("code-failed", "no-proof", "no-clause", "no-witness", "rounds")
    std = {}
    if PASS4:
        for r in _jsonl(os.environ.get("PREV_FROM", "/tmp/wit2_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_"))):
            if r.get("stop") != "api-fail":
                std[(r["model"], r["source"], r["task"], H.nows(r.get("spec_before")))] = r
    tg = []
    for k, v in S.items():
        if not (v["accepted"] and v["det"] == 0.0 and v["rel"] is not None):
            continue
        if ONLY == "weak" and v["rel"] is not False:
            continue
        if ONLY == "good" and v["rel"] is not True:
            continue
        p = prev.get((k[0], k[1], k[2], H.nows(v["spec"])))
        if PASS4:
            q = std.get((k[0], k[1], k[2], H.nows(v["spec"])))
            if p is None and q is not None and q.get("stop") in RETRY and not q.get("changed"):
                tg.append(k)
        elif PASS3:
            if p is not None and p.get("stop") == "complete" and not p.get("changed"):
                tg.append(k)
        elif (p is None and not PASS2) or (PASS2 and p is not None and p.get("stop") == "no-witness"):
            tg.append(k)
    done = prev
    random.Random(11).shuffle(tg)
    if LIMIT:
        tg = tg[:LIMIT]
    print("%s targets: %d (already done %d) cap $%.0f" % (MODEL, len(tg), len(done), CAP), flush=True)
    if os.environ.get("DRY") == "1":
        print("   by previous stop:", dict(collections.Counter((std.get((k[0], k[1], k[2], H.nows(S[k]["spec"]))) or {}).get("stop") for k in tg)),
              "| weak %d good %d" % (sum(1 for k in tg if S[k]["rel"] is False), sum(1 for k in tg if S[k]["rel"] is True)), flush=True)
        raise SystemExit(0)
    lock = threading.Lock(); fo = open(OUT, "a"); st = collections.Counter(); spent = [0.0]

    def work(k):
        if spent[0] > CAP:
            with lock:
                st["skipped-cap"] += 1
            return
        v = S[k]; s = {"rel": v["rel"], "det": v["det"]}
        o = {"model": k[0], "source": k[1], "task": k[2], "rel_before": s["rel"], "spec_before": v["spec"], "origin": v["origin"]}
        asker = H.Asker(MODEL)
        try:
            parts = H.task_parts(k[1], k[2])
            if O.modifies_text(parts).strip() or not (O.sig_all(parts) or (0, 0, []))[2]:
                o.update({"stop": "unsupported", "changed": False, "activated": False, "n_rounds": 0, "history": []})
                o["rel_after"] = s["rel"]; o["det_after"] = s["det"]
            else:
                p = prev.get((k[0], k[1], k[2], H.nows(v["spec"])))
                if PASS4:
                    q = std[(k[0], k[1], k[2], H.nows(v["spec"]))]
                    o.update(witness_arm2(parts, v["spec"], v["code"], asker, flag_first=(q.get("pass") == 2), force_first=(q.get("pass") == 3)))
                    o["pass"] = 4; o["mode_of_pass"] = q.get("pass", 1); o["prev_stop"] = q.get("stop")
                    o["budget"] = {"iters": ITERS, "clause_tries": CLAUSE_TRIES, "rounds": ROUNDS}
                    o["prev_usd"] = round((q.get("cost") or {}).get("cost_usd", 0) + q.get("prev_usd", 0), 4)
                    o["prev_calls"] = (q.get("cost") or {}).get("calls", 0) + q.get("prev_calls", 0)
                    o["prev_activated"] = bool(q.get("activated") or q.get("prev_activated"))
                else:
                    o.update(witness_arm2(parts, v["spec"], v["code"], asker, flag_first=PASS2, force_first=PASS3))
                if (PASS2 or PASS3) and p is not None:
                    o["pass"] = 3 if PASS3 else 2
                    o["prev_usd"] = round((p.get("cost") or {}).get("cost_usd", 0) + p.get("prev_usd", 0), 4)
                    o["prev_calls"] = (p.get("cost") or {}).get("calls", 0) + p.get("prev_calls", 0)
                    o["prev_stop"] = p.get("stop"); o["prev_activated"] = bool(p.get("activated") or p.get("prev_activated"))
                if o["changed"]:
                    ra, rc, _ = O.rel2(parts, o["final_spec"], o["final_code"])
                    da, dc, _ = O.det2(parts, o["final_spec"], o["final_code"])
                    o.update({"rel_after": ra, "rel_after_cls": rc, "det_after": da})
                else:
                    o["rel_after"] = s["rel"]; o["det_after"] = s["det"]
        except Exception as e:
            o["error"] = str(e)[:300]; o.setdefault("stop", "error")
        o["cost"] = asker.summ()
        with lock:
            spent[0] += o["cost"].get("cost_usd", 0)
            fo.write(json.dumps(o) + NL); fo.flush()
            st["n"] += 1; st["act"] += bool(o.get("activated")); st["chg"] += bool(o.get("changed"))
            st["fixed"] += (o.get("rel_before") is False and o.get("rel_after") is True)
            st["broke"] += (o.get("rel_before") is True and o.get("rel_after") is not True)
            st["stop:" + str(o.get("stop"))] += 1
            print("  %-34s %-11s rel %s->%s calls %d $%.3f | n %d/%d act %d chg %d FIXED %d BROKE %d spent $%.2f" % (
                k[2][:34], str(o.get("stop")), o.get("rel_before"), o.get("rel_after"), o["cost"]["calls"], o["cost"].get("cost_usd", 0),
                st["n"], len(tg), st["act"], st["chg"], st["fixed"], st["broke"], spent[0]), flush=True)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "8"))) as ex:
        list(ex.map(work, tg))
    print("DONE %s %s spent $%.2f" % (MODEL, dict(st), spent[0]), flush=True)
