"""Are the GIVEN specifications of the published benchmarks complete? A reference-free, mechanical audit.

For every task of a given-spec Dafny benchmark the benchmark's own postcondition G is put through four checks.
No model call, no reference solution, strict verifier (an unfinished proof is not a proof).
  D  determinate    : G admits at most one output per input (uniqueness lemma proved)
  A  unconstrained  : if G accepts one output it accepts EVERY output of the type (lemma proved)
  B  shape only     : if G accepts one output it accepts every output of the same LENGTH (lemma proved)
  T  trivial program: a body that ignores the task (a constant, an empty or freshly allocated array, or the
                      input handed back) VERIFIES against the benchmark's exact specification under the
                      published acceptance rule (`dafny verify` exits with 0)
A and B are proofs that the specification says nothing about the result (or about its contents). T is a
concrete wrong-by-construction program that the verifier accepts. D is the positive certificate.
The audited method is the one whose body the benchmark asks for (the last method of vc-spec).
Output: /tmp/given_audit.jsonl"""
import os, sys, re, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import vericode_compete as V
import fix_harness as H
import fix_hdr as HDR
import fix_oracle as O
import boot_given as B

NL = chr(10)
SOURCES = [s for s in os.environ.get("SOURCES", "numpy_simple,verina,verified_cogen").split(",") if s]
OUT = os.environ.get("OUT", "/tmp/given_audit.jsonl")


def target_header(vc_spec):
    """header of the LAST method in vc-spec: the one whose body (vc-code) is to be written"""
    pos = [m.start() for m in re.finditer(r"(?m)^\s*method\b", vc_spec or "")]
    return HDR.parse(vc_spec[pos[-1]:]) if pos else None


def sub(e, rets, tag):
    for rv, _ in rets:
        e = re.sub(r"\b%s\b" % re.escape(rv), rv + tag, e)
    return e


def is_arr(t):
    return t.replace(" ", "").startswith("array<")


def is_seq(t):
    t = t.replace(" ", "")
    return t.startswith("seq<") or t == "string"


def eq(rv, rt):
    if is_arr(rt):
        return "(%s_1.Length == %s_2.Length && forall i_d9 :: 0 <= i_d9 < %s_1.Length ==> %s_1[i_d9] == %s_2[i_d9])" % (rv, rv, rv, rv, rv)
    return "(%s_1 == %s_2)" % (rv, rv)


def lemma(parts, h, kind):
    params, rets = h["params"], h["rets"]
    ens = [O.strip_two(e) for e in h["ensures"]]
    decl = ["%s: %s" % p for p in params] + ["%s_1: %s" % r for r in rets] + ["%s_2: %s" % r for r in rets]
    s = "lemma Audit%s(%s)" % (h.get("generic", ""), ", ".join(decl)) + NL
    for r in h["requires"]:
        s += "  requires %s" % r + NL
    for e in ens:
        s += "  requires %s" % sub(e, rets, "_1") + NL
    if kind == "D":
        for e in ens:
            s += "  requires %s" % sub(e, rets, "_2") + NL
        s += "  ensures %s" % " && ".join(eq(rv, rt) for rv, rt in rets) + NL
    else:
        if kind == "B":
            lens = [("%s_2.Length == %s_1.Length" % (rv, rv)) if is_arr(rt) else ("|%s_2| == |%s_1|" % (rv, rv)) for rv, rt in rets if is_arr(rt) or is_seq(rt)]
            if not lens:
                return None
            for l in lens:
                s += "  requires %s" % l + NL
        for e in ens:
            s += "  ensures %s" % sub(e, rets, "_2") + NL
    return V.pre(parts) + NL + s + "{}" + NL


def prove(src):
    if src is None:
        return None
    ok, out = H.dverify2(src, 90)
    if ok:
        return True
    if out != "TIMEOUT" and ("resolution/type errors" in out or "parse errors" in out):
        return None
    return False


def elem_default(t):
    t = t.replace(" ", "")
    return {"int": "0", "nat": "0", "real": "0.0", "bool": "false", "char": "'a'"}.get(t)


def trivial_bodies(h):
    """[(label, statements)] of bodies that ignore the task; single-return methods only"""
    params, rets = h["params"], h["rets"]
    if len(rets) != 1:
        return []
    rv, rt = rets[0]; t = rt.replace(" ", ""); out = []
    if t in ("int", "nat"):
        out += [("constant 0", "%s := 0;" % rv), ("constant 1", "%s := 1;" % rv)]
        if t == "int":
            out.append(("constant -1", "%s := -1;" % rv))
    elif t == "bool":
        out += [("constant false", "%s := false;" % rv), ("constant true", "%s := true;" % rv)]
    elif t == "real":
        out.append(("constant 0.0", "%s := 0.0;" % rv))
    elif t.startswith("seq<") or t == "string":
        out.append(("empty sequence", "%s := [];" % rv))
    elif t.startswith("array<") and not t.startswith("array<array"):
        el = t[6:-1]
        out.append(("empty array", "%s := new %s[0];" % (rv, el)))
        for pn, pt in params:
            if is_arr(pt):
                out.append(("fresh array of the length of %s, contents never set" % pn, "%s := new %s[%s.Length];" % (rv, el, pn)))
            elif pt.replace(" ", "") in ("int", "nat"):
                out.append(("fresh array of length %s, contents never set" % pn, "if %s >= 0 { %s := new %s[%s]; } else { %s := new %s[0]; }" % (pn, rv, el, pn, rv, el)))
    for pn, pt in params:
        if pt.replace(" ", "") == t:
            out.append(("the input %s handed back" % pn, "%s := %s;" % (rv, pn)))
    return out


def audit(job):
    src, f = job; task = os.path.basename(f)
    o = {"source": src, "task": task}
    try:
        parts = V.load(f); vs = parts.get("vc-spec") or ""
        h = target_header(vs)
        if not h or not h["rets"]:
            o["status"] = "no-method-or-no-return"; return o
        if h["modifies"] or O.TWO.search(NL.join(h["ensures"])) and h["modifies"]:
            o["status"] = "in-place"; return o
        if not h["ensures"]:
            o.update({"status": "ok", "n_ens": 0, "D": False, "A": True, "B": None, "T": None, "note": "no postcondition at all"})
            return o
        o.update({"status": "ok", "n_ens": len(h["ensures"]), "method": h["name"], "rets": ["%s: %s" % r for r in h["rets"]],
                  "spec": NL.join("ensures " + e for e in h["ensures"])[:900], "requires": h["requires"][:4]})
        o["D"] = prove(lemma(parts, h, "D"))
        o["A"] = None if o["D"] else prove(lemma(parts, h, "A"))
        o["B"] = None if (o["D"] or o["A"]) else prove(lemma(parts, h, "B"))
        o["T"] = None
        if not o["D"]:
            for lab, st in trivial_bodies(h):
                prog = vs.rstrip() + NL + "{" + NL + "  " + st + NL + "}" + NL
                rc, out = B.rc_verify(V.assemble(parts, prog))
                if rc == 0:
                    o["T"] = lab; o["T_body"] = st; break
    except Exception as e:
        o["status"] = "error"; o["error"] = str(e)[:200]
    return o


if __name__ == "__main__":
    jobs = []
    for s in SOURCES:
        jobs += [(s, f) for f in sorted(glob.glob(V.BENCH + "/%s/yaml/*.yaml" % s))]
    print("tasks: %d" % len(jobs), flush=True)
    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "24"))) as ex:
        res = list(ex.map(audit, jobs))
    with open(OUT, "w") as f:
        for o in res:
            f.write(json.dumps(o) + NL)
    for s in SOURCES:
        L = [o for o in res if o["source"] == s]; ok = [o for o in L if o.get("status") == "ok"]
        c = collections.Counter(o.get("status") for o in L)
        weak = [o for o in ok if o.get("A") or o.get("B") or o.get("T")]
        print("%-15s tasks %3d | audited %3d (%s) | D determinate %3d | A unconstrained %2d | B shape-only %2d | T trivial program verifies %2d | A or B or T: %2d | not determinate, no certificate %3d" % (
            s, len(L), len(ok), dict(c), sum(1 for o in ok if o.get("D")), sum(1 for o in ok if o.get("A")), sum(1 for o in ok if o.get("B")),
            sum(1 for o in ok if o.get("T")), len(weak), sum(1 for o in ok if not o.get("D")) - len(weak)), flush=True)
        for o in weak:
            print("     %-34s %s%s%s | %s" % (o["task"][:34], "A" if o.get("A") else "-", "B" if o.get("B") else "-", "T" if o.get("T") else "-", (o.get("T") or o.get("note") or "")[:70]))
