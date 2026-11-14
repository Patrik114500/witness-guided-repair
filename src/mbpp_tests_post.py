"""Post-pass: recompute MBPP tests_pass over mbpp_ours2 accepted records (code is stored) with the
FIXED oracle: rename the json's method name -> the GT/src method name inside the test snippets,
assert -> expect, execute with dafny run. No LLM calls. Output: /tmp/mbpp_tests_post.jsonl."""
import os, sys, re, json, glob
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import mbpp_ours as M

db = json.load(open(glob.glob(M.D + "/*.json")[0]))
OUT = "/tmp/mbpp_tests_post.jsonl"
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: done.add(json.loads(l)["task"])
        except Exception: pass
fout = open(OUT, "a")
np = nf = nn = 0
for l in open("/tmp/mbpp_ours2.jsonl"):
    try: r = json.loads(l)
    except Exception: continue
    if r.get("status") != "accepted" or not r.get("code") or r["task"] in done:
        continue
    tid = r["task"].replace("task_id_", "")
    t = db.get(tid); gp = M.gt_parts(tid, "")
    if not t or not gp:
        continue
    head, parts = gp
    sig = V.parse_sig(parts["vc-spec"])
    src_name = sig[0]
    jm = re.search(r"method\s+(\w+)", t.get("method_signature", ""))
    json_name = jm.group(1) if jm else src_name
    tp = None
    try:
        tests = list(t.get("test_cases", {}).values())[:3]
        body = "\n".join("  { %s }" % re.sub(r"\b%s\b" % re.escape(json_name), src_name, x)
                         .replace("assert ", "expect ").replace("\n", " ") for x in tests)
        src = V.assemble(parts, r["code"]) + "\nmethod Main() {\n" + body + "\n}\n"
        out = V.drun(src)
        if "expectation violation" in out:
            tp = False
        elif "Error" in out:
            tp = None
        else:
            tp = True
    except Exception:
        tp = None
    fout.write(json.dumps({"task": r["task"], "tests_pass": tp}) + "\n"); fout.flush()
    np += tp is True; nf += tp is False; nn += tp is None
    done.add(r["task"])
print("DONE pass=%d fail=%d inconclusive=%d" % (np, nf, nn), flush=True)
