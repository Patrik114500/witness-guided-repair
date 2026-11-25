"""Concrete check of accepted solutions against the REFERENCE postcondition, by execution. No model calls.

For an accepted solution whose specification S is not proved to imply the reference G, a lemma cannot tell
"S is wrong or weak" from "the prover gave up". Execution can, in one direction: the accepted program is run
on generated inputs that satisfy the task's precondition, and G is evaluated on (input, output).
  * some run violates G  -> a concrete counterexample: the verified program is WRONG for the task
  * every run satisfies G -> consistent with correctness (evidence, not proof)
  * not runnable          -> G or the precondition is not compilable, or the types are not supported
Sanity group: accepts already PROVED to imply the reference must never produce a counterexample.
Output: /tmp/ce_test.jsonl"""
import os, sys, re, json, random, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import vericode_compete as V
import fix_harness as H
import fix_oracle as O
import fix_state5
import wit2 as W2

NL = chr(10); BS = chr(92); DNL = '"' + BS + 'n"'
NIN = int(os.environ.get("NIN", "28"))
S = fix_state5.load5()
refdet = json.load(open("/tmp/ref_det.json"))
cert = set(k for k, d in refdet.items() if d == 1.0)


def lit(t, rnd, mode):
    """a Dafny expression of type t, or None"""
    t = t.replace(" ", "")
    if t == "int":
        return str(rnd.choice([0, 1, 2, 3, 5, 7, -1, -3, 4, 10]))
    if t == "nat":
        return str(rnd.choice([0, 1, 2, 3, 4, 5, 7, 10]))
    if t == "bool":
        return rnd.choice(["true", "false"])
    if t == "real":
        return "%d.%d" % (rnd.choice([0, 1, 2, 3, 5]), rnd.choice([0, 5]))
    if t == "char":
        return "'" + rnd.choice("abcAZ019 x") + "'"
    if t == "string":
        return '"' + "".join(rnd.choice("abcA1 9zb") for _ in range(rnd.choice([0, 1, 2, 3, 5]))) + '"'
    m = re.match(r"seq<(.+)>$", t)
    if m:
        el = m.group(1); n = rnd.choice([0, 1, 2, 3, 4, 5])
        if el in ("int", "nat"):
            vals = int_list(n, rnd, mode, el == "nat")
            return "[" + ", ".join(str(x) for x in vals) + "]" if vals else "[]"
        xs = [lit(el, rnd, mode) for _ in range(n)]
        if any(x is None for x in xs):
            return None
        return "[" + ", ".join(xs) + "]"
    return None


def int_list(n, rnd, mode, nat):
    lo = 0 if nat else -4
    if mode == "sorted":
        return sorted(rnd.randint(lo, 7) for _ in range(n))
    if mode == "strict":
        return sorted(rnd.sample(range(lo, 12), min(n, 12 - lo)))
    if mode == "equal":
        return [rnd.randint(lo, 5)] * n
    if mode == "distinct":
        return rnd.sample(range(lo, 12), min(n, 12 - lo))
    return [rnd.randint(lo, 7) for _ in range(n)]


def decl(pn, pt, rnd, mode):
    t = pt.replace(" ", "")
    m = re.match(r"array<(.+)>$", t)
    if m:
        el = m.group(1); n = rnd.choice([0, 1, 2, 3, 4, 5])
        if el in ("int", "nat"):
            vals = [str(x) for x in int_list(n, rnd, mode, el == "nat")]
        else:
            vals = [lit(el, rnd, mode) for _ in range(n)]
            if any(x is None for x in vals):
                return None
        if not vals:
            return "var %s := new %s[0];" % (pn, el)
        return "var %s := new %s[%d] [%s];" % (pn, el, len(vals), ", ".join(vals))
    e = lit(t, rnd, mode)
    if e is None:
        return None
    return "var %s: %s := %s;" % (pn, pt, e)


def test(k):
    v = S[k]; o = {"model": k[0], "source": k[1], "task": k[2], "rel": v["rel"], "det": v["det"], "status": None}
    try:
        parts = H.task_parts(k[1], k[2]); h = O.hdr(parts)
        if not h or len(h["rets"]) < 1 or h["modifies"]:
            o["status"] = "unsupported"; return o
        g = [O.strip_two(e, hyp=False) for e in h["ensures"]]
        if not g or O.TWO.search(NL.join(g)):
            o["status"] = "unsupported"; return o
        rnd = random.Random(hash((k[1], k[2])) & 0xffffffff)
        blocks = []; shown = {}
        prec = W2.conj(h["requires"]); pred = W2.conj(g)
        outs = ", ".join(rv for rv, _ in h["rets"])
        call = "var %s := %s(%s);" % (outs, h["name"], ", ".join(pn for pn, _ in h["params"]))
        for i in range(NIN):
            mode = ["random", "sorted", "strict", "equal", "distinct", "random", "sorted"][i % 7]
            ds = [decl(pn, pt, rnd, mode) for pn, pt in h["params"]]
            if any(d is None for d in ds):
                o["status"] = "unsupported"; return o
            ins = " ".join(ds); shown[i] = ins
            blocks.append("  {" + NL + "    " + ins + NL + "    if " + prec + " {" + NL + "      " + call + NL + "      var okz9: bool := " + pred + ";" + NL +
                          '      print "T%d=", okz9, ' % i + DNL + ";" + NL + "    } else {" + NL + '      print "T%d=skip", ' % i + DNL + ";" + NL + "    }" + NL + "  }")
        src = V.assemble(parts, v["code"]) + NL + "method Main() {" + NL + NL.join(blocks) + NL + "}" + NL
        out = W2.drun2(src, 150)
        res = dict((int(a), b) for a, b in re.findall(r"T(\d+)=(true|false|skip)", out))
        npass = sum(1 for b in res.values() if b == "true"); nfail = sum(1 for b in res.values() if b == "false")
        if not res:
            o["status"] = "not runnable"; o["why"] = W2._first_err(out)[:140]; return o
        o.update({"n_valid": npass + nfail, "n_pass": npass, "n_fail": nfail})
        if nfail:
            i = sorted(a for a, b in res.items() if b == "false")[0]
            o["status"] = "counterexample"; o["input"] = shown[i]
        elif npass:
            o["status"] = "all pass"
        else:
            o["status"] = "no valid input"
    except Exception as e:
        o["status"] = "error"; o["why"] = str(e)[:140]
    return o


if __name__ == "__main__":
    acc = [k for k, v in S.items() if v["accepted"] and ("%s|%s" % (k[1], k[2])) in cert]
    unres = [k for k in acc if S[k]["rel"] is False]
    proved = [k for k in acc if S[k]["rel"] is True]
    random.Random(5).shuffle(proved)
    jobs = unres + proved[:int(os.environ.get("SANITY", "300"))]
    print("certified-reference accepts: %d | not proved to imply the reference: %d | sanity sample of proved ones: %d" % (len(acc), len(unres), len(jobs) - len(unres)), flush=True)
    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "24"))) as ex:
        res = list(ex.map(test, jobs))
    with open("/tmp/ce_test.jsonl", "w") as f:
        for o in res:
            f.write(json.dumps(o) + NL)
    for name, flt in [("NOT proved to imply the reference", lambda o: o["rel"] is False), ("  of these: S provably determinate", lambda o: o["rel"] is False and o["det"] == 1.0),
                      ("  of these: S not proved determinate", lambda o: o["rel"] is False and o["det"] != 1.0), ("sanity: PROVED to imply the reference", lambda o: o["rel"] is True)]:
        L = [o for o in res if flt(o)]; c = collections.Counter(o["status"] for o in L)
        print("%-40s n %4d | counterexample %3d | all pass %3d | no valid input %3d | not runnable %3d | unsupported %3d | error %d" % (
            name, len(L), c["counterexample"], c["all pass"], c["no valid input"], c["not runnable"], c["unsupported"], c["error"]))
    ce = [o for o in res if o["status"] == "counterexample" and o["rel"] is False]
    print("counterexamples per model:", dict(collections.Counter(o["model"].split(":")[-1] for o in ce)))
    print("tasks with a counterexample:", len(set((o["source"], o["task"]) for o in ce)), collections.Counter(o["task"] for o in ce).most_common(12))
    for o in [x for x in res if x["status"] == "counterexample" and x["rel"] is True][:5]:
        print("SANITY VIOLATION:", o["model"], o["task"], o.get("input"))
    print("not runnable reasons:", collections.Counter((o.get("why") or "")[:60] for o in res if o["status"] == "not runnable").most_common(6))
