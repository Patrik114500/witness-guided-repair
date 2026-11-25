"""Given-spec Verus / Lean runner with the fixed model call (2026-11-18).
Identical to xlang_bench.py (same prompts, same ROUNDS, same integrity check, same verifier calls); the only
change is the model call: reasoning models get a larger completion budget and an empty / failed response is
retried instead of silently consuming a repair round (fix_harness.Asker).
Env: LANG_=verus|lean, MODEL, ROUNDS, OUT, SHARD=i/N, ONLY (file with task names, one per line)."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlang_bench as X
import fix_harness as H

ASK = H.Asker(X.MODEL, tries=4)


def _ask(model, prompt, temp=0.3):
    return ASK.ask(prompt)


X.V.ask = _ask
OUT = os.environ.get("OUT", "")
SHARD = os.environ.get("SHARD", "")
ONLY = os.environ.get("ONLY", "")
pat = "/*.yaml" if X.LANG == "verus" else "/*.lean"
tasks = sorted(glob.glob(X.TASKDIR + pat))
if ONLY:
    keep = set(l.strip() for l in open(ONLY) if l.strip())
    tasks = [t for t in tasks if os.path.basename(t) in keep]
if SHARD:
    i, n = map(int, SHARD.split("/")); tasks = [t for j, t in enumerate(tasks) if j % n == i]
done = set()
if OUT and os.path.exists(OUT):
    for l in open(OUT):
        try:
            done.add(json.loads(l)["task"])
        except Exception:
            pass
fout = open(OUT, "a") if OUT else None
print("GIVEN-SPEC v2 %s model=%s tasks=%d rounds=%d done=%d" % (X.LANG, X.MODEL, len(tasks), X.ROUNDS, len(done)), flush=True)
acc = 0
for t in tasks:
    name = os.path.basename(t)
    if name in done:
        continue
    c0 = ASK.summ()
    try:
        status, src = (X.run_verus_task(t) if X.LANG == "verus" else X.run_lean_task(t))
    except Exception as e:
        status, src = "error:" + str(e)[:60], ""
    c1 = ASK.summ()
    acc += int(status == "accepted")
    rec = {"model": X.MODEL, "lang": X.LANG, "task": name, "status": status, "src": src if status == "accepted" else "",
           "calls": c1["calls"] - c0["calls"], "empties": c1["empties"] - c0["empties"],
           "tok_out": c1["tok_out"] - c0["tok_out"], "cost_usd": round(c1["cost_usd"] - c0["cost_usd"], 4)}
    print("  %-34s %-9s calls=%d empties=%d out_tok=%d $%.3f" % (name[:34], status, rec["calls"], rec["empties"], rec["tok_out"], rec["cost_usd"]), flush=True)
    if fout:
        fout.write(json.dumps(rec) + chr(10)); fout.flush()
print("DONE accepted %d, cost $%.2f" % (acc, ASK.summ()["cost_usd"]), flush=True)
