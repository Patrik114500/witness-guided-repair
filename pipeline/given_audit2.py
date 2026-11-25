"""The reference-free audit of the GIVEN specifications (given_audit.py: certificates D, A, B, T) extended to the
other Dafny benchmarks of the published vericoding set. Same checks, same strict verifier; only the driver differs:
results are written as they arrive and the run can be resumed.
Env: SOURCES (default apps,bignum,dafnybench,humaneval,numpy_triple), OUT (/tmp/given_audit_more.jsonl), WORKERS."""
import os, sys, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
os.environ.setdefault("SOURCES", "apps,bignum,dafnybench,humaneval,numpy_triple")
import given_audit as GA
V = GA.V

NL = chr(10)
SOURCES = [s for s in os.environ["SOURCES"].split(",") if s]
OUT = os.environ.get("OUT", "/tmp/given_audit_more.jsonl")

done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            o = json.loads(l); done.add((o["source"], o["task"]))
        except Exception:
            pass
jobs = []
for s in SOURCES:
    jobs += [(s, f) for f in sorted(glob.glob(V.BENCH + "/%s/yaml/*.yaml" % s)) if (s, os.path.basename(f)) not in done]
print("tasks to audit: %d (already done %d)" % (len(jobs), len(done)), flush=True)
lock = threading.Lock(); n = 0
with open(OUT, "a") as fout, ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "48"))) as ex:
    futs = [ex.submit(GA.audit, j) for j in jobs]
    for fu in as_completed(futs):
        try:
            o = fu.result()
        except Exception as e:
            o = {"source": "?", "task": "?", "status": "error", "error": str(e)[:200]}
        with lock:
            fout.write(json.dumps(o) + NL); fout.flush(); n += 1
            if n % 50 == 0:
                print("  %d / %d" % (n, len(jobs)), flush=True)
res = [json.loads(l) for l in open(OUT)]
for s in SOURCES:
    L = [o for o in res if o["source"] == s]; ok = [o for o in L if o.get("status") == "ok"]
    c = collections.Counter(o.get("status") for o in L)
    weak = [o for o in ok if o.get("A") or o.get("B") or o.get("T")]
    print("%-15s tasks %3d | audited %3d (%s) | D determinate %3d | A %2d | B %2d | T %2d | A or B or T: %3d | undecided %3d" % (
        s, len(L), len(ok), dict(c), sum(1 for o in ok if o.get("D")), sum(1 for o in ok if o.get("A")), sum(1 for o in ok if o.get("B")),
        sum(1 for o in ok if o.get("T")), len(weak), sum(1 for o in ok if not o.get("D")) - len(weak)), flush=True)
print("DONE", flush=True)
