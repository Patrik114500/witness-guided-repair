"""The undecided GIVEN specifications, opened up with the witness of wit2 (2026-11-21).
For every given specification the reference-free audit (given_audit*.jsonl) could neither prove
determinate (D) nor provably too weak (A, B, T), on the seven Dafny datasets with published per-task outputs:
  1 witness : the model proposes an input and two different outputs; the tool confirms that the precondition holds
              and the specification admits both (executing the compiled predicates, else a verifier proof). A
              confirmed witness is a checked fact: the given specification is not determinate.
  2 arbiter : if the task has a description, the model reads it and says whether both outputs are intended
              (INTENDED: benign multi-valued intent) or not (UNINTENDED: the given specification is too weak). This
              is a model judgement, not a proof, and is reported as such.
The specification is the LAST method of vc-spec (the one whose body the benchmark asks for), as in the audit.
No body is needed: the witness is checked on the specification alone.
Env: MODEL (default aoai:gpt-5-mini), CAP (USD), WORKERS, LIMIT, OUT (/tmp/given_witness.jsonl, resumable)."""
import os, sys, re, json, random, threading, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "aoai:gpt-5-mini")
import given_audit as GA
import fix_harness as H
import fix_oracle as O
import wit2 as W2

V = GA.V
NL = chr(10)
MODEL = os.environ["MODEL"]
OUT = os.environ.get("OUT", "/tmp/given_witness.jsonl")
CAP = float(os.environ.get("CAP", "25")); LIMIT = int(os.environ.get("LIMIT", "0"))
SRC = ["apps", "bignum", "dafnybench", "humaneval", "numpy_simple", "numpy_triple", "verina"]


def jl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


A = {}
for f in ("/tmp/given_audit.jsonl", "/tmp/given_audit_more.jsonl"):
    for o in jl(f):
        A[(o["source"], o["task"])] = o
targets = [k for k, o in A.items() if k[0] in SRC and o.get("status") == "ok" and not o.get("D")
           and not (o.get("A") or o.get("B") or o.get("T"))]
done = set((r["source"], r["task"]) for r in jl(OUT) if r.get("status") != "api-fail")
tg = [k for k in targets if k not in done]
random.Random(5).shuffle(tg)
if LIMIT:
    tg = tg[:LIMIT]
print("undecided given specifications: %d, to run %d (done %d), model %s, cap $%.0f" % (len(targets), len(tg), len(done), MODEL, CAP), flush=True)


def task_parts(src, task):
    """the benchmark task with the method under audit as vc-spec; earlier declarations of vc-spec go to the preamble"""
    parts = V.load(V.BENCH + "/%s/yaml/%s" % (src, task))
    vs = parts.get("vc-spec") or ""
    pos = [m.start() for m in re.finditer(r"(?m)^\s*method\b", vs)]
    if not pos:
        return None, None
    p2 = dict(parts)
    p2["vc-preamble"] = (parts.get("vc-preamble") or "") + NL + vs[:pos[-1]]
    p2["vc-spec"] = vs[pos[-1]:]
    h = GA.target_header(vs)
    return p2, h


lock = threading.Lock(); spent = [0.0]; st = collections.Counter(); fo = open(OUT, "a")


def work(k):
    if spent[0] > CAP:
        with lock:
            st["skipped-cap"] += 1
        return
    src, task = k
    o = {"source": src, "task": task}
    asker = H.Asker(MODEL)
    try:
        parts, h = task_parts(src, task)
        if not parts or not h or not h["ensures"]:
            o["status"] = "unsupported"
        else:
            S = O.spec_text(h["ensures"])
            o["has_description"] = bool((parts.get("vc-description") or "").strip())
            log = []
            wit = W2.find_witness2(parts, S, "", asker, log)
            o["wlog"] = log[-6:]
            if "api-fail" in log:
                o["status"] = "api-fail"
            elif not wit:
                o["status"] = "no-witness"
            else:
                o["witness"] = wit
                if not o["has_description"]:
                    o["status"] = "witness, no description"
                else:
                    verdict, correct, C, info = W2.arbiter(parts, S, "", wit, asker)
                    o["arbiter"] = verdict; o["correct"] = correct
                    o["status"] = "api-fail" if verdict == "API-FAIL" else "witness, arbiter " + str(verdict)
    except Exception as e:
        o["status"] = "error"; o["error"] = str(e)[:300]
    o["cost"] = asker.summ()
    with lock:
        spent[0] += o["cost"].get("cost_usd", 0)
        fo.write(json.dumps(o) + NL); fo.flush()
        st["n"] += 1; st[o["status"]] += 1
        print("  %-13s %-40s %-30s $%.3f | n %d/%d spent $%.2f" % (src, task[:40], o["status"], o["cost"].get("cost_usd", 0), st["n"], len(tg), spent[0]), flush=True)


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "12"))) as ex:
    list(ex.map(work, tg))
print("DONE %s spent $%.2f" % (dict(st), spent[0]), flush=True)
