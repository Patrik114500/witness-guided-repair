"""Stage E (2026-11-18 evening): repair of the header bug.

The first pipeline read the task's method header with a single-line regular expression. For 55 tasks a
`requires` clause that starts on the next line (or spans lines) was cut off, so the model was shown a
dangling `requires` in the specification prompt and in the code prompt. Two consequences:
  * models that kept the header "exactly" could not verify anything (artificial failures);
  * models that rewrote the header got "accepted" with a precondition of their own, or with a block that
    does not contain the method at all (the acceptance test only asked whether the file verifies).
This stage re-runs those tasks from scratch with the correct header, and re-runs the code stage of the
other accepts whose body does not verify under the benchmark's own header.
  mode "full": specification generation (big_run.gen_spec_raw, unchanged prompt) + code loop
  mode "code": code loop from the stored generated specification
The code loop is SPEC-LOCKED: only the body the model returns is used, restated under the benchmark's own
signature and requires and the generated ensures. So an accept is canonical by construction, and a block
without the method is not an accept. Same number of attempts as the big run (5), bypasses rejected.

Run: MODEL=<id> [WORKERS=6] [CAP=usd] python3 -u fix_rerun_e.py     Output: /tmp/fix_rerunE_<model>.jsonl
"""
import os, sys, re, json, time, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_hdr as HDR
import fix_canon as FCN
import fix_cheat as FC
import fix_oracle as O

# every module of this process reads the robust header (this is the bug the stage repairs)
_old_sig_head = V.sig_head


def _sig_head(vs):
    h = HDR.parse(vs)
    return HDR.head_text(h) if h else _old_sig_head(vs)


V.sig_head = _sig_head
import big_run as BR          # noqa: E402  (after the patch)
import wit2 as W2             # noqa: E402

NL = chr(10)
ITERS = int(os.environ.get("ITERS", "5"))


class Tr:
    """big_run's tracker interface on top of the robust asker"""
    def __init__(self, asker):
        self.model = asker.model; self.a = asker

    def ask(self, prompt, label=""):
        return self.a.ask(prompt)


def code_loop_locked(parts, head, gen, asker, iters=ITERS):
    base_txt, fix_txt = H.PROMPTS["orig"]
    base = base_txt + V.pre(parts) + NL + head + NL + "    " + gen + NL
    name = O.hdr(parts)["name"]
    convo = base; attempts = []; it = 0; api_fail = 0
    while it < iters:
        out = asker.ask(convo)
        if not out.strip():
            api_fail += 1
            if api_fail >= 3:
                attempts.append({"iter": it + 1, "verified": False, "out": "API-FAILURE"})
                return None, attempts
            continue
        it += 1
        block = H.dedupe_block(parts, V.code_of(out))
        prog = FCN.canonical_program(block, name, head, gen)      # spec lock: the model's body, the task's header
        if not prog:
            attempts.append({"iter": it, "verified": False, "out": "NO-METHOD"})
            convo = base + fix_txt % ("the answer did not contain the method %s with a body" % name)
            continue
        ok, err = H.dverify2(V.assemble(parts, prog))
        byp = W2.bypasses(prog)
        attempts.append({"iter": it, "verified": ok, "bypass": byp, "out": err[-300:]})
        if ok and not byp:
            return prog, attempts
        if ok and byp:
            convo = base + NL + NL + FC.message(byp) + " Return ONLY a ```dafny code block."
        else:
            convo = base + fix_txt % err
    return None, attempts


def _jsonl(path):
    out = []
    if os.path.exists(path):
        for l in open(path):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


if __name__ == "__main__":
    MODEL = os.environ["MODEL"]
    CODE2 = os.environ.get("CODE2", "") == "1"     # code-only re-runs from the specification read out of the old accepted program
    OUT = os.environ.get("OUT", ("/tmp/fix_rerunE2_%s.jsonl" if CODE2 else "/tmp/fix_rerunE_%s.jsonl") % MODEL.replace(":", "_").replace("/", "_"))
    CAP = float(os.environ.get("CAP", "40")); LIMIT = int(os.environ.get("LIMIT", "0"))
    broken = set(tuple(x) for x in json.load(open("/tmp/fix_broken_head.json"))["broken"])
    base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun({MODEL})}
    sc3 = {(r["model"], r["source"], r["task"]): r for r in _jsonl("/tmp/fix_scores5.jsonl" if os.path.exists("/tmp/fix_scores5.jsonl") else "/tmp/fix_scores3.jsonl")}
    done = set((r["model"], r["source"], r["task"]) for r in _jsonl(OUT) if not r.get("api_fail"))
    jobs = []
    for k, r in base.items():
        if k in done:
            continue
        if (k[1], k[2]) in broken:
            if not CODE2:
                jobs.append(("full", k))
        else:
            s = sc3.get(k)
            if CODE2 and s and s.get("canon") is not True and s.get("canon_cls") != "nosig":
                jobs.append(("code", k))
    if LIMIT:
        jobs = jobs[:LIMIT]
    print("%s stage E: full %d, code-only %d (done %d) cap $%.0f" % (MODEL, sum(1 for j in jobs if j[0] == "full"),
                                                                     sum(1 for j in jobs if j[0] == "code"), len(done), CAP), flush=True)
    lock = threading.Lock(); fo = open(OUT, "a"); st = collections.Counter(); spent = [0.0]

    def work(job):
        mode, k = job
        if spent[0] > CAP:
            with lock:
                st["skipped-cap"] += 1
            return
        r = base[k]; s = sc3.get(k) or {}
        o = {"model": k[0], "source": k[1], "task": k[2], "stage": "E", "mode": mode, "accepted": False,
             "old_status": r.get("status"), "old_canon": s.get("canon"), "old_rel": s.get("rel")}
        asker = H.Asker(MODEL)
        try:
            parts = H.task_parts(k[1], k[2]); head = O.head(parts)
            if mode == "full":
                gen, _raw = BR.gen_spec_raw(parts, head, Tr(asker))
            else:
                gen = (s.get("spec") or "").strip() or r.get("gen_spec")     # what the old accepted program stated
            o["gen_spec"] = gen
            if not gen:
                o["status"] = "no-spec"
            else:
                code, att = code_loop_locked(parts, head, gen, asker)
                o["attempts"] = att
                if any(a.get("out") == "API-FAILURE" for a in att):
                    o["api_fail"] = True
                if code is None:
                    o["status"] = "no-verify"
                else:
                    rel, rc, _ = O.rel2(parts, gen, code); det, dc, _ = O.det2(parts, gen, code)
                    o.update({"status": "accepted", "accepted": True, "code": code, "rel": rel, "rel_cls": rc, "det": det, "det_cls": dc})
        except Exception as e:
            o["error"] = str(e)[:300]; o.setdefault("status", "error")
        o["cost"] = asker.summ()
        if asker.calls and asker.empties >= asker.calls:
            o["api_fail"] = True
        with lock:
            spent[0] += o["cost"].get("cost_usd", 0)
            fo.write(json.dumps(o) + NL); fo.flush()
            st["n"] += 1; st["acc"] += o["accepted"]; st["rel"] += (o.get("rel") is True); st["old_acc"] += (r.get("status") == "accepted")
            st["old_valid"] += (s.get("canon") is True); st["old_rel"] += (s.get("canon") is True and s.get("rel") is True)
            print("  %-4s %-36s %-9s rel %-5s (was %s, canonical %s) calls %d $%.3f | n %d/%d accepted %d (old %d, valid %d) correct %d (old %d) $%.2f" % (
                mode, k[2][:36], o.get("status"), o.get("rel"), r.get("status"), s.get("canon"), o["cost"]["calls"], o["cost"].get("cost_usd", 0),
                st["n"], len(jobs), st["acc"], st["old_acc"], st["old_valid"], st["rel"], st["old_rel"], spent[0]), flush=True)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "6"))) as ex:
        list(ex.map(work, jobs))
    print("DONE %s %s spent $%.2f" % (MODEL, dict(st), spent[0]), flush=True)
