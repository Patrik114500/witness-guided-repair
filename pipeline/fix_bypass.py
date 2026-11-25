"""Rescue stage D: big-run accepts (original or rescued) whose accepted code verifies only through a bypass
(assume / {:axiom}, the published pipeline's rules). Such an accept is not a success. The code stage is
re-run from the stored spec with the guarded loop (the bypass is rejected with feedback), with at most 4
attempts, since the unguarded run had already spent at least one.
  MODE=run   : model calls, per MODEL, writes /tmp/fix_rescueD_<model>.jsonl (resumable)
  MODE=score : no model calls, appends the final verdict of every listed task to /tmp/fix_scores.jsonl
               (re-rescued -> scored like any accept; otherwise accepted=False, origin "demote-bypass")
The list of affected tasks is /tmp/inv_cheat2.json (inv_cheat2.py)."""
import os, sys, json, glob, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import nl_gated_compare as NG
import det_gate
import fix_harness as H
import fix_cheat as FC

MODE = os.environ.get("MODE", "run")
LIST = [b for b in json.load(open("/tmp/inv_cheat2.json"))["bigrun"]]
base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
NL = chr(10)

if MODE == "run":
    MODEL = os.environ["MODEL"]
    OUT = "/tmp/fix_rescueD_%s.jsonl" % MODEL.replace(":", "_").replace("/", "_")
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            try:
                r = json.loads(l); done.add((r["model"], r["source"], r["task"]))
            except Exception:
                pass
    tg = [b for b in LIST if b["model"] == MODEL and (b["model"], b["source"], b["task"]) not in done]
    print("%s bypass targets: %d" % (MODEL, len(tg)), flush=True)
    lock = threading.Lock(); fo = open(OUT, "a"); st = collections.Counter()

    def work(b):
        k = (b["model"], b["source"], b["task"]); r = base[k]
        o = {"model": k[0], "source": k[1], "task": k[2], "stage": "D", "rescued": False}
        try:
            parts = H.task_parts(k[1], k[2]); head = V.sig_head(parts["vc-spec"]); gen = r["gen_spec"]
            asker = H.Asker(MODEL)
            code, att = H.gen_code_fixed(parts, head + NL + "    " + gen, asker, iters=4, variant="orig", enforce_ens=None, guard=True)
            o["attempts"] = [{"iter": a["iter"], "verified": a["verified"], "bypass": a.get("bypass"), "out": a["dafny_out"][-160:]} for a in att]
            o["cost"] = asker.summ()
            if code is not None:
                o.update({"rescued": True, "code": code})
        except Exception as e:
            o["error"] = str(e)[:200]
        with lock:
            fo.write(json.dumps(o) + NL); fo.flush(); st["n"] += 1; st["r"] += bool(o["rescued"])
            print("  %-36s %s bypass-rejected=%d $%.3f | %d/%d re-rescued %d" % (k[2][:36], "RESCUED" if o["rescued"] else "fail   ",
                  sum(1 for a in o.get("attempts", []) if a.get("bypass")), (o.get("cost") or {}).get("cost_usd", 0), st["n"], len(tg), st["r"]), flush=True)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "8"))) as ex:
        list(ex.map(work, tg))
    print("DONE %s re-rescued %d of %d" % (MODEL, st["r"], st["n"]), flush=True)
else:
    D = {}
    for f in glob.glob("/tmp/fix_rescueD_*.jsonl"):
        for l in open(f):
            try:
                r = json.loads(l); D[(r["model"], r["source"], r["task"])] = r
            except Exception:
                pass
    fo = open("/tmp/fix_scores.jsonl", "a"); st = collections.Counter()
    for b in LIST:
        k = (b["model"], b["source"], b["task"]); r = base[k]; d = D.get(k)
        o = {"model": k[0], "source": k[1], "task": k[2]}
        if d and d.get("rescued") and not FC.cheats(d["code"], "dafny"):
            parts = H.task_parts(k[1], k[2]); sig = V.parse_sig(parts["vc-spec"]); gen = r.get("gen_spec") or ""
            gen_ens = V.ensures_list("method _() returns ()" + NL + "  " + gen)
            verb = H.ensures_present(d["code"], gen_ens)
            if verb:
                spec = gen
            else:
                ce = H.method_ensures(d["code"], sig[0]) if sig else None
                spec = (NL + "    ").join("ensures " + e for e in ce) if ce else ""
            o.update({"origin": "rescueD", "accepted": True, "gen_verbatim": verb})
            if not spec.strip():
                o["reliable_gt"] = False; o["determinacy"] = 0.0
            else:
                o["reliable_gt"] = NG.reliable_gt(parts, spec)
                try:
                    o["determinacy"] = det_gate.completeness_determinacy(parts, spec)
                except Exception:
                    o["determinacy"] = None
        else:
            o.update({"origin": "demote-bypass", "accepted": False, "pending": d is None})
        st[(o["origin"], str(o.get("reliable_gt")))] += 1
        fo.write(json.dumps(o) + NL)
    fo.close()
    print("stage D scored:", dict(st), "| not yet re-run:", sum(1 for b in LIST if (b["model"], b["source"], b["task"]) not in D))
