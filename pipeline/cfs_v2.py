"""Dafny, specification GIVEN (code + proof generation), for the same-model comparison with the published
vericoding leaderboard on numpy_simple (58) and verina (157). Final harness (2026-11-18):
  - loop-neutral code prompt, dedupe of repeated preamble members, robust model call;
  - acceptance = the model's body verifies when the method is re-stated with the benchmark's EXACT vc-spec
    (signature, requires, ensures untouched), which is how the published pipeline assembles its outputs;
  - the published bypass rules (assume, {:axiom}) reject an output, with feedback.
One run, ITERS attempts (default 5). Env: MODEL, SOURCES, ITERS, WORKERS, OUT, LIMIT. Resumable by key."""
import os, sys, re, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_canon as C
import fix_cheat as FC

MODEL = os.environ["MODEL"]
SOURCES = [s for s in os.environ.get("SOURCES", "numpy_simple,verina").split(",") if s]
ITERS = int(os.environ.get("ITERS", "5"))
LIMIT = int(os.environ.get("LIMIT", "0"))
OUT = os.environ.get("OUT", "/tmp/cfs2_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_"))
BASE = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY as given, "
        "do not weaken them. Add the method body and any helper lemmas or functions you need. If the body needs a "
        "loop, write a WHILE loop with explicit invariants (not a for loop); if it needs no loop, do not add one. "
        "Do not repeat declarations that are already given above the method. Do not use assume or {:axiom}. "
        "Return ONLY a ```dafny code block.\n\n")
FIX = ("\n\nFAILED verification:\n%s\n\nFix it; if there is a loop, correct its invariants. Keep the specification "
       "intact. Return ONLY a ```dafny code block.")


def solve(parts, asker):
    spec = parts["vc-spec"]
    m = re.search(r"method\s+(?:\{:[^}]*\}\s*)*(\w+)", spec)
    name = m.group(1) if m else None
    base = BASE + V.pre(parts) + "\n" + spec + "\n"
    convo = base; att = []; it = 0; api_fail = 0
    while it < ITERS:
        out = asker.ask(convo)
        if not out.strip():
            api_fail += 1
            if api_fail >= 3:
                att.append({"iter": it + 1, "verified": False, "out": "API-FAILURE"}); return None, att
            continue
        it += 1
        block = H.dedupe_block(parts, V.code_of(out))
        byp = FC.cheats(block, "dafny")
        sp = C.split_method(block, name) if name else None
        if not sp:
            att.append({"iter": it, "verified": False, "out": "NO-METHOD"})
            convo = base + FIX % ("the answer did not contain the method %s with a body" % name)
            continue
        canon = sp[0] + spec.rstrip() + "\n" + sp[1]
        ok, err = H.dverify2(V.assemble(parts, canon))
        att.append({"iter": it, "verified": ok, "bypass": byp, "out": err[-200:]})
        if ok and not byp:
            return canon, att
        convo = base + (("\n\n" + FC.message(byp) + " Return ONLY a ```dafny code block.") if ok else FIX % err)
    return None, att


done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            r = json.loads(l); done.add((r["source"], r["task"]))
        except Exception:
            pass
jobs = []
for src in SOURCES:
    fs = sorted(glob.glob(V.BENCH + "/%s/yaml/*.yaml" % src))
    if LIMIT:
        fs = fs[:LIMIT]
    jobs += [(src, f) for f in fs if (src, os.path.basename(f)) not in done]
print("%s given-spec v2: %d tasks to run (%d done), ITERS=%d" % (MODEL, len(jobs), len(done), ITERS), flush=True)
lock = threading.Lock(); fo = open(OUT, "a"); st = collections.Counter(); cost = [0.0]


def work(job):
    src, f = job; task = os.path.basename(f)
    o = {"model": MODEL, "source": src, "task": task, "success": False}
    try:
        parts = V.load(f); asker = H.Asker(MODEL)
        code, att = solve(parts, asker)
        o["attempts"] = att; o["cost"] = asker.summ(); o["success"] = code is not None
        if code is not None:
            o["code"] = code; o["iter"] = att[-1]["iter"]
    except Exception as e:
        o["error"] = str(e)[:200]
    with lock:
        fo.write(json.dumps(o) + "\n"); fo.flush()
        st[(src, "n")] += 1; st[(src, "ok")] += bool(o["success"]); cost[0] += (o.get("cost") or {}).get("cost_usd", 0)
        print("  %-14s %-34s %s it=%s $%.3f | %s cum $%.2f" % (src, task[:34], "OK  " if o["success"] else "fail", o.get("iter"),
              (o.get("cost") or {}).get("cost_usd", 0), {s: "%d/%d" % (st[(s, "ok")], st[(s, "n")]) for s in SOURCES}, cost[0]), flush=True)


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "8"))) as ex:
    list(ex.map(work, jobs))
print("DONE %s %s cost $%.2f" % (MODEL, {s: "%d/%d" % (st[(s, "ok")], st[(s, "n")]) for s in SOURCES}, cost[0]), flush=True)
