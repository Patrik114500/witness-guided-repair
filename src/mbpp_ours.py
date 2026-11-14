"""Run OUR pipeline (NL->spec->code->verify + witness arm) on MBPP-DFY (Misu et al., FSE'24 dataset,
also used by Clover) -- second external benchmark anchor. NL from the task json, GT spec from src/*.dfy
(oracle), plus the dataset's own test cases as an independent oracle.
Env: MODEL, OUT. Resumable."""
import os, sys, re, json, glob
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import nl_gated_compare as NG
import big_run as BR

D = os.path.expanduser("~/clover/dataset/MBPP-DFY-153")
MODEL = os.environ.get("MODEL", "claude:claude-haiku-4-5")
OUT = os.environ.get("OUT", "/tmp/mbpp_ours.jsonl")

db = json.load(open(glob.glob(D + "/*.json")[0]))
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            done.add(json.loads(l)["task"])
        except Exception:
            pass
fout = open(OUT, "a")


def gt_parts(tid, sig_json):
    f = D + "/src/task_id_%s.dfy" % tid
    if not os.path.exists(f):
        return None
    strong = open(f).read()
    m = re.search(r"(method\s+\w+\s*\([^)]*\)\s*returns\s*\([^)]*\)(?:\s*requires[^\n]*)*)", strong)
    if not m:
        return None
    head = m.group(1).rstrip()
    last_kw = max(strong.rfind("ensures"), strong.rfind("requires"))
    bpos = strong.find("{", last_kw) if last_kw >= 0 else -1
    spec_part = strong[:bpos] if bpos > 0 else strong
    gt_ens = V.ensures_list(spec_part)
    if not gt_ens:
        return None
    parts = {"vc-preamble": "", "vc-helpers": "", "vc-code": "", "vc-postamble": "",
             "vc-description": "", "vc-spec": head + "\n  " + "\n  ".join("ensures " + e for e in gt_ens)}
    return head, parts


def test_oracle(parts, code, tests):
    """independent oracle: EXECUTE the dataset's own test cases against the accepted code
    (assert -> expect, dafny run; assert would require static PROOF from the weak spec)."""
    try:
        body = "\n".join("  { %s }" % t.replace("assert ", "expect ").replace("\n", " ")
                         for t in list(tests.values())[:3])
        src = V.assemble(parts, code) + "\nmethod Main() {\n" + body + "\n}\n"
        out = V.drun(src)
        if "expectation violation" in out:
            return False
        if "Error" in out:
            return None  # test harness didn't compile -> inconclusive
        return True
    except Exception:
        return None


def main():
    n = 0
    for tid, t in sorted(db.items(), key=lambda kv: int(kv[0])):
        name = "task_id_" + tid
        if name in done:
            continue
        gp = gt_parts(tid, t.get("method_signature", ""))
        rec = {"task": name, "model": MODEL}
        if not gp:
            rec["status"] = "no-gt"
        else:
            head, parts = gp
            parts["vc-description"] = t.get("task_description", "")
            tr = BR.Tracker(MODEL)
            try:
                gen, _ = BR.gen_spec_raw(parts, head, tr)
                rec["gen_spec"] = gen
                if not gen:
                    rec["status"] = "no-spec"
                else:
                    code, attempts = BR.gen_code_raw(parts, head + "\n    " + gen, tr)
                    rec["accepted"] = code is not None
                    if code is None:
                        rec["status"] = "no-verify"
                    else:
                        rec["status"] = "accepted"
                        rec["code"] = code
                        rec["reliable_gt"] = NG.reliable_gt(parts, gen)
                        rec["tests_pass"] = test_oracle(parts, code, t.get("test_cases", {}))
                        rec["arm_witness"] = BR.witness_arm(parts, head, gen, code, tr)
                rec["cost"] = tr.summ()
            except Exception as e:
                rec["status"] = "error"; rec["error"] = str(e)[:150]
        fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(name); n += 1
        aw = rec.get("arm_witness", {})
        print("  %-14s %-9s rel=%s tests=%s wit=%s/%s $%.3f" % (
            name, rec.get("status"), rec.get("reliable_gt"), rec.get("tests_pass"),
            aw.get("n_rounds"), aw.get("benign_nondet"), rec.get("cost", {}).get("cost_usd", 0)), flush=True)
    print("DONE %d" % n, flush=True)

if __name__ == "__main__":
    main()
