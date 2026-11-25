"""MBPP-DFY scoring v2 (2026-11-19, night): every accepted program gets a verdict, nothing is left "not assessable".
Same rule for every pipeline and model. No model calls.

What v1 (mbpp_rescore.py) left open, and what v2 does about it:
 1. Reference method. A reference file may hold a helper method before the task's method (task_id_784:
    FirstEvenOddIndices, then ProductEvenOdd). v1 compared against the first one. v2 takes the task's MAIN method:
    the method with a result that no other method of the file calls (the last one if several).
 2. Contract context. v1 put both programs in full into the comparison file; if anything in a file did not resolve
    (the reference of task_id_566 holds an unused ghost function that names a local variable of a method body), the
    comparison could not be built. v2 retries such a comparison with the contracts' context only: the functions and
    predicates the requires/ensures refer to, transitively, plus types and constants; everything else left out.
 3. Interface mapping between the program and the reference contract.
      inputs : same type; nat/int (Dafny turns the difference into a proof obligation); array<T> / seq<T>;
               array<array<T>> / seq<seq<T>>; a program that takes real (or a wider bit-vector) where the
               reference takes int (or a narrower one) accepts more, its inputs are converted
      results: same type, nat/int, array/seq, an int result where the reference has real (compared as real);
               in another order (matched by type, then by name); extra results of the program (e.g. a `found`
               flag) that the reference does not have; one sequence of k elements where the reference has k
               results of the element type
 4. Verdicts. correct     : Pre and Ent proved (below)
              not-shown   : the comparison is built but not proved (the contract does not imply the reference)
              interface   : the program does not implement the task's interface: it accepts only part of the
                            task's inputs (integers where the task takes real numbers, 8-bit where it takes 32-bit
                            values) or takes other inputs or gives other results than can be mapped. It does not
                            solve the task as stated, so it is NOT correct.
              unresolved  : the comparison could not be built although the interfaces map: a measurement gap,
                            reported separately (expected to be zero)
    Pre : RefReq(in) ==> GenReq(in)                                       the program may not assume more
    Ent : RefReq(in) && GenReq(in) && GenEns(in, out) ==> RefEns(in, out)
    Only the two lemmas are verified (--filter-symbol), strict rule: an unfinished proof is not a proof.
 5. Tests: the dataset's own test cases, executed, for information only (used when the reference passes them).
Env: FILES = "name=glob[;glob...],..." (a later glob overrides an earlier one task by task), WORKERS, OUTJ, OUTS.
A pipeline named "x@model" is paired with "baseline@model"."""
import os, sys, re, json, glob, signal, tempfile, subprocess, collections, itertools
from math import comb
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import vericode_compete as V
import fix_harness as H
import fix_hdr as HDR
import fix_oracle as O

NL = chr(10)
D = os.path.expanduser("~/clover/dataset/MBPP-DFY-153")
db = json.load(open(glob.glob(D + "/*.json")[0]))
FILES = [x.split("=", 1) for x in os.environ.get(
    "FILES", "baseline@haiku-4-5=/tmp/mbpp_repro_haiku.jsonl,ours@haiku-4-5=/tmp/mbpp_boost_full2.jsonl").split(",") if x.strip()]
W = int(os.environ.get("WORKERS", "32"))
OUTJ = os.environ.get("OUTJ", "/tmp/mbpp_rescore2.jsonl")
OUTS = os.environ.get("OUTS", "/tmp/mbpp_rescore2_summary.json")
MRE = re.compile(r"(?m)^[ \t]*(?:ghost[ \t]+)?method\b[ \t]*(?:\{:[^}]*\}[ \t]*)*(\w+)")
BYPASS = re.compile(r"\bassume\b|\{:axiom\}|\{:verify\s+false\}|\{:extern")
DECL = re.compile(r"(?m)^[ \t]*((?:ghost|static|opaque|abstract|twostate|least|greatest|inductive)[ \t]+)*"
                  r"(method|function|predicate|lemma|datatype|codatatype|type|newtype|const|class|trait|iterator|include|import)\b")
KEEP = {"function", "predicate", "datatype", "codatatype", "type", "newtype", "const", "class", "trait"}
I = lambda v: v


def jl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def run(args, src, timeout):
    with tempfile.NamedTemporaryFile("w", suffix=".dfy", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        pr = subprocess.Popen([V.DAFNY] + args + [p], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            o, _ = pr.communicate(timeout=timeout)
            return o
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pr.pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                pr.communicate(timeout=10)
            except Exception:
                pass
            return None
    finally:
        try:
            os.unlink(p)
        except Exception:
            pass


def first_error(o):
    for ln in (o or "").split(NL):
        if "Error" in ln:
            return re.sub(r"^.*?\.dfy", "", ln)[:220]
    return (o or "")[-200:]


def prove(src, symbol):
    """'proved' | 'failed' | 'timeout' | 'noresolve', detail. Only the named lemma is verified."""
    o = run(["verify", "--filter-symbol", symbol], src, 150)
    if o is None:
        return "timeout", ""
    if "resolution/type errors" in o or "parse errors" in o:
        return "noresolve", first_error(o)
    unfinished = bool(re.search(r"[1-9]\d* (?:time ?outs?|out of resource|inconclusive)", o)) or "timed out" in o
    ok = bool(re.search(r"(?<!\d)0 errors", o)) and bool(re.search(r"[1-9]\d* verified", o)) and not unfinished
    if ok:
        return "proved", ""
    if unfinished:
        return "timeout", ""
    return "failed", first_error(o)


def nocomment(s):
    s = re.sub(r"/\*.*?\*/", " ", s or "", flags=re.S)
    return re.sub(r"//[^" + NL + r"]*", "", s)


def chunks(code):
    """top-level declarations: [(kind, name, text)] (brace depth 0, comments removed)"""
    code = nocomment(code)
    starts = []
    for m in DECL.finditer(code):
        pre = code[:m.start()]
        if pre.count("{") - pre.count("}") == 0:
            starts.append((m.start(), m.group(2)))
    out = []
    for i, (s, kind) in enumerate(starts):
        e = starts[i + 1][0] if i + 1 < len(starts) else len(code)
        txt = code[s:e]
        mm = re.match(r"\s*(?:\w+\s+)*?(?:method|function|predicate|lemma|datatype|codatatype|type|newtype|const|class|trait)\s+(?:\{:[^}]*\}\s*)*(\w+)", txt)
        out.append((kind, mm.group(1) if mm else "", txt))
    return out


def contract_only(code):
    return NL.join(t.rstrip() for k, n, t in chunks(code) if k in KEEP) + NL


def closure(code, h):
    """the contract's context: the declarations the header's requires/ensures refer to, transitively (types and
    constants always). Unused declarations are left out: the reference of task_id_566 holds a ghost function that
    nothing uses and that does not resolve (it names a local variable of the method body)."""
    cs = [(k, n, t) for k, n, t in chunks(code) if k in KEEP or k == "lemma"]
    names = set(re.findall(r"[A-Za-z_]\w*", " ".join(h["requires"] + h["ensures"])))
    keep = set(); changed = True
    while changed:
        changed = False
        for i, (k, n, t) in enumerate(cs):
            if i in keep:
                continue
            if k in ("datatype", "codatatype", "type", "newtype", "const", "class", "trait") or n in names:
                keep.add(i); changed = True
                names |= set(re.findall(r"[A-Za-z_]\w*", t))
    return NL.join(cs[i][2].rstrip() for i in sorted(keep)) + NL


def methods_with_result(code):
    out = []
    for m in MRE.finditer(code):
        h = HDR.parse(code[m.start():])
        if h and h["rets"] and m.group(1) != "Main":
            out.append((m.start(), h))
    return out


def main_method(code, want=None):
    """the task's method: named like `want` if given and present; else a method with a result that no other method
    of the file calls (the last such one); else the last method with a result"""
    hs = methods_with_result(code)
    if not hs:
        return None
    if want:
        for pos, h in hs:
            if h["name"].lower() == want.lower():
                return h
    cs = chunks(code)
    roots = []
    for pos, h in hs:
        called = any(re.search(r"\b%s\s*\(" % re.escape(h["name"]), t) for k, n, t in cs if n != h["name"] and k in ("method", "lemma"))
        if not called:
            roots.append(h)
    return (roots or [h for _, h in hs])[-1]


def norm(t):
    return re.sub(r"\s+", "", t or "").replace("string", "seq<char>")


def elem(t, kind):
    n = norm(t)
    return n[len(kind) + 1:-1] if n.startswith(kind + "<") and n.endswith(">") else None


def bvw(t):
    m = re.fullmatch(r"bv(\d+)", norm(t) or "")
    return int(m.group(1)) if m else None


NUMS = {"nat", "int"}
NESTED = "seq(%(v)s.Length, i_n requires 0 <= i_n < %(v)s.Length reads %(v)s, (set j_n | 0 <= j_n < %(v)s.Length :: %(v)s[j_n]) => %(v)s[i_n][..])"


def narrower(rt, gt):
    """does a program parameter of type gt accept only part of the values of a reference parameter of type rt?"""
    nr, ng = norm(rt), norm(gt)
    if nr == "real" and ng in NUMS:
        return True
    if bvw(nr) and bvw(ng) and bvw(ng) < bvw(nr):
        return True
    for kind in ("seq", "array", "set", "multiset"):
        er, eg = elem(nr, kind), elem(ng, kind)
        if er and eg and narrower(er, eg):
            return True
    if elem(nr, "seq") and elem(ng, "array") and narrower(elem(nr, "seq"), elem(ng, "array")):
        return True
    if elem(nr, "array") and elem(ng, "seq") and narrower(elem(nr, "array"), elem(ng, "seq")):
        return True
    return False


def conv_in(rt, gt, generic=False):
    """a reference input of type rt handed to a program parameter of type gt:
    {decl: type of the lemma variable, g: expression for the program, r: expression for the reference} or None"""
    nr, ng = norm(rt), norm(gt)
    if nr == ng or {nr, ng} <= NUMS or generic:
        return {"decl": rt, "g": I, "r": I}
    er, eg = elem(rt, "seq"), elem(gt, "array")
    if er is not None and er == eg:
        return {"decl": gt, "g": I, "r": lambda v: v + "[..]"}
    er, eg = elem(rt, "array"), elem(gt, "seq")
    if er is not None and er == eg:
        return {"decl": rt, "g": lambda v: v + "[..]", "r": I}
    er, eg = elem(rt, "seq"), elem(gt, "array")
    if er is not None and eg is not None and elem(er, "seq") is not None and elem(er, "seq") == elem(eg, "array"):
        return {"decl": gt, "g": I, "r": lambda v: NESTED % {"v": v}}
    if nr in NUMS and ng == "real":
        return {"decl": rt, "g": lambda v: "(%s as real)" % v, "r": I}
    if bvw(nr) and bvw(ng) and bvw(ng) > bvw(nr):
        return {"decl": rt, "g": lambda v, w=bvw(ng): "(%s as bv%d)" % (v, w), "r": I}
    return None


def conv_out(rt, gt, generic=False):
    """a program result of type gt read as a reference result of type rt"""
    nr, ng = norm(rt), norm(gt)
    if generic:
        return {"decl": rt, "g": I, "r": I}
    if nr == ng or {nr, ng} <= NUMS:
        return {"decl": gt, "g": I, "r": I}
    er, eg = elem(rt, "seq"), elem(gt, "array")
    if er is not None and er == eg:
        return {"decl": gt, "g": I, "r": lambda v: v + "[..]"}
    er, eg = elem(rt, "array"), elem(gt, "seq")
    if er is not None and er == eg:
        return {"decl": rt, "g": lambda v: v + "[..]", "r": I}
    if nr == "real" and ng in NUMS:
        return {"decl": gt, "g": I, "r": lambda v: "(%s as real)" % v}
    if bvw(nr) and bvw(ng) and bvw(ng) < bvw(nr):
        return {"decl": gt, "g": I, "r": lambda v, w=bvw(nr): "(%s as bv%d)" % (v, w)}
    return None


def typeparams(h):
    return set(re.findall(r"[A-Za-z_]\w*", h.get("generic") or ""))


def uses(t, tps):
    return bool(tps) and bool(set(re.findall(r"[A-Za-z_]\w*", t)) & tps)


def interface(rh, gh):
    """('ok', mapping) or ('interface', reason)"""
    tps = typeparams(gh)
    if len(rh["params"]) != len(gh["params"]):
        return "interface", "takes %d inputs, the task %d" % (len(gh["params"]), len(rh["params"]))
    ins = []
    for (rn, rt), (gn, gt) in zip(rh["params"], gh["params"]):
        if narrower(rt, gt):
            return "interface", "accepts only part of the task's inputs (%s where the task takes %s)" % (gt, rt)
        c = conv_in(rt, gt, uses(gt, tps))
        if c is None:
            return "interface", "takes other inputs (%s where the task takes %s)" % (gt, rt)
        ins.append(c)
    R, G = rh["rets"], gh["rets"]
    if len(R) <= len(G):
        best = None
        for perm in itertools.permutations(range(len(G)), len(R)):
            cs = [conv_out(R[i][1], G[perm[i]][1], uses(G[perm[i]][1], tps)) for i in range(len(R))]
            if all(cs):
                score = (sum(R[i][0].lower() == G[perm[i]][0].lower() for i in range(len(R))), sum(perm[i] == i for i in range(len(R))))
                if best is None or score > best[0]:
                    best = (score, perm, cs)
        if best:
            outs = {best[1][i]: best[2][i] for i in range(len(R))}
            gdecl = [(outs[j]["decl"] if j in outs else G[j][1]) for j in range(len(G))]
            gexpr = [(outs[j]["g"] if j in outs else I) for j in range(len(G))]
            rexpr = [(lambda v, f=best[2][i]: f["r"](v), "y%d" % best[1][i]) for i in range(len(R))]
            return "ok", {"ins": ins, "gdecl": gdecl, "gexpr": gexpr, "rexpr": rexpr, "extra": [], "how": "results %s" % (list(best[1]),)}
        return "interface", "gives other results (%s where the task has %s)" % ([t for _, t in G], [t for _, t in R])
    if len(G) == 1:
        g = G[0][1]
        el = elem(g, "seq") or elem(g, "array")
        if el is not None and all(norm(t) == norm(el) or {norm(t), norm(el)} <= NUMS for _, t in R):
            ln = ("|y0| == %d" if elem(g, "seq") else "y0.Length == %d") % len(R)
            return "ok", {"ins": ins, "gdecl": [g], "gexpr": [I], "rexpr": [(I, "y0[%d]" % i) for i in range(len(R))], "extra": [ln],
                          "how": "one sequence of %d results" % len(R)}
    return "interface", "gives %d results, the task %d" % (len(G), len(R))


def conj(es):
    return ("    " + (" &&" + NL + "    ").join("(%s)" % e for e in es)) if es else "    true"


def preds(tag, h):
    g = h.get("generic", "") or ""
    pin = ", ".join("%s: %s" % p for p in h["params"])
    pall = ", ".join("%s: %s" % p for p in h["params"] + h["rets"])
    names = ", ".join(n for n, _ in h["params"])
    ens = [O.strip_two(e) for e in h["ensures"]]
    s = "  ghost predicate %sReq%s(%s)" % (tag, g, pin) + NL + "    reads *" + NL + "  {" + NL + conj(h["requires"]) + NL + "  }" + NL
    s += "  ghost predicate %sEns%s(%s)" % (tag, g, pall) + NL + "    reads *" + NL + "    requires %sReq(%s)" % (tag, names) + NL
    s += "  {" + NL + conj(ens) + NL + "  }" + NL
    return s


def check_src(gen_ctx, gh, ref_ctx, rh, mp, which):
    g = rh.get("generic", "") or ""
    xs = ["x%d" % k for k in range(len(mp["ins"]))]
    din = ", ".join("%s: %s" % (x, c["decl"]) for x, c in zip(xs, mp["ins"]))
    xg = ", ".join(c["g"](x) for x, c in zip(xs, mp["ins"]))
    xr = ", ".join(c["r"](x) for x, c in zip(xs, mp["ins"]))
    ys = ["y%d" % j for j in range(len(mp["gdecl"]))]
    dout = ", ".join("%s: %s" % (y, t) for y, t in zip(ys, mp["gdecl"]))
    yg = ", ".join(f(y) for y, f in zip(ys, mp["gexpr"]))
    yr = ", ".join(f(v) for f, v in mp["rexpr"])
    s = "module ZzGen {" + NL + gen_ctx + NL + "}" + NL + "module ZzRef {" + NL + ref_ctx + NL + "}" + NL
    s += "module ZzCheckGen {" + NL + "  import opened ZzGen" + NL + preds("Gen", gh) + "}" + NL
    s += "module ZzCheckRef {" + NL + "  import opened ZzRef" + NL + preds("Ref", rh) + "}" + NL
    s += "module ZzCheck {" + NL + "  import CG = ZzCheckGen" + NL + "  import CR = ZzCheckRef" + NL
    if which == "pre":
        s += "  lemma ZzPre%s(%s)" % (g, din) + NL + "    requires CR.RefReq(%s)" % xr + NL + "    ensures CG.GenReq(%s)" % xg + NL + "  {}" + NL
    else:
        s += "  lemma ZzEnt%s(%s)" % (g, ", ".join(x for x in (din, dout) if x)) + NL + "    requires CR.RefReq(%s)" % xr + NL
        s += "    requires CG.GenReq(%s)" % xg + NL + "    requires CG.GenEns(%s)" % ", ".join(x for x in (xg, yg) if x) + NL
        s += "    ensures %s" % " && ".join(mp["extra"] + ["CR.RefEns(%s)" % ", ".join(x for x in (xr, yr) if x)]) + NL + "  {}" + NL
    return s + "}" + NL


def proof_verdict(gen_code, ref_code):
    rh = main_method(ref_code)
    if not rh:
        return {"proof": "unresolved", "why": "no reference method with a result"}
    gh = main_method(gen_code, rh["name"])
    o = {"ref_name": rh["name"], "ref_sig": rh["sig_text"][:200]}
    if not gh:
        o.update({"proof": "interface", "why": "the program has no method with a result"}); return o
    o.update({"gen_name": gh["name"], "gen_sig": gh["sig_text"][:200]})
    if rh["modifies"] or gh["modifies"]:
        o.update({"proof": "unresolved", "why": "in-place method (two-state contract)"}); return o
    st, mp = interface(rh, gh)
    if st == "interface":
        o.update({"proof": "interface", "why": mp}); return o
    o["mapping"] = mp["how"]
    if not gh["ensures"]:
        o.update({"proof": "not-shown", "why": "the program states no postcondition"}); return o
    for ctx in ("full", "closure"):
        gc, rc = (gen_code, ref_code) if ctx == "full" else (closure(gen_code, gh), closure(ref_code, rh))
        pre, pd = prove(check_src(gc, gh, rc, rh, mp, "pre"), "ZzCheck.ZzPre")
        if pre == "noresolve":
            o["noresolve_" + ctx] = pd; continue
        ent, ed = prove(check_src(gc, gh, rc, rh, mp, "ent"), "ZzCheck.ZzEnt")
        if ent == "noresolve":
            o["noresolve_" + ctx] = ed; continue
        o.update({"context": ctx, "pre": pre, "ent": ent})
        if pre == "proved" and ent == "proved":
            o["proof"] = "correct"
        else:
            o["proof"] = "not-shown"
            o["why"] = ("precondition stronger than the reference's (%s)" % pre) if pre != "proved" and ent == "proved" else (
                "entailment %s%s" % (ent, "" if pre == "proved" else ", precondition %s" % pre))
            o["detail"] = (ed or pd)[:200]
        return o
    o.update({"proof": "unresolved", "why": "the comparison does not resolve: " + (o.get("noresolve_closure") or o.get("noresolve_full") or "")[:160]})
    return o


def tests_verdict(code, name, t):
    tests = t.get("test_cases") or {}
    if not isinstance(tests, dict) or not tests:
        return "no-tests"
    dm = re.search(r"method\s+(\w+)", t.get("method_signature") or "")
    body = NL.join("  { %s }" % x.replace("assert ", "expect ").replace(NL, " ") for x in list(tests.values())[:3])
    if dm and name and dm.group(1) != name:
        body = re.sub(r"\b%s\b" % re.escape(dm.group(1)), name, body)
    prog = re.sub(r"\bmethod\s+Main\s*\(", "method Main_orig_(", code)
    o = run(["run", "--target:py", "--no-verify"], prog + NL + "method Main() {" + NL + body + NL + "}" + NL, 150)
    if o is None:
        return "timeout"
    if "resolution/type errors" in o or "parse errors" in o:
        return "norun"
    if "expectation violation" in o:
        return "fail"
    if "Traceback" in o or "Error" in o:
        return "crash"
    return "pass"


REF = {}
for tid in db:
    f = D + "/src/task_id_%s.dfy" % tid
    if os.path.exists(f):
        REF["task_id_" + tid] = open(f).read()


def ref_job(task):
    code = REF[task]; rh = main_method(code)
    return task, {"ref_tests": tests_verdict(code, rh["name"] if rh else None, db[task.replace("task_id_", "")]), "ref_name": rh["name"] if rh else None}


def job(x):
    pipe, r = x
    task = r["task"]; t = db.get(task.replace("task_id_", ""), {})
    code = r.get("code") or ((r.get("attempts") or [{}])[-1].get("code")) or ""
    o = {"pipeline": pipe, "task": task, "old_rel": r.get("reliable_gt")}
    try:
        ok, out = H.dverify2(code, 90)
        o["strict"] = bool(ok); o["bypass"] = bool(BYPASS.search(nocomment(code)))
        if not ok or o["bypass"]:
            return o
        ref = REF.get(task)
        if ref is None:
            o["proof"] = "unresolved"; o["why"] = "no reference file"; return o
        o.update(proof_verdict(code, ref))
        o["tests"] = tests_verdict(code, o.get("gen_name"), t)
    except Exception as e:
        o["error"] = str(e)[:200]; o["proof"] = "unresolved"; o["why"] = "scorer error"
    return o


def records(spec):
    """a pipeline's records from ';'-separated globs, deduplicated by task: a later file overrides an earlier one"""
    d = {}
    for pat in spec.split(";"):
        for g in sorted(glob.glob(pat.strip())):
            for r in jl(g):
                if "task" in r:
                    d[r["task"]] = r
    return list(d.values())


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=W) as ex:
        refinfo = dict(ex.map(ref_job, sorted(REF)))
    print("reference programs: %d | their own tests: %s | main methods that are not the first method: %s" % (
        len(REF), dict(collections.Counter(v["ref_tests"] for v in refinfo.values())),
        sorted(t for t in REF if (methods_with_result(REF[t]) or [(0, {"name": None})])[0][1]["name"] != refinfo[t]["ref_name"])), flush=True)
    jobs = []; RUNINFO = {}
    for pipe, spec in FILES:
        ALLR = records(spec)
        R = [r for r in ALLR if r.get("status") == "accepted"]
        RUNINFO[pipe] = {"records": len(ALLR), "status": dict(collections.Counter(str(r.get("status")) for r in ALLR)),
                         "calls": sum((r.get("cost") or {}).get("calls", 0) for r in ALLR),
                         "tok_in": sum((r.get("cost") or {}).get("tok_in", 0) for r in ALLR),
                         "tok_out": sum((r.get("cost") or {}).get("tok_out", 0) for r in ALLR)}
        print("%-26s records %3d %s" % (pipe, len(ALLR), RUNINFO[pipe]["status"]), flush=True)
        jobs += [(pipe, r) for r in R]
    with ThreadPoolExecutor(max_workers=W) as ex:
        rows = list(ex.map(job, jobs))
    for o in rows:
        o["ref_tests"] = refinfo.get(o["task"], {}).get("ref_tests")
    with open(OUTJ, "w") as f:
        for o in rows:
            f.write(json.dumps(o) + NL)
    summ = {"runs": RUNINFO}
    for pipe, _ in FILES:
        L = [o for o in rows if o["pipeline"] == pipe]
        S = [o for o in L if o.get("strict") and not o.get("bypass")]
        pc = collections.Counter(o.get("proof") for o in S)
        tv = [o for o in S if o.get("ref_tests") == "pass"]
        summ[pipe] = {"records": RUNINFO[pipe]["records"], "accepted_records": len(L), "strict": sum(1 for o in L if o.get("strict")),
                      "bypass": sum(1 for o in L if o.get("strict") and o.get("bypass")), "accepted": len(S), "proof": dict(pc),
                      "tests_on_valid": dict(collections.Counter(o.get("tests") for o in tv)), "n_test_valid": len(tv),
                      "contract_context": sum(1 for o in S if o.get("context") == "closure"),
                      "mapped": dict(collections.Counter(o.get("mapping") for o in S if o.get("mapping") and o.get("mapping") != "results [0]"))}
        print("== %-24s accepted %3d (records %d, not strict %d, bypass %d) | %s | tests %s" % (
            pipe, len(S), RUNINFO[pipe]["records"], len(L) - summ[pipe]["strict"], summ[pipe]["bypass"], dict(pc), summ[pipe]["tests_on_valid"]), flush=True)
        for k, v in collections.Counter((o.get("proof"), (o.get("why") or "")[:70]) for o in S if o.get("proof") in ("interface", "unresolved")).most_common(12):
            print("      %-10s %3d  %s" % (k[0], v, k[1]))
    P = {p: set(o["task"] for o in rows if o["pipeline"] == p and o.get("strict") and not o.get("bypass") and o.get("proof") == "correct") for p, _ in FILES}
    for p in P:
        if p.startswith("baseline"):
            continue
        base = "baseline" + (p[p.index("@"):] if "@" in p else "")
        if base not in P:
            continue
        a, b = len(P[p] - P[base]), len(P[base] - P[p]); n = a + b
        pv = min(1.0, 2.0 * sum(comb(n, k) for k in range(0, min(a, b) + 1)) / (2.0 ** n)) if n else 1.0
        summ["paired_" + p] = {"ours_only": a, "baseline_only": b, "p": pv, "ours": len(P[p]), "baseline": len(P[base])}
        print("paired: %-22s %3d | %-22s %3d | only ours %d, only baseline %d | McNemar exact p = %.4f" % (p, len(P[p]), base, len(P[base]), a, b, pv), flush=True)
    json.dump(summ, open(OUTS, "w"), indent=1)
    print("DONE", flush=True)
