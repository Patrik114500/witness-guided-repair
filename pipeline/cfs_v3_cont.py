"""Dafny, specification given: the same-model comparison re-measured under the PUBLISHED acceptance rule.

The published vericoding pipeline accepts an output only if `dafny verify <file>` exits with code 0 (process
limit 120 s). With the Dafny version used here that excludes not only verification errors but also proofs
that hit Dafny's own time limit (exit 4) and programs with warnings (exit 2: warnings are errors unless
--allow-warnings is given). Our loop (cfs_v2) read the summary line instead and accepted both.
This script does not start over. A task whose accepted program already exits with 0 stands. A task whose
accepted program exits with 2 or 4 gets its loop CONTINUED: the verifier's output (warning or time-out) is
fed back and the attempts that were left of the 5 are used, now with the published rule.
Input: /tmp/cfs2_<model>.jsonl and /tmp/rc_probe_cfs.json. Output: /tmp/cfs3_<model>.jsonl."""
import os, sys, re, json, glob, shutil, signal, tempfile, subprocess, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_canon as C
import fix_cheat as FC

NL = chr(10)
MODEL = os.environ["MODEL"]
ITERS = int(os.environ.get("ITERS", "5"))
OUT = os.environ.get("OUT", "/tmp/cfs3_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_"))
BASE = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY as given, "
        "do not weaken them. Add the method body and any helper lemmas or functions you need. If the body needs a "
        "loop, write a WHILE loop with explicit invariants (not a for loop); if it needs no loop, do not add one. "
        "Do not repeat declarations that are already given above the method. Do not use assume or {:axiom}. "
        "Return ONLY a ```dafny code block." + NL + NL)
FIX = (NL + NL + "FAILED verification:" + NL + "%s" + NL + NL + "Fix it; if there is a loop, correct its invariants. Keep the specification "
       "intact. Return ONLY a ```dafny code block.")


def rc_verify(src, timeout=120):
    """the published rule: exit code of `dafny verify`, 120 s process limit"""
    d = tempfile.mkdtemp(prefix="rc_", dir="/tmp"); p = os.path.join(d, "t.dfy")
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


if __name__ == "__main__":
    rcs = {(m, s, t): rc for m, s, t, rc, w, to in json.load(open("/tmp/rc_probe_cfs.json"))}
    recs = {}
    for l in open("/tmp/cfs2_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_")):
        try:
            r = json.loads(l); recs[(r["model"], r["source"], r["task"])] = r
        except Exception:
            pass
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            try:
                r = json.loads(l); done.add((r["model"], r["source"], r["task"]))
            except Exception:
                pass
    tg = [k for k, r in recs.items() if r.get("success") and rcs.get(k, 0) != 0 and k not in done]
    print("%s: accepted %d, exit code 0: %d, to continue: %d" % (MODEL, sum(1 for r in recs.values() if r.get("success")),
                                                               sum(1 for k, r in recs.items() if r.get("success") and rcs.get(k) == 0), len(tg)), flush=True)
    lock = threading.Lock(); fo = open(OUT, "a"); st = collections.Counter()

    def work(k):
        r = recs[k]; parts = H.task_parts(k[1], k[2]); spec = parts["vc-spec"]
        m = re.search(r"method\s+(?:\{:[^}]*\}\s*)*(\w+)", spec); name = m.group(1) if m else None
        base = BASE + V.pre(parts) + NL + spec + NL
        o = {"model": k[0], "source": k[1], "task": k[2], "success": False, "first_iter": r.get("iter"), "first_rc": rcs.get(k)}
        asker = H.Asker(MODEL); att = []
        try:
            rc, out = rc_verify(V.assemble(parts, r["code"]))
            if rc == 0:                                   # the earlier non-zero exit was a load artefact
                o.update({"success": True, "code": r["code"], "iter": r.get("iter"), "note": "exit 0 on re-check"})
            else:
                it = int(r.get("iter") or ITERS); convo = base + FIX % out[-1500:]; api_fail = 0
                while it < ITERS:
                    ans = asker.ask(convo)
                    if not ans.strip():
                        api_fail += 1
                        if api_fail >= 3:
                            att.append({"iter": it + 1, "rc": None, "out": "API-FAILURE"}); break
                        continue
                    it += 1
                    block = H.dedupe_block(parts, V.code_of(ans))
                    byp = FC.cheats(block, "dafny")
                    sp = C.split_method(block, name) if name else None
                    if not sp:
                        att.append({"iter": it, "rc": None, "out": "NO-METHOD"})
                        convo = base + FIX % ("the answer did not contain the method %s with a body" % name); continue
                    canon = sp[0] + spec.rstrip() + NL + sp[1]
                    rc, out = rc_verify(V.assemble(parts, canon))
                    att.append({"iter": it, "rc": rc, "bypass": byp, "out": out[-200:]})
                    if rc == 0 and not byp:
                        o.update({"success": True, "code": canon, "iter": it}); break
                    convo = base + ((NL + NL + FC.message(byp) + " Return ONLY a ```dafny code block.") if rc == 0 else FIX % out[-1500:])
        except Exception as e:
            o["error"] = str(e)[:200]
        o["attempts"] = att; o["cost"] = asker.summ()
        with lock:
            fo.write(json.dumps(o) + NL); fo.flush(); st["n"] += 1; st["ok"] += o["success"]
            print("  %-14s %-34s first it=%s rc=%s -> %s (it=%s) $%.3f | %d/%d" % (k[1], k[2][:34], r.get("iter"), rcs.get(k), "OK" if o["success"] else "fail",
                  o.get("iter"), o["cost"].get("cost_usd", 0), st["ok"], st["n"]), flush=True)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "6"))) as ex:
        list(ex.map(work, tg))
    print("DONE %s continued %d, now exit code 0: %d" % (MODEL, st["n"], st["ok"]), flush=True)
