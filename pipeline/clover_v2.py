"""CloverBench head-to-head, re-measured fairly (2026-11-18).
  MODE=ours   : our loop. Spec generation unchanged (big_run.gen_spec_raw + syntax gate); code loop from
                fix_harness (loop-neutral prompt, dedupe, robust ask, generated ensures must stay verbatim).
  MODE=clover : Clover's own generators with the SAME model for both steps: gen_spec_from_doc, then
                gen_body_from_spec (feedback_turn=3, which only checks that the body COMPILES), then Clover's
                spec-soundness step: the body must verify against Clover's generated spec. That is Clover's
                generation core; its remaining consistency checks could only remove accepts, so the number
                of correctly verified tasks measured here is an upper bound for fully gated Clover.
Scoring is identical for both pipelines:
  canon_ok    : the accepted body re-verifies under the benchmark's own signature + requires with the
                generated ensures (a pipeline may not assume more than the task allows);
  reliable_gt : the generated ensures imply the benchmark's strong spec (multi-return handled).
A task counts as correctly verified when accepted, canon_ok and reliable_gt all hold.
Env: MODE, MODEL, OUT, SHARD=i/N, SEED_TAG (free label). Resumable by task."""
import os, sys, re, json, glob, time
sys.path.insert(0, os.path.expanduser("~/clover/clover"))
sys.path.insert(0, os.path.expanduser("~/clover/shim"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/clover"))
MODE = os.environ.get("MODE", "ours")
MODEL = os.environ.get("MODEL", "aoai:gpt-4o")
os.environ["SPEC_MODEL"] = MODEL; os.environ["BODY_MODEL"] = MODEL; os.environ["SHIM_MODEL"] = MODEL
import vericode_compete as V
import big_run as BR
import clover_gated as CG
import fix_harness as H
import fix_canon as C
import det_gate

OUT = os.environ.get("OUT", "/tmp/clover_v2_%s.jsonl" % MODE)
SHARD = os.environ.get("SHARD", "")
CB = os.path.expanduser("~/clover/dataset/CloverBench/textbook_algo")
NL = chr(10)
names = sorted(os.path.basename(p) for p in glob.glob(CB + "/*") if os.path.isdir(p))
if SHARD:
    i, n = map(int, SHARD.split("/")); names = [x for j, x in enumerate(names) if j % n == i]
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            done.add(json.loads(l)["task"])
        except Exception:
            pass
fout = open(OUT, "a")


def det_safe(parts, gen):
    try:
        m = re.search(r"returns\s*\(([^)]*)\)", parts["vc-spec"])
        if m and m.group(1).count(":") > 1:
            return None                      # the determinacy lemma only handles one return value
        return det_gate.completeness_determinacy(parts, gen)
    except Exception:
        return None


def canon_ok(parts, head, gen, code):
    name = V.parse_sig(parts["vc-spec"])[0]
    cp = C.canonical_program(code, name, head, gen)
    return bool(cp) and H.dverify2(cp)[0]


for name in names:
    if name in done:
        continue
    rec = {"task": name, "model": MODEL, "mode": MODE, "tag": os.environ.get("SEED_TAG", "")}
    a = time.time()
    try:
        t = CG.load_task(name)
        if not t:
            rec["status"] = "no-sig"
        else:
            doc, head, parts = t
            if MODE == "ours":
                tr = BR.Tracker(MODEL)
                gen, _raw = BR.gen_spec_raw(parts, head, tr)
                rec["gen_spec"] = gen
                if not gen:
                    rec["status"] = "no-spec"
                else:
                    asker = H.Asker(MODEL)
                    gen_ens = V.ensures_list("method _() returns ()" + NL + "  " + gen)
                    code, att = H.gen_code_fixed(parts, head + NL + "    " + gen, asker, iters=5, variant="v2", enforce_ens=gen_ens)
                    rec["code_iters"] = len(att); rec["accepted"] = code is not None
                    rec["calls"] = tr.calls + asker.calls
                    if code is None:
                        rec["status"] = "no-verify"; rec["last_out"] = att[-1]["dafny_out"][-300:] if att else ""
                    else:
                        rec["status"] = "accepted"; rec["code"] = code
                        rec["canon_ok"] = canon_ok(parts, head, gen, code)
                        rec["reliable_gt"] = H.reliable_gt_mr(parts, gen)
                        rec["determinacy"] = det_safe(parts, gen)
            else:
                import clover, utils, sglang as sgl
                sgl.reset_calls()
                spec = clover.gen_spec_from_doc(doc, head, CG.DAFNY, feedback_turn=3)
                spec = spec if isinstance(spec, str) else ""
                gen0 = CG.ens_only(spec) if spec else ""
                rec["gen_spec"] = gen0; rec["spec_native"] = spec
                if not gen0:
                    rec["status"] = "no-spec"
                else:
                    res = clover.gen_body_from_spec(spec, CG.DAFNY, feedback_turn=3)
                    ok_gen, body = res if isinstance(res, tuple) else (True, res)
                    rec["calls"] = sgl.get_calls(); rec["compiled"] = bool(ok_gen and body)
                    rec["code"] = body or ""
                    sound = False
                    if rec["compiled"]:
                        # Clover's spec-soundness step, merged correctly: native spec + the body from its
                        # opening brace (their merge_spec_and_body drops the last spec line, which in the
                        # generator's output is the last ensures clause).
                        sp = C.split_method(body, V.parse_sig(parts["vc-spec"])[0])
                        if sp:
                            merged = sp[0] + spec.rstrip() + NL + sp[1]
                            out, err = utils.run_dafny(merged, CG.DAFNY)      # their flags, their 15 s limit
                            sound = utils.is_dafny_verified(str(out)) or H.dverify2(merged)[0]
                    rec["accepted"] = sound
                    if not sound:
                        rec["status"] = "no-verify"
                    else:
                        rec["status"] = "accepted"
                        rec["canon_ok"] = canon_ok(parts, head, gen0, body)
                        rec["reliable_gt"] = H.reliable_gt_mr(parts, gen0)
                        rec["determinacy"] = det_safe(parts, gen0)
    except Exception as e:
        rec["status"] = "error"; rec["error"] = str(e)[:200]
    rec["time_s"] = round(time.time() - a, 1)
    fout.write(json.dumps(rec) + NL); fout.flush(); done.add(name)
    print("  %-7s %-22s %-9s canon=%s rel=%s det=%s calls=%s %.0fs" % (
        MODE, name[:22], rec.get("status"), rec.get("canon_ok"), rec.get("reliable_gt"),
        rec.get("determinacy"), rec.get("calls"), rec["time_s"]), flush=True)
print("DONE", flush=True)
