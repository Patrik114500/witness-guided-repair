"""The conjunctive acceptance rule applied to the OTHER repair arms' proposals. No model calls.

The three flag-driven arms of the big run (LLM judge, mined invariants, determinacy rewrite) REPLACE the accepted
specification S0 by their proposal P. Here the same stored proposals are accepted the way our repair accepts a
clause: the new specification is S0 AND P, and only if a body verifies under it (the arm's own body, else the
original body) with the benchmark's own header; otherwise the original accept is kept.
A specification that already implied the reference still implies it after a conjunct is added, so this rule cannot
break a correct specification; what it keeps of the arm's repairs is measured here.
Only proposals whose plain replacement counted in the audit (changed, body verifies canonically) are considered.
Output: /tmp/fix_arms_conj.jsonl (one row per accept and arm)."""
import os, sys, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import fix_harness as H
import fix_oracle as O
import fix_hdr as HDR
import fix_canon as FCN
import wit2 as W2

NL = chr(10)
ARMS = ["arm_ours", "arm_judge", "arm_determinacy"]
OUT = "/tmp/fix_arms_conj.jsonl"


def bypass_of(parts, code, spec):
    """the bypasses (assume, {:axiom}, ...) in the block a body contributes when it is stated canonically, by the
    same rule our own repair applies to its bodies (wit2.bypasses). The arms' bodies come from the first big run,
    which had no such filter: gpt-5 'verified' false invariants with `assume false`. None = no canonical program."""
    h = O.hdr(parts)
    if not h or not code:
        return None
    prog = FCN.canonical_program(code, h["name"], HDR.head_text(h), O.spec_text(O.spec_ensures(spec)))
    if not prog:
        return None
    return W2.bypasses(H.dedupe_block(parts, prog))


def jl(p):
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
sc = {(r["model"], r["source"], r["task"]): r for r in jl("/tmp/fix_scores6.jsonl")}
plain = [a for a in jl("/tmp/fix_arms6.jsonl") if a.get("arm") in ARMS and a.get("changed") and a.get("canon_after") is True]
print("valid plain changes: %s" % dict(collections.Counter(a["arm"] for a in plain)), flush=True)
pc = {}; lock = threading.Lock(); st = collections.Counter()


def parts_of(k):
    t = (k[1], k[2])
    if t not in pc:
        pc[t] = H.task_parts(k[1], k[2])
    return pc[t]


def work(a):
    k = (a["model"], a["source"], a["task"]); r = base.get(k); s = sc.get(k)
    o = {"model": k[0], "source": k[1], "task": k[2], "arm": a["arm"], "plain_after": a.get("after")}
    try:
        if not r or not s or s.get("canon") is not True:
            o["skip"] = "no audited base accept"; return o
        parts = parts_of(k)
        arm = r.get(a["arm"]) or {}
        code0 = (r.get("code_attempts") or [{}])[-1].get("code")
        code1 = arm.get("final_code") or code0
        s0 = O.spec_ensures(s.get("spec") or "") or O.spec_ensures(O.code_spec(parts, code0) or "")
        p = O.spec_ensures(arm.get("final_spec") or "")
        seen = set(); both = []
        for e in s0 + p:
            w = H.nows(e)
            if w and w not in seen:
                seen.add(w); both.append(e)
        o["before"] = s.get("rel"); o["added"] = len(both) - len(s0)
        # the plain replacement counted with this body: is it honest by the published bypass rule?
        pb = bypass_of(parts, code1, arm.get("final_spec") or "")
        o["plain_bypass"] = bool(pb); o["plain_bypass_what"] = (pb or [])[:3]
        if not s0 or not p:
            o["skip"] = "no specification text"; return o
        if o["added"] == 0:
            o.update({"conj_valid": False, "why": "the proposal adds nothing to the original specification"}); return o
        sp = O.spec_text(both)
        body = None; skipped = []
        for label, code in (("arm", code1), ("orig", code0)):
            if not code:
                continue
            if bypass_of(parts, code, sp):
                skipped.append(label); continue          # a body that verifies through a bypass is no body
            cn, cc = O.canon_check(parts, code, sp)
            if cn is True:
                body = (label, code); break
        o["bypass_bodies_skipped"] = skipped
        o["conj_valid"] = body is not None
        if body is None:
            o["why"] = "no stored body verifies under the conjunction"; return o
        o["body"] = body[0]
        rel, rc, _ = O.rel2(parts, sp, body[1])
        det, dc, _ = O.det2(parts, sp, body[1])
        o.update({"lemma": rel, "lemma_cls": rc, "det": det})
        # a specification that implied the reference still implies it with a conjunct added
        o["conj_after"] = True if s.get("rel") is True else rel
        o["by_construction"] = bool(s.get("rel") is True and rel is not True)
    except Exception as e:
        o["error"] = str(e)[:200]
    with lock:
        st["n"] += 1
        if st["n"] % 200 == 0:
            print("  ..%d" % st["n"], flush=True)
    return o


with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "48"))) as ex:
    rows = list(ex.map(work, plain))
with open(OUT, "w") as f:
    for o in rows:
        f.write(json.dumps(o) + NL)
for arm in ARMS:
    L = [o for o in rows if o["arm"] == arm and "skip" not in o and "error" not in o]
    v = [o for o in L if o.get("conj_valid")]
    hon = [o for o in L if not o.get("plain_bypass")]
    print("%-16s proposals %4d, of which the arm's body uses a bypass: %d" % (arm, len(L), len(L) - len(hon)), flush=True)
    print("%-16s honest proposals %4d | plain: fixed %3d broke %3d | conjunctive: valid %4d (body: %s) fixed %3d broke %3d by-construction %d | errors %d" % (
        arm, len(hon), sum(1 for o in hon if o.get("before") is False and o.get("plain_after") is True),
        sum(1 for o in hon if o.get("before") is True and o.get("plain_after") is False), len(v),
        dict(collections.Counter(o.get("body") for o in v)),
        sum(1 for o in v if o.get("before") is False and o.get("conj_after") is True),
        sum(1 for o in v if o.get("before") is True and o.get("conj_after") is not True),
        sum(1 for o in v if o.get("by_construction")), sum(1 for o in rows if o["arm"] == arm and "error" in o)), flush=True)
print("DONE", flush=True)
