"""Mis-specification arm v2: NL-DIRECT DIFFERENTIAL detection + strong arbiter on disagreements only.
1. Generate 2 implementations from the NL ONLY (no spec -> no proof burden, cheap & easy).
2. Run them and the accepted (spec-constrained) code on precondition-valid inputs.
3. Agreement everywhere -> spec fine. Disagreement -> evidence (x, o_spec, o_direct) -> STRONG arbiter
   answers the EASY question: 'two programs disagree on x; which output matches the description?'
4. If the spec side is wrong -> strong-model rewrite with the counterexample -> gate+code+verify (local).
Safety: keep-on-fail everywhere. Env: LOCAL (gen model), ARBITER (strong), N, OUT."""
import os, sys, re, json
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V
import nl_gated_compare as NG
import witness_repair as WR
import big_run as BR

LOCAL = os.environ.get("LOCAL", "qwen2.5-coder:32b")
ARB = os.environ.get("ARBITER", "claude:claude-opus-5-5")
N = int(os.environ.get("N", "30"))
OUT = os.environ.get("OUT", "/tmp/misspec2.jsonl")


def nl_direct_impl(tr, parts, head):
    """implement from the DESCRIPTION only (no spec shown) -- compile+run quality, no proof needed."""
    nl = parts.get("vc-description", "").strip()
    p = ("Implement this Dafny method from the description. NO ensures/requires needed, no proofs, "
         "just a correct implementation that compiles. Return ONLY a ```dafny code block.\n\n"
         "Signature:\n%s\n\nDescription:\n%s\n" % (head, nl[:1200]))
    for _ in range(2):
        block = V.code_of(tr.ask(p, "nl_direct"))
        if not block:
            continue
        # compile check (no verification)
        src = V.pre(parts) + "\n" + block + "\nmethod Main() { }\n"
        out = V.drun(src)
        if "Error" not in out:
            return block
        p += "\nPrevious attempt had errors:\n" + out[:500] + "\nFix and return ONLY a dafny block."
    return None


def run_on(parts, code, name, params, rt0, inputs):
    if rt0 in ("array<int>", "seq<int>"):
        return WR._run_struct(parts, code, params, inputs, name, rt0)
    pb = []
    for i, (pyv, decls) in enumerate(inputs):
        args = ", ".join(pn for pn, _ in params)
        pb.append('  { %s var r := %s(%s); print "I%d:", r, "\\n"; }' % (decls, name, args, i))
    o = V.drun(V.assemble(parts, code) + "\nmethod Main() {\n" + "\n".join(pb) + "\n}\n")
    res = {}
    for i, _ in enumerate(inputs):
        m = re.search(r"I%d:(-?\d+|true|false)" % i, o)
        if m:
            g = m.group(1); res[i] = (g == "true") if rt0 == "bool" else int(g)
    return res


def main():
    rows = []
    for l in open("/tmp/big_run_local.jsonl.bak_20261113_003548"):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("status") != "accepted" or r.get("model") != LOCAL or not r.get("gen_spec"):
            continue
        aw = r.get("arm_witness") or {}
        if aw.get("n_rounds", 0) > 0:
            continue
        rows.append(r)
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
            if not sig or not sig[2]:
                continue
            name, params, (rvar, rt) = sig
            rt0 = rt.replace(" ", "")
            if rt0 not in ("int", "nat", "bool"):
                continue
            code = None
            for a in r.get("code_attempts", []):
                if a.get("verified"):
                    code = a["code"]
            if not code:
                continue
            head = V.sig_head(parts["vc-spec"])
            trL = BR.Tracker(LOCAL)
            inputs = WR._valid_inputs(parts, params, tries=10)[:5]
            if not inputs:
                continue
            o_spec = run_on(parts, code, name, params, rt0, inputs)
            # two NL-direct implementations
            directs = []
            for _ in range(2):
                b = nl_direct_impl(trL, parts, head)
                if b:
                    directs.append(run_on(parts, b, name, params, rt0, inputs))
            if not directs:
                continue
            # find a disagreement where the direct impls AGREE with each other but differ from spec-code
            dis = None
            for i in sorted(o_spec):
                dvals = [d.get(i) for d in directs if i in d]
                if dvals and all(v == dvals[0] for v in dvals) and dvals[0] != o_spec[i]:
                    dis = (inputs[i][0], o_spec[i], dvals[0]); break
            rec = {"task": r["task"], "rel_before": r.get("reliable_gt"), "disagreement": bool(dis)}
            if dis:
                pyv, os_, od_ = dis
                trA = BR.Tracker(ARB)
                q = ("Description of a method:\n%s\n\nTwo programs disagree on input (%s): "
                     "program A returns %s, program B returns %s. According to the description, which "
                     "is correct? Answer exactly A or B on the first line."
                     % (parts.get("vc-description", "")[:900],
                        ", ".join("%s=%s" % kv for kv in pyv.items()), os_, od_))
                ans = trA.ask(q, "diff_arbiter").strip().splitlines()[0].upper() if True else ""
                rec["arbiter"] = ans[:3]
                if "B" in ans and "A" not in ans[:2]:  # spec-side (A) judged wrong
                    g2 = None
                    p = ("This Dafny postcondition leads verified code to return %s on input (%s), but the "
                         "correct result per the description is %s.\nDescription:\n%s\nOld postcondition:\n%s\n"
                         "Signature:\n%s\nWrite a corrected postcondition. Return ONLY valid Dafny ensures lines."
                         % (os_, ", ".join("%s=%s" % kv for kv in pyv.items()), od_,
                            parts.get("vc-description", "")[:800], r["gen_spec"], head))
                    g2 = WR.extract_ensures(parts, trA.ask(p, "diff_rewrite"))
                    rec["rewritten"] = bool(g2)
                    if g2:
                        c2, att = BR.gen_code_raw(parts, head + "\n    " + g2, trL)
                        rec["reverified"] = c2 is not None
                        rec["rel_after"] = NG.reliable_gt(parts, g2) if c2 else None
                rec["arb_cost"] = trA.summ()["cost_usd"]
            fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(r["task"]); cnt += 1
            print("  %-26s relB=%-5s dis=%-5s arb=%-3s rew=%s rev=%s relA=%s" % (
                r["task"][:26], rec.get("rel_before"), rec.get("disagreement"), rec.get("arbiter", ""),
                rec.get("rewritten"), rec.get("reverified"), rec.get("rel_after")), flush=True)
        except Exception as e:
            print("  err %s %s" % (r["task"][:20], str(e)[:70]), flush=True)
    rs = [json.loads(l) for l in open(OUT)]
    dis = [x for x in rs if x.get("disagreement")]
    fa = sum(1 for x in dis if x.get("rel_before") is True and "B" in str(x.get("arbiter", "")))
    fixed = sum(1 for x in rs if x.get("rel_before") is False and x.get("rel_after") is True)
    broke = sum(1 for x in rs if x.get("rel_before") is True and x.get("rel_after") is False)
    print("SUMMARY: checked %d | differential-disagreement %d | spec-judged-wrong false-alarms %d | fixed %d broke %d"
          % (len(rs), len(dis), fa, fixed, broke), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
