"""The reference specifications of the two END-TO-END benchmarks (MBPP-DFY and CloverBench), put through the same
reference-free audit as the given specifications of the vericoding set (given_audit.py: D determinate,
A unconstrained, B shape only, T a task-ignoring program verifies). No model call.
"Correct" in result 3 means "the generated specification implies the reference", so a reference that is itself too
weak makes that verdict cheap for both pipelines. This counts how many references are affected, and how many of
each pipeline's correct MBPP tasks sit on them.
Output /tmp/ref_audit.jsonl."""
import os, sys, re, json, glob, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import given_audit as GA
import boot_given as B
import fix_hdr as HDR
import fix_oracle as O
V = GA.V

NL = chr(10)
D = os.path.expanduser("~/clover/dataset/MBPP-DFY-153")
MRE = re.compile(r"(?m)^[ \t]*(?:ghost[ \t]+)?method\b[ \t]*(?:\{:[^}]*\}[ \t]*)*(\w+)")


def audit_parts(src, task, parts):
    o = {"source": src, "task": task}
    try:
        vs = parts.get("vc-spec") or ""
        h = GA.target_header(vs)
        if not h or not h["rets"]:
            o["status"] = "no-method-or-no-return"; return o
        if h["modifies"]:
            o["status"] = "in-place"; return o
        if not h["ensures"]:
            o.update({"status": "ok", "n_ens": 0, "D": False, "A": True, "B": None, "T": None, "note": "no postcondition at all"}); return o
        o.update({"status": "ok", "n_ens": len(h["ensures"]), "method": h["name"], "spec": NL.join("ensures " + e for e in h["ensures"])[:600]})
        o["D"] = GA.prove(GA.lemma(parts, h, "D"))
        o["A"] = None if o["D"] else GA.prove(GA.lemma(parts, h, "A"))
        o["B"] = None if (o["D"] or o["A"]) else GA.prove(GA.lemma(parts, h, "B"))
        o["T"] = None
        if not o["D"]:
            for lab, st in GA.trivial_bodies(h):
                prog = vs.rstrip() + NL + "{" + NL + "  " + st + NL + "}" + NL
                rc, out = B.rc_verify(V.assemble(parts, prog))
                if rc == 0:
                    o["T"] = lab; o["T_body"] = st; break
    except Exception as e:
        o["status"] = "error"; o["error"] = str(e)[:200]
    return o


def mbpp_parts(tid):
    code = open(D + "/src/task_id_%s.dfy" % tid).read()
    hs = []
    for m in MRE.finditer(code):
        h = HDR.parse(code[m.start():])
        if h and h["rets"] and m.group(1) != "Main":
            hs.append(h)
    if not hs:
        return None
    h = hs[0]
    # the reference program stays available as context (its helper functions), its task method under another name
    pre = re.sub(r"\bmethod(\s+(?:\{:[^}]*\}\s*)*)%s\b" % re.escape(h["name"]), lambda m: "method" + m.group(1) + h["name"] + "_ref_", code, count=1)
    vs = HDR.head_text(h) + NL + NL.join("    ensures " + e for e in h["ensures"])
    return {"vc-preamble": pre, "vc-helpers": "", "vc-code": "", "vc-postamble": "", "vc-description": "", "vc-spec": vs}


jobs = []
db = json.load(open(glob.glob(D + "/*.json")[0]))
for tid in sorted(db, key=int):
    if os.path.exists(D + "/src/task_id_%s.dfy" % tid):
        p = mbpp_parts(tid)
        jobs.append(("mbpp", "task_id_" + tid, p))
try:
    sys.path.insert(0, os.path.expanduser("~/clover")); sys.path.insert(0, os.path.expanduser("~/clover/clover")); sys.path.insert(0, os.path.expanduser("~/clover/shim"))
    import clover_gated as CG
    tasks = sorted(set(json.loads(l)["task"] for f in glob.glob("/tmp/clover_v2_*_s*.jsonl") for l in open(f)))
    for t in tasks:
        try:
            doc, head, parts = CG.load_task(t)
            jobs.append(("clover", t, parts))
        except Exception as e:
            jobs.append(("clover", t, None))
except Exception as e:
    print("clover loader not available:", str(e)[:200], flush=True)
print("references to audit: %s" % dict(collections.Counter(j[0] for j in jobs)), flush=True)


def run(j):
    src, task, parts = j
    if parts is None:
        return {"source": src, "task": task, "status": "not loadable"}
    return audit_parts(src, task, parts)


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "40"))) as ex:
    res = list(ex.map(run, jobs))
with open("/tmp/ref_audit.jsonl", "w") as f:
    for o in res:
        f.write(json.dumps(o) + NL)
for s in ("mbpp", "clover"):
    L = [o for o in res if o["source"] == s]; ok = [o for o in L if o.get("status") == "ok"]
    weak = [o for o in ok if o.get("A") or o.get("B") or o.get("T")]
    print("%-7s references %3d | audited %3d (%s) | D determinate %3d | A %d B %d T %d | flagged %2d | undecided %3d" % (
        s, len(L), len(ok), dict(collections.Counter(o.get("status") for o in L)), sum(1 for o in ok if o.get("D")),
        sum(1 for o in ok if o.get("A")), sum(1 for o in ok if o.get("B")), sum(1 for o in ok if o.get("T")), len(weak),
        sum(1 for o in ok if not o.get("D")) - len(weak)), flush=True)
    for o in weak:
        print("     %-22s %s%s%s | %-34s | %s" % (o["task"][:22], "A" if o.get("A") else "-", "B" if o.get("B") else "-", "T" if o.get("T") else "-",
                                                (o.get("T") or o.get("note") or "")[:34], (o.get("spec") or "").replace(NL, " ; ")[:150]))
# how the MBPP verdicts sit on the reference classes
cls = {}
for o in res:
    if o["source"] == "mbpp":
        cls[o["task"]] = ("flagged" if (o.get("A") or o.get("B") or o.get("T")) else ("determinate" if o.get("D") else "undecided")) if o.get("status") == "ok" else "not audited"
if os.path.exists("/tmp/mbpp_rescore.jsonl"):
    R = [json.loads(l) for l in open("/tmp/mbpp_rescore.jsonl")]
    for p in ("baseline", "ours"):
        c = collections.Counter((o.get("proof"), cls.get(o["task"], "?")) for o in R if o["pipeline"] == p and o.get("strict") and not o.get("bypass"))
        print("MBPP %-8s verdict x reference class: %s" % (p, {"%s|%s" % k: v for k, v in sorted(c.items(), key=str)}))
print("DONE", flush=True)
