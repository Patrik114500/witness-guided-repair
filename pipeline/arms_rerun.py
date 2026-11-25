"""The three replace arms of the big run (mined invariants, LLM judge, determinacy flag), re-run UNCHANGED
(big_run.iterated_repair, ITERS=5, REPAIR_ROUNDS=5 as in the big run) on the accepts whose specification changed after
the big run (stage E re-runs with the repaired header, later rescues, specifications re-read from the program). The
big run's stored proposals were made for the original specification and do not apply to these. Start: the CURRENT
accepted specification and program (fix_state5.load5). The header is the robust one (fix_oracle.head), and
V.sig_head is patched as in stage E (fix_rerun_e.py).
Env: MODEL, WORKERS, CAP (USD), OUT (default /tmp/arms_rerun_<model>.jsonl). Resumable."""
import os, sys, json, threading, collections
os.environ.setdefault("ITERS", "5"); os.environ.setdefault("REPAIR_ROUNDS", "5")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_hdr as HDR
import fix_oracle as O
import fix_state, fix_state5
import big_run as BR
from concurrent.futures import ThreadPoolExecutor

_old_sig_head = V.sig_head


def _sig_head(vs):
    h = HDR.parse(vs)
    return HDR.head_text(h) if h else _old_sig_head(vs)


V.sig_head = _sig_head
NL = chr(10)
MODEL = os.environ["MODEL"]
TAG = MODEL.replace(":", "_").replace("/", "_")
OUT = os.environ.get("OUT", "/tmp/arms_rerun_%s.jsonl" % TAG)
CAP = float(os.environ.get("CAP", "100"))
S0 = fix_state.load(); E = fix_state5.load_E(); S = fix_state5.load5()
sc = {(r["model"], r["source"], r["task"]): r for r in (json.loads(l) for l in open("/tmp/fix_scores6.jsonl"))}
pos = json.load(open("/tmp/posable.json"))
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            r = json.loads(l)
            if r.get("status") != "error":
                done.add((r["model"], r["source"], r["task"], H.nows(r.get("spec_before"))))
        except Exception:
            pass
targets = []
for k, v in S.items():
    if k[0] != MODEL or not v["accepted"] or v["rel"] is None or not pos.get("%s|%s" % (k[1], k[2])):
        continue
    in_common = (S0.get(k, {}).get("origin") == "orig" and k not in E and sc.get(k, {}).get("canon") is True and not sc.get(k, {}).get("respec"))
    if in_common or (k[0], k[1], k[2], H.nows(v["spec"])) in done:
        continue
    targets.append(k)
print("%s: %d accepts with a changed specification to run (already done %d), cap $%.0f" % (MODEL, len(targets), len(done), CAP), flush=True)
lock = threading.Lock(); spent = [0.0]; st = collections.Counter()
fout = open(OUT, "a")


def work(k):
    if spent[0] > CAP:
        with lock:
            st["skipped-cap"] += 1
        return
    v = S[k]
    o = {"model": k[0], "source": k[1], "task": k[2], "spec_before": v["spec"], "origin": v["origin"]}
    tr = BR.Tracker(MODEL)
    try:
        parts = H.task_parts(k[1], k[2])
        head = O.head(parts)
        for arm, name in (("ours", "arm_ours"), ("judge", "arm_judge"), ("det", "arm_determinacy")):
            o[name] = BR.iterated_repair(parts, head, v["spec"], v["code"], tr, arm)
        o["status"] = "ok"
    except Exception as e:
        o["status"] = "error"; o["error"] = str(e)[:300]
    o["cost"] = tr.summ()
    with lock:
        spent[0] += o["cost"].get("cost_usd", 0)
        fout.write(json.dumps(o) + NL); fout.flush()
        st["n"] += 1; st[o["status"]] += 1
        for a in ("arm_ours", "arm_judge", "arm_determinacy"):
            st["changed:" + a] += bool((o.get(a) or {}).get("spec_repair_rounds"))
        print("  %-36s %-6s rounds %s/%s/%s $%.3f | n %d/%d spent $%.2f" % (
            k[2][:36], o["status"], (o.get("arm_ours") or {}).get("spec_repair_rounds"), (o.get("arm_judge") or {}).get("spec_repair_rounds"),
            (o.get("arm_determinacy") or {}).get("spec_repair_rounds"), o["cost"].get("cost_usd", 0), st["n"], len(targets), spent[0]), flush=True)


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "6"))) as ex:
    list(ex.map(work, targets))
print("DONE %s %s spent $%.2f" % (MODEL, dict(st), spent[0]), flush=True)
