"""Read-only: why does figure 2 count so few specifications? The funnel of the common set (9 cloud models, all tasks
with a reference contract), the same set and rules as fix_table5.py:
  (1) accepts, correct / not shown correct
  (2) the not-shown ones by kind: provably determinate (the specification pins down ONE output for every input, and
      that output is not provably the reference's: it says something else, adding clauses cannot fix it) against
      not determinate (it leaves something open: adding a clause can fix it)
  (3) per rule, the valid changes split by what they did to the verdict: on correct specs (stays correct =
      strengthened, or broken) and on not-shown specs (repaired, or still not shown)."""
import os, sys, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import fix_harness as H
import fix_state, fix_state5

NL = chr(10)


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


CLOUD = ["claude:claude-opus-5-5", "aoai:gpt-6-astra", "claude:claude-sonnet-4-6", "grok:grok-4.3", "claude:claude-opus-4-6", "aoai:gpt-5",
         "aoai:gpt-5-mini", "claude:claude-haiku-4-5", "aoai:gpt-4o"]
S0 = fix_state.load(); E = fix_state5.load_E(); S = fix_state5.load5()
sc = {(r["model"], r["source"], r["task"]): r for r in jl("/tmp/fix_scores6.jsonl")}
pos = json.load(open("/tmp/posable.json"))
common = set(k for k, v in S0.items() if v["accepted"] and v["origin"] == "orig" and k not in E and k in sc and sc[k].get("canon") is True
             and sc[k]["rel"] is not None and not sc[k].get("respec") and pos.get("%s|%s" % (k[1], k[2])) and k[0] in CLOUD)
good = [k for k in common if sc[k]["rel"] is True]; weak = [k for k in common if sc[k]["rel"] is False]
print("(1) common set: %d accepts | correct %d | not shown correct %d" % (len(common), len(good), len(weak)))
refdet = json.load(open("/tmp/ref_det.json"))
c = collections.Counter()
for k in weak:
    d = sc[k].get("det")
    r = refdet.get("%s|%s" % (k[1], k[2]))
    c[("spec determinate" if d == 1.0 else ("spec not determinate" if d == 0.0 else "determinacy unknown"),
       "reference determinate" if r == 1.0 else "reference not proved determinate")] += 1
print("(2) the %d not-shown specifications:" % len(weak))
for kk, v in sorted(c.items()):
    print("      %-22s | %-34s %4d" % (kk[0], kk[1], v))
# (3) per rule
plain = {}
for a in jl("/tmp/fix_arms6.jsonl"):
    plain[(a["model"], a["source"], a["task"], a["arm"])] = a
byp = set((a["model"], a["source"], a["task"], a["arm"]) for a in jl("/tmp/fix_arms_conj.jsonl") if a.get("plain_bypass"))
conj = {(a["model"], a["source"], a["task"], a["arm"]): a for a in jl("/tmp/fix_arms_conj.jsonl")}
W = {}
for f in sorted(__import__("glob").glob("/tmp/wit2_*.jsonl")):
    if "rescore" in f:
        continue
    for r in jl(f):
        if "stop" not in r or r.get("stop") == "api-fail":
            continue
        k = (r["model"], r["source"], r["task"])
        if k in S and H.nows(r.get("spec_before")) == H.nows(S[k]["spec"]):
            if k in W and W[k].get("changed") and not r.get("changed"):
                continue
            W[k] = r
cache = {(r["model"], r["source"], r["task"], r["spec"]): r for r in jl("/tmp/wit2_rescore.jsonl")}
print("(3) valid changes per rule, by effect on the verdict (common set)")
print("      %-26s %7s | %-16s %-8s | %-9s %-16s | proposals reaching no valid change" % ("rule", "changes", "correct: stronger", "broken", "repaired", "still not shown"))
OUT = {"common": len(common), "correct": len(good), "not_shown": len(weak), "kinds": {"%s|%s" % kk: v for kk, v in c.items()}, "rules": {}}
for arm, lab in [("arm_judge", "LLM judge"), ("arm_determinacy", "determinacy rewrite"), ("arm_ours", "mined invariants")]:
    for mode in ("replace", "add"):
        n = st = br = rp = nr = inval = 0
        for k in common:
            key = (k[0], k[1], k[2], arm)
            if mode == "replace":
                a = plain.get(key)
                if not a or not a.get("changed"):
                    continue
                if not (a.get("canon_after") is True) or key in byp:
                    inval += 1; continue
                after = a.get("after")
            else:
                a = conj.get(key)
                if not a or "skip" in a or "error" in a:
                    continue
                if not a.get("conj_valid"):
                    inval += 1; continue
                after = a.get("conj_after")
            n += 1
            if sc[k]["rel"] is True:
                if after is True:
                    st += 1
                else:
                    br += 1
            else:
                if after is True:
                    rp += 1
                else:
                    nr += 1
        print("      %-26s %7d | %-16d %-8d | %-9d %-16d | %d" % ("%s, %s" % (lab, mode), n, st, br, rp, nr, inval))
        OUT["rules"]["%s|%s" % (lab, mode)] = {"changes": n, "stays_correct": st, "broken": br, "repaired": rp, "still_not_shown": nr}
n = st = br = rp = nr = 0
for k in common:
    r = W.get(k)
    if not r or not r.get("changed"):
        continue
    cc = cache.get((k[0], k[1], k[2], H.nows(r["final_spec"])))
    if not cc or cc.get("canon") is not True:
        continue
    n += 1
    after = True if sc[k]["rel"] is True else cc.get("rel")
    if sc[k]["rel"] is True:
        st += 1
    else:
        rp += after is True; nr += after is not True
targets = [k for k in common if k in W]
print("      %-26s %7d | %-16d %-8d | %-9d %-16d | targets %d (accepts whose spec was not provably determinate), of them weak %d" % (
    "witness-guided, add", n, st, br, rp, nr, len(targets), sum(1 for k in targets if sc[k]["rel"] is False)))
OUT["rules"]["witness-guided|add"] = {"changes": n, "stays_correct": st, "broken": br, "repaired": rp, "still_not_shown": nr}
# all four proposers under the add rule, one valid strengthening per accept, a provably determinate one first (same
# choice as fix_table5.py: witness_v2, determinacy rewrite, LLM judge, mined invariants)
ORDER = {"witness_v2": 0, "arm_determinacy": 1, "arm_judge": 2, "arm_ours": 3}
n = st = br = rp = nr = 0
for k in common:
    cs = []
    for arm in ("arm_ours", "arm_judge", "arm_determinacy"):
        a = conj.get((k[0], k[1], k[2], arm))
        if a and "skip" not in a and "error" not in a and a.get("conj_valid"):
            cs.append((arm, a.get("conj_after"), a.get("det")))
    r = W.get(k)
    if r and r.get("changed"):
        cc = cache.get((k[0], k[1], k[2], H.nows(r["final_spec"])))
        if cc and cc.get("canon") is True:
            cs.append(("witness_v2", True if sc[k]["rel"] is True else cc.get("rel"), cc.get("det")))
    if not cs:
        continue
    cs.sort(key=lambda x: (0 if x[2] == 1.0 else 1, ORDER[x[0]]))
    after = cs[0][1]; n += 1
    if sc[k]["rel"] is True:
        st += after is True; br += after is not True
    else:
        rp += after is True; nr += after is not True
print("      %-26s %7d | %-16d %-8d | %-9d %-16d" % ("all four proposers, add", n, st, br, rp, nr))
OUT["rules"]["all four proposers|add"] = {"changes": n, "stays_correct": st, "broken": br, "repaired": rp, "still_not_shown": nr}
wk_det = [k for k in weak if sc[k].get("det") == 1.0]
print("not-shown specs that are provably determinate (no witness can exist, adding cannot repair them): %d of %d" % (len(wk_det), len(weak)))
json.dump(OUT, open("/tmp/repair_funnel.json", "w"), indent=1)
