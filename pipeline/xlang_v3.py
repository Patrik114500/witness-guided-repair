"""Given-spec Verus / Lean runner, final version (2026-11-18): the fixed model call of xlang_v2 PLUS the
published pipeline's own bypass rules (fix_cheat): an output that verifies only through assume / axiom /
verifier-external attributes is not a success, the loop says so and the model must try again.
Prompts, integrity check and verifier calls are those of xlang_bench.py.
Env: LANG_=verus|lean, MODEL, ROUNDS (attempts = ROUNDS + 1), OUT, SHARD=i/N, ONLY (file of task names)."""
import os, sys, re, json, glob, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlang_bench as X
import fix_harness as H
import fix_cheat as FC

ASK = H.Asker(X.MODEL, tries=4)
NL = chr(10)


def ask(prompt):
    return ASK.ask(prompt)


def run_verus(y):
    d = yaml.safe_load(open(y))
    pre = d.get("vc-preamble", "use vstd::prelude::*;" + NL + NL + "verus! {")
    post = d.get("vc-postamble", NL + "}" + NL + "fn main() {}")
    spec = d.get("vc-spec", "")
    helpers = d.get("vc-helpers", "") or ""
    base = ("You write Verus (verified Rust). Below is a function with its FIXED requires/ensures "
            "specification and a placeholder body. Write a correct implementation (plus any helper "
            "lemmas or loop invariants you need) so that Verus verifies it. You MUST keep the given "
            "signature, requires and ensures EXACTLY as written. Return ONLY a ```rust block with "
            "the complete function(s); do NOT repeat `use`, `verus! {`, the closing brace or "
            "`fn main`." + NL + NL + "Preamble:" + NL + "%s" + NL + NL + "Specification (fixed):" + NL + "%s" + NL) % (pre, spec)
    convo = base; src = ""; nbyp = 0
    for _ in range(X.ROUNDS + 1):
        g = X.block(ask(convo), "verus")
        src = pre + NL + helpers + NL + g + NL + post
        okI, missing = X.integrity(spec, g)
        if not okI:
            convo = base + (NL + NL + "You modified the given specification (missing lines: %s). Keep it "
                            "EXACTLY. Return ONLY the ```rust block." % missing[:3])
            continue
        ok, out = X.verify_verus(src)
        if ok:
            byp = FC.cheats(g, "verus")
            if not byp:
                return "accepted", src, nbyp
            nbyp += 1
            convo = base + NL + NL + FC.message(byp) + " Return ONLY the ```rust block."
            continue
        if ok is None:
            return "timeout", src, nbyp
        convo = base + NL + NL + "Your attempt failed Verus:" + NL + out[-900:] + NL + NL + "Fix it. Return ONLY the ```rust block."
    return "fail", src, nbyp


def run_lean(p):
    src0 = open(p).read()
    m = re.search(r"-- <vc-theorems>(.*?)(?:-- </vc-theorems>|$)", src0, re.S)
    thm = m.group(1) if m else ""
    base = ("You write Lean 4 (no imports, core only). The file below has definition(s) stubbed "
            "with `sorry` and FIXED specification theorem(s) whose proofs are `sorry`. Implement "
            "the definition(s) and prove the theorem(s). You MUST NOT change any theorem "
            "statement or definition signature. Return ONLY the complete file in a ```lean "
            "block." + NL + NL + src0)
    convo = base; g = ""; nbyp = 0
    for _ in range(X.ROUNDS + 1):
        g = X.block(ask(convo), "lean")
        okI, missing = X.integrity(thm, g)
        if not okI:
            convo = base + (NL + NL + "You modified the given theorem statement (missing: %s). Keep it "
                            "EXACTLY. Return ONLY the full ```lean file." % missing[:2])
            continue
        ok, out = X.verify_lean(g)
        if ok:
            byp = FC.cheats(FC.model_written(g, src0), "lean")
            if not byp:
                return "accepted", g, nbyp
            nbyp += 1
            convo = base + NL + NL + FC.message(byp) + " Return ONLY the full ```lean file."
            continue
        if ok is None:
            return "timeout", g, nbyp
        convo = base + NL + NL + "Your attempt failed Lean:" + NL + out[-1000:] + NL + NL + "Fix it. Return ONLY the full ```lean file."
    return "fail", g, nbyp


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
print("GIVEN-SPEC v3 (guarded) %s model=%s tasks=%d attempts=%d done=%d" % (X.LANG, X.MODEL, len(tasks), X.ROUNDS + 1, len(done)), flush=True)
acc = 0
for t in tasks:
    name = os.path.basename(t)
    if name in done:
        continue
    c0 = ASK.summ()
    try:
        status, src, nbyp = (run_verus(t) if X.LANG == "verus" else run_lean(t))
    except Exception as e:
        status, src, nbyp = "error:" + str(e)[:60], "", 0
    c1 = ASK.summ()
    acc += int(status == "accepted")
    rec = {"model": X.MODEL, "lang": X.LANG, "task": name, "status": status, "src": src if status == "accepted" else "",
           "bypass_rejected": nbyp, "calls": c1["calls"] - c0["calls"], "tok_out": c1["tok_out"] - c0["tok_out"],
           "cost_usd": round(c1["cost_usd"] - c0["cost_usd"], 4)}
    print("  %-34s %-9s calls=%d bypass_rejected=%d $%.3f" % (name[:34], status, rec["calls"], nbyp, rec["cost_usd"]), flush=True)
    if fout:
        fout.write(json.dumps(rec) + NL); fout.flush()
print("DONE accepted %d, cost $%.2f" % (acc, ASK.summ()["cost_usd"]), flush=True)
