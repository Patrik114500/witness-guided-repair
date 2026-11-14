"""POSITIVE CONTROLS for the mis-specification branch (sensitivity validation).
MODE=seeded : take RELIABLE accepts, inject a spec fault (operator/offset mutation), regenerate code
              against the wrong spec (it will verify), then run the differential arm:
              detect? arbiter correct? rewrite restores entailment?
MODE=mbpp   : the 6 natural positives (verified accepts that FAIL the dataset's tests); success metric:
              tests pass after rewrite+recode.
Env: MODE, LOCAL, ARBITER, N, OUT."""
import os, sys, re, json, glob, random
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import nl_gated_compare as NG
import witness_repair as WR
import big_run as BR
import misspec2 as M2
random.seed(23)

MODE = os.environ.get("MODE", "seeded")
LOCAL = os.environ.get("LOCAL", "qwen2.5-coder:32b")
ARB = os.environ.get("ARBITER", "claude:claude-opus-5-5")
N = int(os.environ.get("N", "12"))
OUT = os.environ.get("OUT", "/tmp/misspec_controls.jsonl")

MUTS = [(" >= ", " > "), (" <= ", " < "), (" > ", " >= "), (" < ", " <= "),
        (" + 1", " + 2"), ("+1", "+2"), (" - 1", ""), (" == ", " != ")]


def mutate_spec(parts, gen):
    cands = []
    for a, b in MUTS:
        if a in gen:
            m = gen.replace(a, b, 1)
            if m != gen and WR.spec_syntax_ok(parts, m)[0]:
                cands.append(m)
    random.shuffle(cands)
    return cands[0] if cands else None


def differential_arm(parts, head, spec, code, trL, trA):
    """returns dict: disagreement?, arbiter, rewritten spec (if any)."""
    sig = V.parse_sig(parts["vc-spec"])
    name, params, (rvar, rt) = sig
    rt0 = rt.replace(" ", "")
    inputs = WR._valid_inputs(parts, params, tries=10)[:5]
    if not inputs:
        return {"skip": "noinput"}
    o_spec = M2.run_on(parts, code, name, params, rt0, inputs)
    directs = []
    for _ in range(2):
        b = M2.nl_direct_impl(trL, parts, head)
        if b:
            directs.append(M2.run_on(parts, b, name, params, rt0, inputs))
    if not directs:
        return {"skip": "nodirect"}
    dis = None
    for i in sorted(o_spec):
        dvals = [d.get(i) for d in directs if i in d]
        if dvals and all(v == dvals[0] for v in dvals) and dvals[0] != o_spec[i]:
            dis = (inputs[i][0], o_spec[i], dvals[0]); break
    out = {"disagreement": bool(dis)}
    if not dis:
        return out
    pyv, os_, od_ = dis
    q = ("Description of a method:\n%s\n\nTwo programs disagree on input (%s): program A returns %s, "
         "program B returns %s. According to the description, which is correct? Answer exactly A or B "
         "on the first line." % (parts.get("vc-description", "")[:900],
                                 ", ".join("%s=%s" % kv for kv in pyv.items()), os_, od_))
    ans = (trA.ask(q, "arb").strip().splitlines() or [""])[0].upper()
    out["arbiter"] = ans[:4]
    if "B" in ans and not ans.startswith("A"):
        p = ("This Dafny postcondition makes verified code return %s on input (%s), but the correct "
             "result per the description is %s.\nDescription:\n%s\nOld postcondition:\n%s\nSignature:\n%s\n"
             "Write a corrected postcondition. Return ONLY valid Dafny ensures lines."
             % (os_, ", ".join("%s=%s" % kv for kv in pyv.items()), od_,
                parts.get("vc-description", "")[:800], spec, head))
        out["rewrite"] = WR.extract_ensures(parts, trA.ask(p, "rew"))
    return out


def run_seeded():
    rows = []
    for l in open("/tmp/big_run_local.jsonl.bak_20261113_003548"):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if (r.get("status") == "accepted" and r.get("model") == LOCAL and r.get("gen_spec")
                and r.get("reliable_gt") is True):
            rows.append(r)
    random.shuffle(rows)
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            try: done.add(json.loads(l)["task"])
            except Exception: pass
    fout = open(OUT, "a")
    cnt = 0
    for r in rows:
        if cnt >= N or r["task"] in done:
            continue
        try:
            parts = V.load(V.BENCH + "/%s/yaml/%s" % (r["source"], r["task"]))
            sig = V.parse_sig(parts["vc-spec"])
            if not sig or not sig[2] or sig[2][1].replace(" ", "") not in ("int", "nat", "bool"):
                continue
            head = V.sig_head(parts["vc-spec"])
            mspec = mutate_spec(parts, r["gen_spec"])
            if not mspec:
                continue
            # sanity: the mutated spec must NOT entail GT (otherwise not a real fault)
            if NG.reliable_gt(parts, mspec) is True:
                continue
            trL = BR.Tracker(LOCAL); trA = BR.Tracker(ARB)
            code2, att = BR.gen_code_raw(parts, head + "\n    " + mspec, trL)
            rec = {"task": r["task"], "mutated": True, "code_verified": code2 is not None}
            if code2:
                d = differential_arm(parts, head, mspec, code2, trL, trA)
                rec.update(d)
                if d.get("rewrite"):
                    c3, _ = BR.gen_code_raw(parts, head + "\n    " + d["rewrite"], trL)
                    rec["reverified"] = c3 is not None
                    rec["rel_after"] = NG.reliable_gt(parts, d["rewrite"]) if c3 else None
            fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(r["task"]); cnt += 1
            print("  %-26s codeV=%s dis=%s arb=%s relA=%s" % (
                r["task"][:26], rec.get("code_verified"), rec.get("disagreement"),
                rec.get("arbiter", ""), rec.get("rel_after")), flush=True)
        except Exception as e:
            print("  err %s %s" % (r["task"][:20], str(e)[:70]), flush=True)
    rs = [json.loads(l) for l in open(OUT)]
    cv = [x for x in rs if x.get("code_verified")]
    det = sum(1 for x in cv if x.get("disagreement"))
    fixed = sum(1 for x in cv if x.get("rel_after") is True)
    print("SEEDED SUMMARY: controls %d (code-verified %d) | DETECTED %d | REPAIRED-to-entailment %d"
          % (len(rs), len(cv), det, fixed), flush=True)
    print("DONE", flush=True)


def run_mbpp():
    import mbpp_ours as M
    db = json.load(open(glob.glob(M.D + "/*.json")[0]))
    tp = {}
    for l in open("/tmp/mbpp_tests_post.jsonl"):
        x = json.loads(l); tp[x["task"]] = x["tests_pass"]
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            try: done.add(json.loads(l)["task"])
            except Exception: pass
    fout = open(OUT, "a")
    for l in open("/tmp/mbpp_ours2.jsonl"):
        r = json.loads(l)
        if r.get("status") != "accepted" or tp.get(r["task"]) is not False or r["task"] in done:
            continue
        try:
            tid = r["task"].replace("task_id_", "")
            t = db[tid]; head, parts = M.gt_parts(tid, "")
            parts["vc-description"] = t.get("task_description", "")
            sig = V.parse_sig(parts["vc-spec"])
            if not sig or not sig[2] or sig[2][1].replace(" ", "") not in ("int", "nat", "bool"):
                fout.write(json.dumps({"task": r["task"], "skip": "rettype"}) + "\n"); continue
            trL = BR.Tracker(LOCAL); trA = BR.Tracker(ARB)
            d = differential_arm(parts, head, r["gen_spec"], r["code"], trL, trA)
            rec = {"task": r["task"], "natural": True}
            rec.update(d)
            if d.get("rewrite"):
                c3, _ = BR.gen_code_raw(parts, head + "\n    " + d["rewrite"], trL)
                rec["reverified"] = c3 is not None
                if c3:
                    # success metric: dataset tests after repair
                    sname = sig[0]
                    jm = re.search(r"method\s+(\w+)", t.get("method_signature", ""))
                    jn = jm.group(1) if jm else sname
                    tests = list(t.get("test_cases", {}).values())[:3]
                    body = "\n".join("  { %s }" % re.sub(r"\b%s\b" % re.escape(jn), sname, x)
                                     .replace("assert ", "expect ").replace("\n", " ") for x in tests)
                    o = V.drun(V.assemble(parts, c3) + "\nmethod Main() {\n" + body + "\n}\n")
                    rec["tests_after"] = False if "expectation violation" in o else (None if "Error" in o else True)
            fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(r["task"])
            print("  %-16s dis=%s arb=%s rew=%s testsA=%s" % (
                r["task"], rec.get("disagreement"), rec.get("arbiter", ""),
                bool(rec.get("rewrite")), rec.get("tests_after")), flush=True)
        except Exception as e:
            print("  err %s %s" % (r["task"][:16], str(e)[:70]), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    (run_mbpp if MODE == "mbpp" else run_seeded)()
