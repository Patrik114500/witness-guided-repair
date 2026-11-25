"""Specification given: the loop with a SELF-BOOTSTRAPPED example library (2026-11-18, late evening).

The plain loop solves every task in isolation. Benchmarks such as numpy_simple are families of similar
tasks, and what the model lacks on the unsolved ones is mostly verifier idiom, which its own accepted
solutions of sibling tasks already contain. Protocol, same model and same budget as the published run:
  * at most ATTEMPTS (5) model answers per task, as before;
  * attempt 1 is zero-shot, the unchanged prompt;
  * from attempt 2 on the prompt also carries up to K (3) solutions of the most similar tasks that THIS
    model has already had accepted in THIS run (TF-IDF similarity of the task text), plus the previous
    attempt with the verifier's output;
  * the library grows after every round; no reference solution and no other model's output is ever used.
Acceptance is the published rule of each language: Dafny `dafny verify` exits with 0 on the method re-stated
under the benchmark's exact spec; Verus and Lean exactly as in xlang_bench (their own verifier calls, spec
integrity), and the published bypass rules reject an output.
For Dafny, attempt 1 is taken from the existing plain run (cfs_v2: same prompt, every first answer reused
whatever its outcome), so only attempts 2-5 are new calls.

Env: LANG_=dafny|verus|lean, MODEL, SOURCE (dafny: verina|numpy_simple), ATTEMPTS, K, WORKERS, CAP, OUT."""
import os, sys, re, json, glob, math, shutil, signal, tempfile, subprocess, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LANG = os.environ.get("LANG_", "dafny")
import vericode_compete as V          # noqa: E402
import fix_harness as H               # noqa: E402
import fix_canon as C                 # noqa: E402
import fix_cheat as FC                # noqa: E402

NL = chr(10)
MODEL = os.environ["MODEL"]; SOURCE = os.environ.get("SOURCE", "numpy_simple")
ATT = int(os.environ.get("ATTEMPTS", "5")); K = int(os.environ.get("K", "3")); CAP = float(os.environ.get("CAP", "25"))
TAG = MODEL.replace(":", "_").replace("/", "_")
OUT = os.environ.get("OUT", "/tmp/boot_%s_%s_%s.jsonl" % (LANG, SOURCE, TAG))
STATE = OUT.replace(".jsonl", ".state.json")
EX_LIM = 3500


def toks(s):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s or "")
    return [w.lower() for w in re.findall(r"[A-Za-z]+|\d+", s)]


class Sim:
    def __init__(self, docs):
        self.tf = {i: collections.Counter(toks(t)) for i, t in docs.items()}
        df = collections.Counter(w for c in self.tf.values() for w in c)
        n = len(docs)
        self.idf = {w: math.log((1.0 + n) / (1.0 + d)) + 1.0 for w, d in df.items()}
        self.norm = {i: math.sqrt(sum((c[w] * self.idf[w]) ** 2 for w in c)) or 1.0 for i, c in self.tf.items()}

    def top(self, q, cands, k):
        cq = self.tf[q]; sc = []
        for i in cands:
            if i == q:
                continue
            ci = self.tf[i]
            dot = sum(cq[w] * ci[w] * self.idf[w] ** 2 for w in cq if w in ci)
            sc.append((dot / (self.norm[q] * self.norm[i]), i))
        sc.sort(reverse=True)
        return [i for s, i in sc[:k] if s > 0]


def rc_verify(src, timeout=120):
    """published Dafny rule: exit code of `dafny verify`, 120 s process limit"""
    d = tempfile.mkdtemp(prefix="bg_", dir="/tmp"); p = os.path.join(d, "t.dfy")
    with open(p, "w") as f:
        f.write(src)
    try:
        pr = subprocess.Popen([V.DAFNY, "verify", p], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            o, _ = pr.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pr.pid, signal.SIGKILL)
            except Exception:
                pass
            return -9, "TIMEOUT: verification did not finish in %d seconds" % timeout
        return pr.returncode, o
    finally:
        shutil.rmtree(d, ignore_errors=True)


BASE_DAFNY = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY as given, "
              "do not weaken them. Add the method body and any helper lemmas or functions you need. If the body needs a "
              "loop, write a WHILE loop with explicit invariants (not a for loop); if it needs no loop, do not add one. "
              "Do not repeat declarations that are already given above the method. Do not use assume or {:axiom}. "
              "Return ONLY a ```dafny code block." + NL + NL)


class Dafny:
    fence = "dafny"; RET = "Return ONLY a ```dafny code block."

    def __init__(self):
        self.files = {os.path.basename(f): f for f in sorted(glob.glob(V.BENCH + "/%s/yaml/*.yaml" % SOURCE))}
        self.parts = {t: V.load(f) for t, f in self.files.items()}

    def tasks(self):
        return sorted(self.files)

    def sim_text(self, t):
        return t + " " + self.parts[t]["vc-spec"] + " " + (self.parts[t].get("vc-description") or "")[:600]

    def base(self, t):
        return BASE_DAFNY + V.pre(self.parts[t]) + NL + self.parts[t]["vc-spec"] + NL

    def check(self, t, ans):
        parts = self.parts[t]; spec = parts["vc-spec"]
        m = re.search(r"method\s+(?:\{:[^}]*\}\s*)*(\w+)", spec); name = m.group(1) if m else None
        block = H.dedupe_block(parts, V.code_of(ans))
        byp = FC.cheats(block, "dafny")
        sp = C.split_method(block, name) if name else None
        if not sp:
            return False, block, "the answer did not contain the method %s with a body" % name, None
        canon = sp[0] + spec.rstrip() + NL + sp[1]
        rc, out = rc_verify(V.assemble(parts, canon))
        if rc == 0 and not byp:
            return True, block, "", canon
        if rc == 0:
            return False, block, FC.message(byp), None
        return False, block, out[-1500:], None

    def first_round(self):
        """attempt 1 from the plain run: every first answer is reused, whatever its outcome"""
        rcs = {(m, s, t): rc for m, s, t, rc, w, to in json.load(open("/tmp/rc_probe_cfs.json"))}
        solved = {}; state = {}
        for l in open("/tmp/cfs2_%s.jsonl" % TAG):
            try:
                r = json.loads(l)
            except Exception:
                continue
            if r.get("source") != SOURCE or not (r.get("success") and r.get("iter") == 1 and r.get("code")):
                continue
            t = r["task"]
            if rcs.get((r["model"], r["source"], t)) == 0:
                solved[t] = r["code"]
            else:                                   # accepted by the old lenient call only: warning or time-out
                rc, out = rc_verify(V.assemble(self.parts[t], r["code"]))
                if rc == 0:
                    solved[t] = r["code"]
                else:
                    state[t] = (r["code"], out[-1500:])
        return solved, state


class Verus:
    fence = "rust"; RET = "Return ONLY the ```rust block."

    def __init__(self):
        import yaml
        import xlang_bench as X
        self.X = X
        self.files = {os.path.basename(f): f for f in sorted(glob.glob(X.TASKDIR + "/*.yaml"))}
        self.d = {t: yaml.safe_load(open(f)) for t, f in self.files.items()}

    def tasks(self):
        return sorted(self.files)

    def _p(self, t):
        d = self.d[t]
        return (d.get("vc-preamble", "use vstd::prelude::*;" + NL + NL + "verus! {"), d.get("vc-postamble", NL + "}" + NL + "fn main() {}"),
                d.get("vc-spec", ""), d.get("vc-helpers", "") or "")

    def sim_text(self, t):
        return t + " " + self._p(t)[2] + " " + str(self.d[t].get("vc-description") or "")[:600]

    def base(self, t):
        pre, post, spec, helpers = self._p(t)
        return ("You write Verus (verified Rust). Below is a function with its FIXED requires/ensures "
                "specification and a placeholder body. Write a correct implementation (plus any helper "
                "lemmas or loop invariants you need) so that Verus verifies it. You MUST keep the given "
                "signature, requires and ensures EXACTLY as written. Return ONLY a ```rust block with "
                "the complete function(s); do NOT repeat `use`, `verus! {`, the closing brace or "
                "`fn main`." + NL + NL + "Preamble:" + NL + "%s" + NL + NL + "Specification (fixed):" + NL + "%s" + NL) % (pre, spec)

    def check(self, t, ans):
        X = self.X; pre, post, spec, helpers = self._p(t)
        g = X.block(ans, "verus")
        okI, missing = X.integrity(spec, g)
        if not okI:
            return False, g, "You modified the given specification (missing lines: %s). Keep it EXACTLY." % missing[:3], None
        ok, out = X.verify_verus(pre + NL + helpers + NL + g + NL + post)
        if ok:
            byp = FC.cheats(g, "verus")
            if not byp:
                return True, g, "", g
            return False, g, FC.message(byp), None
        if ok is None:
            return False, g, "Verus did not finish within the time limit. Simplify the proof.", None
        return False, g, "Your attempt failed Verus:" + NL + out[-900:], None

    def first_round(self):
        return None


class Lean:
    fence = "lean"; RET = "Return ONLY the full ```lean file."

    def __init__(self):
        import xlang_bench as X
        self.X = X
        self.files = {os.path.basename(f): f for f in sorted(glob.glob(X.TASKDIR + "/*.lean"))}
        self.src = {t: open(f).read() for t, f in self.files.items()}

    def tasks(self):
        return sorted(self.files)

    def _thm(self, t):
        m = re.search(r"-- <vc-theorems>(.*?)(?:-- </vc-theorems>|$)", self.src[t], re.S)
        return m.group(1) if m else ""

    def sim_text(self, t):
        return t + " " + self.src[t]

    def base(self, t):
        return ("You write Lean 4 (no imports, core only). The file below has definition(s) stubbed "
                "with `sorry` and FIXED specification theorem(s) whose proofs are `sorry`. Implement "
                "the definition(s) and prove the theorem(s). You MUST NOT change any theorem "
                "statement or definition signature. Return ONLY the complete file in a ```lean "
                "block." + NL + NL + self.src[t])

    def check(self, t, ans):
        X = self.X
        g = X.block(ans, "lean")
        okI, missing = X.integrity(self._thm(t), g)
        if not okI:
            return False, g, "You modified the given theorem statement (missing: %s). Keep it EXACTLY." % missing[:2], None
        # full specification lock: the preamble and every definition header must be kept as given, too
        src0 = self.src[t]
        sec = lambda name: (re.search(r"-- <%s>(.*?)(?:-- </%s>|$)" % (name, name), src0, re.S) or [None, ""])[1]
        okP, missP = X.integrity(sec("vc-preamble"), g)
        okD, missD = X.integrity(NL.join(l for l in sec("vc-definitions").splitlines() if l.strip() != "sorry"), g)
        if not (okP and okD):
            return False, g, ("You changed a given declaration (missing: %s). Keep the preamble and every definition signature EXACTLY; "
                              "only replace `sorry`." % (missP + missD)[:2]), None
        ok, out = X.verify_lean(g)
        if ok:
            byp = FC.cheats(FC.model_written(g, self.src[t]), "lean")
            if not byp:
                return True, g, "", g
            return False, g, FC.message(byp), None
        if ok is None:
            return False, g, "Lean did not finish within the time limit. Simplify the proof.", None
        return False, g, "Your attempt failed Lean:" + NL + out[-1000:], None

    def first_round(self):
        return None


def build(ad, t, ex, st):
    p = ""
    if ex:
        p += ("Before the task: %d solution(s) of similar tasks from the same benchmark that the verifier ACCEPTED. They show "
              "idioms that work with this verifier. Adapt what helps; the task below is a different one." % len(ex)) + NL
        for i, (et, art) in enumerate(ex):
            p += NL + "Verified example %d (%s):" % (i + 1, et) + NL + "```" + ad.fence + NL + art.strip()[:EX_LIM] + NL + "```" + NL
        p += NL + "Now the task." + NL + NL
    p += ad.base(t)
    if st:
        block, fb = st
        p += (NL + NL + "Your previous attempt:" + NL + "```" + ad.fence + NL + (block or "").strip()[:6000] + NL + "```" + NL +
              "It was rejected:" + NL + (fb or "") + NL + NL + "Fix it. " + ad.RET)
    return p


if __name__ == "__main__":
    ad = {"dafny": Dafny, "verus": Verus, "lean": Lean}[LANG]()
    T = ad.tasks(); sim = Sim({t: ad.sim_text(t) for t in T})
    solved = {}; state = {}; used = {t: 0 for t in T}; hist = {t: [] for t in T}; rsolved = {}
    cost = [0.0]; calls = [0]; lock = threading.Lock(); start_iter = 1
    if os.path.exists(STATE):
        s = json.load(open(STATE))
        solved, state, used, hist, rsolved = s["solved"], {k: tuple(v) for k, v in s["state"].items()}, s["used"], s["hist"], s["rsolved"]
        cost[0] = s["cost"]; calls[0] = s["calls"]; start_iter = s["iter"] + 1
        print("resumed after iteration %d: solved %d" % (s["iter"], len(solved)), flush=True)
    else:
        fr = ad.first_round()
        if fr is not None:
            solved, state = fr
            for t in T:
                used[t] = 1; hist[t].append({"attempt": 1, "ok": t in solved, "ex": [], "src": "plain run"})
            for t in solved:
                rsolved[t] = 1
            start_iter = 2
            print("attempt 1 taken from the plain run: %d of %d solved" % (len(solved), len(T)), flush=True)
    print("%s %s %s: %d tasks, attempts %d, examples %d, cap $%.0f" % (LANG, SOURCE if LANG == "dafny" else "numpy_simple", MODEL, len(T), ATT, K, CAP), flush=True)

    def work(job):
        t, lib = job
        ex_ids = sim.top(t, list(lib), K) if lib else []
        ex = [(e, lib[e]) for e in ex_ids]
        asker = H.Asker(MODEL, tries=4)
        try:
            ans = asker.ask(build(ad, t, ex, state.get(t)))
        except Exception:
            ans = ""
        c = asker.summ()
        with lock:
            cost[0] += c.get("cost_usd", 0); calls[0] += c.get("calls", 0)
        if not (ans or "").strip():
            return t, None
        try:
            ok, block, fb, art = ad.check(t, ans)
        except Exception as e:
            ok, block, fb, art = False, "", "internal error: %s" % str(e)[:200], None
        return t, (ok, block, fb, art, ex_ids)

    it = start_iter - 1
    for it in range(start_iter, ATT + 4):
        todo = [t for t in T if t not in solved and used[t] < ATT]
        if not todo or cost[0] > CAP:
            break
        lib = dict(solved)                        # the library as it stands at the start of the round
        with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "8"))) as ex:
            res = list(ex.map(work, [(t, lib) for t in todo]))
        new = 0; fail_api = 0
        for t, r in res:
            if r is None:
                fail_api += 1; continue          # no answer from the API: not an attempt
            ok, block, fb, art, ex_ids = r
            used[t] += 1
            hist[t].append({"attempt": used[t], "ok": ok, "ex": ex_ids, "fb": (fb or "")[-160:]})
            if ok:
                solved[t] = art; rsolved[t] = used[t]; new += 1; state.pop(t, None)
            else:
                state[t] = (block, fb)
        json.dump({"iter": it, "solved": solved, "state": state, "used": used, "hist": hist, "rsolved": rsolved, "cost": cost[0], "calls": calls[0]},
                  open(STATE, "w"))
        print("  round %d: tried %d, newly solved %d, API failures %d | solved %d of %d | by attempt %s | $%.2f, %d calls" % (
            it, len(todo), new, fail_api, len(solved), len(T), sorted(collections.Counter(rsolved.values()).items()), cost[0], calls[0]), flush=True)
    with open(OUT, "w") as f:
        for t in T:
            f.write(json.dumps({"model": MODEL, "lang": LANG, "source": SOURCE if LANG == "dafny" else "numpy_simple", "task": t, "solved": t in solved,
                                "attempt_solved": rsolved.get(t), "attempts_used": used[t], "code": solved.get(t, ""), "hist": hist[t]}) + NL)
    print("DONE %s %s %s: solved %d of %d | by attempt %s | with examples in the accepted prompt %d | $%.2f, %d calls" % (
        LANG, SOURCE if LANG == "dafny" else "numpy_simple", MODEL, len(solved), len(T), sorted(collections.Counter(rsolved.values()).items()),
        sum(1 for t in solved if hist[t] and hist[t][-1].get("ex")), cost[0], calls[0]), flush=True)
