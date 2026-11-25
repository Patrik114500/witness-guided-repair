"""Independent re-check of the PLAIN given-spec accepts (the numbers that go into result 4). No model calls.
The plain Lean / Verus runs (xlang_v2 + the guarded re-runs of xlang_v3) checked only the theorem statements
and the published bypass rules. The full specification lock (preamble and definition headers kept, every
accept verified again on its own) was introduced later, for the library run. This script applies the same
lock to the plain accepts, so that the headline numbers and the ablation are held to one standard.
  LANG_=lean|verus : /tmp/gs2_<lang>_<tag>_s*.jsonl, with tasks re-run in /tmp/gs3_... taking precedence
  LANG_=dafny      : /tmp/cfs2_<model>.jsonl accepts that exit with 0 (rc probe) plus the continued ones
                     (/tmp/cfs3_<model>.jsonl), re-verified with the published rule
Output: /tmp/plain_lock_<lang>.json"""
import os, sys, re, json, glob, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LANG = os.environ.get("LANG_", "lean")
os.environ.setdefault("MODEL", "aoai:gpt-5")
import vericode_compete as V       # noqa: E402
import fix_harness as H            # noqa: E402
import fix_cheat as FC             # noqa: E402
import boot_given as B             # noqa: E402

NL = chr(10)
W = int(os.environ.get("WORKERS", "6"))
out = {}


def jl(p):
    r = []
    if os.path.exists(p):
        for l in open(p):
            try:
                r.append(json.loads(l))
            except Exception:
                pass
    return r


def sect(src, name):
    m = re.search(r"-- <%s>(.*?)(?:-- </%s>|$)" % (name, name), src, re.S)
    return m.group(1) if m else ""


if LANG in ("lean", "verus"):
    ad = (B.Lean if LANG == "lean" else B.Verus)()
    X = ad.X
    for tag in ["gpt5", "gpt5mini"]:
        g2 = {}
        for f in sorted(glob.glob("/tmp/gs2_%s_%s_s*.jsonl" % (LANG, tag))):
            for r in jl(f):
                g2[r["task"]] = r
        g3 = {}
        for f in sorted(glob.glob("/tmp/gs3_%s_%s_s*.jsonl" % (LANG, tag))):
            for r in jl(f):
                g3[r["task"]] = r
        final = dict(g2); final.update(g3)
        acc = [r for r in final.values() if r.get("status") == "accepted" and r.get("src")]

        def chk(r):
            t = r["task"]; src = r["src"]; why = []
            try:
                if LANG == "lean":
                    src0 = ad.src[t]
                    for name, lab in [("vc-preamble", "preamble"), ("vc-theorems", "theorem")]:
                        if not X.integrity(sect(src0, name), src)[0]:
                            why.append(lab + "-lines-missing")
                    if not X.integrity(NL.join(l for l in sect(src0, "vc-definitions").splitlines() if l.strip() != "sorry"), src)[0]:
                        why.append("definition-header-changed")
                    if FC.cheats(FC.model_written(src, src0), "lean"):
                        why.append("bypass")
                    ok, o = X.verify_lean(src)
                else:
                    pre, post, spec, helpers = ad._p(t)
                    if not X.integrity(spec, src)[0]:
                        why.append("spec-lines-missing")
                    model_part = src.replace(pre, "").replace(post, "").replace(helpers, "") if helpers.strip() else src.replace(pre, "").replace(post, "")
                    if FC.cheats(model_part, "verus"):
                        why.append("bypass")
                    ok, o = X.verify_verus(src)
                if not ok:
                    why.append("not-verified")
            except Exception as e:
                why.append("error:" + str(e)[:80])
            return t, why
        with ThreadPoolExecutor(max_workers=W) as ex:
            res = list(ex.map(chk, acc))
        bad = [(t, w) for t, w in res if w]
        out[tag] = {"tasks": len(final), "accepted": len(acc), "confirmed": len(acc) - len(bad), "rejected": bad}
        print("%s %-9s tasks %d accepted %d confirmed %d rejected %d %s" % (LANG, tag, len(final), len(acc), len(acc) - len(bad), len(bad),
              dict(collections.Counter(x for t, w in bad for x in w))), flush=True)
        for t, w in bad:
            print("      ", t, w)
else:
    rcs = {(m, s, t): rc for m, s, t, rc, w, to in json.load(open("/tmp/rc_probe_cfs.json"))}
    for model in ["aoai:gpt-5", "aoai:gpt-5-mini"]:
        tag = model.replace(":", "_")
        fin = {}
        for r in jl("/tmp/cfs2_%s.jsonl" % tag):
            k = (r["model"], r["source"], r["task"])
            if r.get("success") and r.get("code") and rcs.get(k) == 0:
                fin[k] = r["code"]
        for r in jl("/tmp/cfs3_%s.jsonl" % tag):
            if r.get("success") and r.get("code"):
                fin[(r["model"], r["source"], r["task"])] = r["code"]
        keys = sorted(fin)

        def chk(k):
            parts = H.task_parts(k[1], k[2]); code = fin[k]; why = []
            try:
                if H.nows(parts["vc-spec"].rstrip()) not in H.nows(code):
                    why.append("spec-not-verbatim")
                if FC.cheats(code.replace(parts["vc-spec"].rstrip(), ""), "dafny"):
                    why.append("bypass")
                rc, o = B.rc_verify(V.assemble(parts, code))
                if rc != 0:
                    why.append("exit-%s" % rc)
            except Exception as e:
                why.append("error:" + str(e)[:80])
            return k, why
        with ThreadPoolExecutor(max_workers=W) as ex:
            res = list(ex.map(chk, keys))
        for s in ["verina", "numpy_simple"]:
            L = [(k, w) for k, w in res if k[1] == s]; bad = [(k[2], w) for k, w in L if w]
            out["%s|%s" % (tag, s)] = {"accepted": len(L), "confirmed": len(L) - len(bad), "rejected": bad}
            print("dafny %-16s %-13s accepted %d confirmed %d rejected %d %s" % (tag, s, len(L), len(L) - len(bad), len(bad),
                  dict(collections.Counter(x for t, w in bad for x in w))), flush=True)
            for t, w in bad:
                print("      ", t, w)
json.dump(out, open("/tmp/plain_lock_%s.json" % LANG, "w"), indent=1)
