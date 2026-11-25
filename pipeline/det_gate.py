"""The determinacy query: one lemma that asks whether a postcondition admits two different outputs for an input."""
import os, sys, re, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import nl_gated_compare as NG

def completeness_determinacy(parts, gen_ens):
    """key-free, solver-based: does the spec admit two different outputs for some input? If yes -> weak.
    Returns 1.0 (determinate/complete), 0.0 (admits spurious output/weak), or None (not checkable)."""
    sig = V.parse_sig(parts["vc-spec"])
    if not sig or not sig[2]: return None
    name, params, (rvar, rt) = sig
    rt = rt.strip()
    ens = V.ensures_list("method _() returns ()\n  " + gen_ens)
    if not ens: return None
    reqs = re.findall(r"requires\s+(.+)", parts["vc-spec"])
    def sub(e, nv): return re.sub(r"\b%s\b" % re.escape(rvar), nv, e)
    plist = ", ".join("%s: %s" % (n, t) for n, t in params)
    lem = V.pre(parts) + "\nlemma Determinacy(%s%sr1: %s, r2: %s)\n" % (plist, ", " if plist else "", rt, rt)
    for r in reqs: lem += "  requires %s\n" % r
    for e in ens: lem += "  requires %s\n" % sub(e, "r1")
    for e in ens: lem += "  requires %s\n" % sub(e, "r2")
    if rt.replace(" ", "").startswith("array<"):
        lem += "  ensures r1.Length == r2.Length && forall i :: 0 <= i < r1.Length ==> r1[i] == r2[i]\n{}\n"
    else:
        lem += "  ensures r1 == r2\n{}\n"
    try:
        ok, _ = V.dverify(lem); return 1.0 if ok else 0.0
    except Exception:
        return None

if __name__ == "__main__":
    M = "qwen2.5-coder:32b"
    tasks = os.environ.get("TASKS", "NpArange,NpArgmax,NpClip,NpSign,NpAbs,NpAdd,NpMaximum,NpSquare").split(",")
    print("%-14s %7s %7s  %s" % ("task", "c_det", "rel", "verdict"))
    hit = miss = fa = 0
    for tsk in tasks:
        fs = glob.glob(V.BENCH + "/numpy_simple/yaml/%s-spec.yaml" % tsk)
        if not fs: continue
        parts = V.load(fs[0]); head = V.sig_head(parts["vc-spec"])
        class C:
            def __init__(s): s.calls=0
            def ask(s,m,p): s.calls+=1; return V.ask(m,p)
        gen = NG.gen_spec(M, parts, head, C())
        if not gen: print("%-14s (no spec)"%tsk); continue
        cd = completeness_determinacy(parts, gen)
        rel = NG.reliable_gt(parts, gen)
        v = ""
        if rel is False and cd == 0.0: v = "CAUGHT"; hit += 1
        elif rel is False: v = "missed (cd=%s)" % cd; miss += 1
        elif rel is True and cd == 0.0: v = "FALSE ALARM"; fa += 1
        elif rel is True: v = "strong ok"
        print("%-14s %7s %7s  %s" % (tsk, cd, rel, v), flush=True)
    print("\ndeterminacy-gate: caught %d | missed %d | false-alarm %d" % (hit, miss, fa))
