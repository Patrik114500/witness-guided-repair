"""Read-only: do the bodies that made a conjunctive change valid (conj_arms.py) or a plain arm change valid contain
a bypass (assume, {:axiom}, {:verify false}, {:extern})? The published rule rejects such programs."""
import os, sys, re, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import fix_harness as H

NL = chr(10)
BYPASS = re.compile(r"\bassume\b|\{:axiom\}|\{:verify\s+false\}|\{:extern")


def nocomment(s):
    s = re.sub(r"/\*.*?\*/", " ", s or "", flags=re.S)
    return re.sub(r"//[^" + NL + r"]*", "", s)


base = {(r["model"], r["source"], r["task"]): r for r in H.load_bigrun(set(H.P11))}
rows = [json.loads(l) for l in open("/tmp/fix_arms_conj.jsonl")]
c = collections.Counter(); bad = []
for o in rows:
    if not o.get("conj_valid"):
        continue
    k = (o["model"], o["source"], o["task"]); r = base[k]
    arm = r.get(o["arm"]) or {}
    code0 = (r.get("code_attempts") or [{}])[-1].get("code") or ""
    code = (arm.get("final_code") or code0) if o.get("body") == "arm" else code0
    # the benchmark's own text can contain `assume {:axiom}` stubs; only the model-written body counts
    parts = H.task_parts(k[1], k[2])
    own = nocomment(code)
    for ln in nocomment((parts.get("vc-preamble") or "") + NL + (parts.get("vc-helpers") or "") + NL + (parts.get("vc-postamble") or "")).split(NL):
        if BYPASS.search(ln) and ln.strip():
            own = own.replace(ln.strip(), "")
    hit = bool(BYPASS.search(own))
    c[(o["arm"], "valid")] += 1; c[(o["arm"], "bypass")] += hit
    if hit:
        fixed = o.get("before") is False and o.get("conj_after") is True
        c[(o["arm"], "bypass_and_fixed")] += fixed
        bad.append((o["arm"], k[0].split(":")[-1], k[2][:40], "FIXED" if fixed else "", [m.group(0) for m in BYPASS.finditer(own)][:3]))
for k in sorted(c):
    print(k, c[k])
for b in bad[:25]:
    print("  ", b)
print("DONE")
