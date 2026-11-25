"""Oracle v2 (2026-11-18 evening): the entailment check S => G and the determinacy check, with three
artifacts of the first oracle removed. No model calls.

  1. two-state specifications. A generated postcondition that mentions old(..), fresh(..) or unchanged(..)
     cannot be stated in an ordinary lemma: the lemma does not resolve, and the first oracle read that as
     "S does not imply G" (weak). Here such a pair is checked with a TWOSTATE lemma (inputs allocated in the
     old state and unchanged unless the benchmark method lists them under modifies, outputs marked `new`).
  2. several return values. The first oracle kept only the first return variable, so the lemma did not
     resolve (reliability: not assessable, determinacy: flagged). Here all return variables are bound.
  3. ill-formed lemmas. A lemma that does not resolve is "not assessable" (None), not "weak" (False). If the
     postcondition calls a helper that only the accepted program declares, the helper declarations are added
     to the lemma file and the check is repeated.
A lemma that resolves but is not proved within the time limit stays "not proved" (False), as before.

Usage as a script: re-scores every accepted big-run task and every repair arm's final specification.
  OUT  /tmp/fix_scores2.jsonl   one line per accepted task (rel, det, their classes, the old values)
  ARMS /tmp/fix_arms2.jsonl     one line per (task, arm) of the first-pass accepts
"""
import os, sys, re, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import fix_harness as H
import fix_hdr as HDR
import fix_canon as FCN

NL = chr(10)
TWO = re.compile(r"\b(old|fresh|unchanged|allocated)\s*\(")

def hdr(parts):
    return HDR.parse(parts.get("vc-spec", "") or "")


def sig_all(parts):
    """(name, [(param, type)], [(ret, type)]) with every return variable, or None."""
    h = hdr(parts)
    return (h["name"], h["params"], h["rets"]) if h else None


def modifies_text(parts):
    h = hdr(parts)
    return " ".join(h["modifies"]) if h else ""


def is_ref(t):
    return t.replace(" ", "").startswith("array")


def req_lines(parts):
    h = hdr(parts)
    return h["requires"] if h else []


def ref_ensures(parts):
    h = hdr(parts)
    return h["ensures"] if h else []


def head(parts):
    """the benchmark's own signature + requires (+ modifies, decreases), robustly parsed"""
    h = hdr(parts)
    return HDR.head_text(h) if h else V.sig_head(parts["vc-spec"])


def spec_ensures(spec):
    return HDR.ens_split(spec)


def spec_text(exprs):
    return (NL + "    ").join("ensures " + e for e in exprs)


def code_header(parts, code):
    """the header the accepted program itself states for the task's method (robustly parsed), or None"""
    h = hdr(parts)
    if not h or not code:
        return None
    m = re.search(r"\bmethod\s+(?:\{:[^}]*\}\s*)*%s\b" % re.escape(h["name"]), code)
    if not m:
        return None
    return HDR.parse(code[m.start():])


def code_spec(parts, code):
    """specification of record: the ensures clauses the verifier actually checked, read from the accepted
    program (the stored generated text can be a truncated copy of a multi-line clause)"""
    ch = code_header(parts, code)
    return spec_text(ch["ensures"]) if ch else None


def canon_check(parts, code, spec, timeout=90):
    """does the accepted body verify when the method is stated with the benchmark's own header and the
    specification of record? (True / False / None, class)"""
    h = hdr(parts)
    if not h:
        return None, "nosig"
    prog = FCN.canonical_program(code or "", h["name"], HDR.head_text(h), spec_text(spec_ensures(spec)))
    if not prog:
        return None, "nosplit"
    ok, out = H.dverify2(V.assemble(parts, H.dedupe_block(parts, prog)), timeout)
    if ok:
        return True, "ok"
    return False, ("timeout" if out == "TIMEOUT" else ("illformed" if ("resolution/type errors" in out or "parse errors" in out) else "unverified"))


def helpers_from_code(parts, code):
    """top-level non-method declarations of the accepted program that the benchmark file does not declare"""
    block = H.dedupe_block(parts, code or "")
    ms = list(H.DECL_TOP.finditer(block)); out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(block)
        if m.group(1) == "method":
            continue
        out.append(block[m.start():end])
    return "".join(out)


def _classify(ok, out):
    if ok:
        return True, "proved"
    if out == "TIMEOUT":
        return False, "timeout"
    if "resolution/type errors" in out or "parse errors" in out:
        return None, "illformed"
    return False, "unproved"


def _err(out):
    for ln in (out or "").split(NL):
        if "Error" in ln:
            return re.sub(r"^\S+\.dfy\(\d+,\d+\):\s*", "", ln.strip())[:140]
    return ""


def _header(kind, name, parts, params, rets_decl, two):
    """lemma header; two-state form binds outputs as `new` and keeps unmodified inputs unchanged."""
    gen = (hdr(parts) or {}).get("generic", "")
    if not two:
        return "lemma %s%s(%s)" % (name, gen, ", ".join(["%s: %s" % p for p in params] + ["%s: %s" % r for r in rets_decl])) + NL
    mods = modifies_text(parts)
    h = "twostate lemma %s%s(%s)" % (name, gen, ", ".join(["%s: %s" % p for p in params] + ["new %s: %s" % r for r in rets_decl])) + NL
    for pn, pt in params:
        if is_ref(pt) and not re.search(r"\b%s\b" % re.escape(pn), mods):
            h += "  requires unchanged(%s)" % pn + NL
    return h


def strip_two(e, hyp=True):
    """one-state reading of a two-state expression, valid for a method WITHOUT a modifies clause: nothing that
    existed before the call can change, so old(X) == X. In a hypothesis the allocation predicates are dropped
    (a weaker hypothesis can only make the lemma harder to prove)."""
    e = re.sub(r"\bold\s*\(", "(", e)
    if hyp:
        e = re.sub(r"\b(fresh|unchanged|allocated)\s*\(([^()]*)\)", "true", e)
    return e


def gt_lemma(parts, our, orig, extra=""):
    name, params, rets = sig_all(parts)
    if not modifies_text(parts).strip():
        our = [strip_two(e) for e in our]; orig = [strip_two(e, hyp=False) for e in orig]
    two = bool(TWO.search(NL.join(our + orig)))
    lem = _header("gt", "GTcheck", parts, params, rets, two)
    for r in req_lines(parts):
        lem += "  requires %s" % r + NL
    for e in our:
        lem += "  requires %s" % e + NL
    for e in orig:
        lem += "  ensures %s" % e + NL
    lem += "{}" + NL
    return (extra + NL if extra else "") + V.pre(parts) + NL + lem


def rel2(parts, spec, code=None, timeout=90):
    """does the specification of record imply the benchmark's reference postcondition?
    (True / False / None, class, first error if ill-formed)"""
    sg = sig_all(parts)
    if not sg:
        return None, "nosig", ""
    orig = ref_ensures(parts)
    if not orig:
        return None, "no-reference", ""
    our = spec_ensures(spec)
    if not our:
        return False, "no-postcondition", ""
    ok, out = H.dverify2(gt_lemma(parts, our, orig), timeout)
    v, cls = _classify(ok, out)
    if cls == "illformed" and code:
        extra = helpers_from_code(parts, code)
        if extra.strip():
            ok2, out2 = H.dverify2(gt_lemma(parts, our, orig, extra), timeout)
            v2, cls2 = _classify(ok2, out2)
            if cls2 != "illformed":
                return v2, cls2 + "+helpers", ""
    return v, cls, (_err(out) if cls == "illformed" else "")


def det_lemma(parts, ens, extra=""):
    name, params, rets = sig_all(parts)
    if not modifies_text(parts).strip():
        ens = [strip_two(e) for e in ens]
    two = bool(TWO.search(NL.join(ens)))

    def sub(e, tag):
        for rv, _ in rets:
            e = re.sub(r"\b%s\b" % re.escape(rv), rv + tag, e)
        return e
    decl = [(rv + "_1", rt) for rv, rt in rets] + [(rv + "_2", rt) for rv, rt in rets]
    lem = _header("det", "Determinacy", parts, params, decl, two)
    for r in req_lines(parts):
        lem += "  requires %s" % r + NL
    for e in ens:
        lem += "  requires %s" % sub(e, "_1") + NL
    for e in ens:
        lem += "  requires %s" % sub(e, "_2") + NL
    eqs = []
    for rv, rt in rets:
        if rt.replace(" ", "").startswith("array<"):
            eqs.append("(%s_1.Length == %s_2.Length && forall i_d9 :: 0 <= i_d9 < %s_1.Length ==> %s_1[i_d9] == %s_2[i_d9])" % (rv, rv, rv, rv, rv))
        else:
            eqs.append("(%s_1 == %s_2)" % (rv, rv))
    lem += "  ensures %s" % " && ".join(eqs) + NL + "{}" + NL
    return (extra + NL if extra else "") + V.pre(parts) + NL + lem


def det2(parts, spec, code=None, timeout=90):
    """does the specification admit at most one output per input? 1.0 proved / 0.0 not proved / None."""
    sg = sig_all(parts)
    if not sg or not sg[2]:
        return None, "noret", ""
    if modifies_text(parts).strip():
        return None, "modifies", ""
    ens = spec_ensures(spec)
    if not ens:
        return 0.0, "no-postcondition", ""
    ok, out = H.dverify2(det_lemma(parts, ens), timeout)
    v, cls = _classify(ok, out)
    if cls == "illformed" and code:
        extra = helpers_from_code(parts, code)
        if extra.strip():
            ok2, out2 = H.dverify2(det_lemma(parts, ens, extra), timeout)
            v2, cls2 = _classify(ok2, out2)
            if cls2 != "illformed":
                return (1.0 if v2 else 0.0), cls2 + "+helpers", ""
    if v is None:
        return None, cls, _err(out)
    return (1.0 if v else 0.0), cls, ""


ARMS = ["arm_ours", "arm_judge", "arm_determinacy", "arm_witness"]


def load_witness_backfill():
    wb = {}
    for wf in ["/tmp/witness_backfill.jsonl", "/tmp/witness_backfill_arr.jsonl", "/tmp/witness_backfill_arr2.jsonl"]:
        try:
            for l in open(wf):
                w = json.loads(l); wb[(w["model"], w["source"], w["task"])] = w["arm_witness"]
        except Exception:
            pass
    return wb


if __name__ == "__main__":
    import fix_state
    OUT = os.environ.get("OUT", "/tmp/fix_scores3.jsonl"); AOUT = os.environ.get("ARMS", "/tmp/fix_arms3.jsonl")
    S = fix_state.load()
    base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
    wb = load_witness_backfill()
    done = set(); adone = set()
    for path, st in [(OUT, done), (AOUT, adone)]:
        if os.path.exists(path):
            for l in open(path):
                try:
                    r = json.loads(l); st.add((r["model"], r["source"], r["task"], r.get("arm", "")))
                except Exception:
                    pass
    jobs = []
    for k, v in S.items():
        if v["accepted"] and (k[0], k[1], k[2], "") not in done:
            jobs.append(("main", k, None))
    for k, r in base.items():
        if r.get("status") != "accepted":
            continue
        for a in ARMS:
            arm = r.get(a)
            if a == "arm_witness" and k in wb and ((not arm) or wb[k].get("n_rounds", 0) >= (arm or {}).get("n_rounds", 0)):
                arm = wb[k]
            if not arm or "final_spec" not in arm or (k[0], k[1], k[2], a) in adone:
                continue
            jobs.append(("arm", k, (a, arm)))
    print("jobs: main %d arm %d" % (sum(1 for j in jobs if j[0] == "main"), sum(1 for j in jobs if j[0] == "arm")), flush=True)
    lock = threading.Lock(); fo = open(OUT, "a"); fa = open(AOUT, "a"); cnt = collections.Counter()
    pc = {}

    def parts_of(k):
        t = (k[1], k[2])
        if t not in pc:
            pc[t] = H.task_parts(k[1], k[2])
        return pc[t]

    def work(job):
        kind, k, x = job
        try:
            parts = parts_of(k)
            if kind == "main":
                v = S[k]
                rel, rc, re_ = rel2(parts, v["spec"], v["code"])
                det, dc, de_ = det2(parts, v["spec"], v["code"])
                cn, cc = canon_check(parts, v["code"], v["spec"])
                o = {"model": k[0], "source": k[1], "task": k[2], "rel": rel, "rel_cls": rc, "rel_err": re_, "det": det, "det_cls": dc,
                     "det_err": de_, "canon": cn, "canon_cls": cc, "old_rel": v["rel"], "old_det": v["det"], "origin": v["origin"],
                     "two": bool(TWO.search(v["spec"] or "")), "nret": len((sig_all(parts) or (0, 0, []))[2])}
                with lock:
                    fo.write(json.dumps(o) + NL); fo.flush(); cnt[("main", str(v["rel"]), str(rel))] += 1; cnt["n"] += 1
                    if cnt["n"] % 200 == 0:
                        print("  ..%d done" % cnt["n"], flush=True)
            else:
                a, arm = x; r = base[k]
                fs = arm.get("final_spec") or ""; gen = r.get("gen_spec") or ""
                code = arm.get("final_code") or (r.get("code_attempts") or [{}])[-1].get("code")
                changed = H.nows(fs) != H.nows(gen)
                b_rel, b_cls, _ = rel2(parts, gen, (r.get("code_attempts") or [{}])[-1].get("code"))
                if changed:
                    a_rel, a_cls, _ = rel2(parts, fs, code)
                else:
                    a_rel, a_cls = b_rel, b_cls
                o = {"model": k[0], "source": k[1], "task": k[2], "arm": a, "changed": changed, "before": b_rel, "before_cls": b_cls,
                     "after": a_rel, "after_cls": a_cls, "old_before": r.get("reliable_gt"), "old_after": arm.get("reliable_gt_after"),
                     "n_rounds": arm.get("n_rounds", arm.get("spec_repair_rounds")), "benign": arm.get("benign_nondet")}
                with lock:
                    fa.write(json.dumps(o) + NL); fa.flush(); cnt["n"] += 1
                    if cnt["n"] % 200 == 0:
                        print("  ..%d done" % cnt["n"], flush=True)
        except Exception as e:
            with lock:
                cnt["error"] += 1
                print("ERR", k, str(e)[:160], flush=True)

    # arms: the "before" lemma of the same record is recomputed per arm; cache it to save time
    _cache = {}; _rel2 = rel2

    def rel2(parts, spec, code=None, timeout=90, _c=_cache, _f=_rel2):   # noqa: F811 (memoised for the batch)
        key = (parts.get("vc-spec", ""), H.nows(spec), hash(code or ""))
        if key in _c:
            return _c[key]
        r = _f(parts, spec, code, timeout); _c[key] = r
        return r

    with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "72"))) as ex:
        list(ex.map(work, jobs))
    print("DONE", {str(k): v for k, v in cnt.items()}, flush=True)
