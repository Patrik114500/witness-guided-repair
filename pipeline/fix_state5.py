"""State of every big-run task after the evening audit (2026-11-18), BEFORE any specification repair.

Layers, later ones override earlier ones:
  1. fix_state.load()            first pass + rescue stages A-D (code, specification of record)
  2. /tmp/fix_scores5.jsonl      oracle v4 scores and the canonical check of every accept; the specification of
                                 record is the one the accepted program states (fix_audit5)
  3. /tmp/fix_rerunE_*.jsonl     stage E: tasks whose header was mis-read are re-run with the correct header;
                                 other accepts that fail the canonical check get their code stage re-run
Rules:
  * an accept is VALID only if its body verifies under the benchmark's own header with the specification of
    record (canonical check). A non-canonical accept without a stage-E record is not an accept.
  * tasks whose vc-spec is not a method (6 verina tasks) cannot be checked: accepted, not assessable.
load5() -> {key: {accepted, rel, det, spec, code, origin, note}}"""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_harness as H
import fix_state


def _jsonl(path):
    out = []
    if os.path.exists(path):
        for l in open(path):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def load_E():
    """stage E records: 'full' re-runs (tasks whose header was mis-read) from fix_rerunE_*, 'code' re-runs
    (other non-canonical accepts, from the specification the old program stated) from fix_rerunE2_*"""
    E = {}
    for pat, mode in [("/tmp/fix_rerunE_*.jsonl", "full"), ("/tmp/fix_rerunE2_*.jsonl", "code")]:
        for f in sorted(glob.glob(pat)):
            for r in _jsonl(f):
                if r.get("api_fail") or r.get("status") == "error" or r.get("mode") != mode:
                    continue
                E[(r["model"], r["source"], r["task"])] = r
    return E


def load5(models=None, use_E=True):
    S0 = fix_state.load(models)
    # strict audit (v6) when available: time-outs are not proofs
    sc = {(r["model"], r["source"], r["task"]): r for r in _jsonl("/tmp/fix_scores6.jsonl" if os.path.exists("/tmp/fix_scores6.jsonl") else "/tmp/fix_scores5.jsonl")}
    E = load_E() if use_E else {}
    E6 = {(r["model"], r["source"], r["task"]): r for r in _jsonl("/tmp/fix_E6.jsonl")}
    out = {}
    for k, v in S0.items():
        o = {"accepted": False, "rel": None, "det": None, "spec": None, "code": None, "origin": v["origin"], "note": ""}
        s5 = sc.get(k)
        if k in E and not (E[k]["mode"] == "code" and s5 and s5.get("canon") is True):
            e = E[k]; acc = bool(e.get("accepted")); rel = e.get("rel"); det = e.get("det")
            if acc and k in E6:                      # strict re-validation of the stage-E accept
                acc = bool(E6[k]["accepted"]); rel = E6[k]["rel"]; det = E6[k]["det"]
            o.update({"origin": "E-" + e["mode"], "accepted": acc, "spec": e.get("gen_spec"), "code": e.get("code"),
                      "rel": rel if acc else None, "det": det if acc else None})
        elif v["accepted"]:
            s = sc.get(k)
            if s is None:
                o["note"] = "unscored"
            elif s.get("canon") is True or s.get("canon_cls") == "nosig":
                o.update({"accepted": True, "rel": s["rel"], "det": s["det"], "spec": s.get("spec", v["spec"]), "code": v["code"]})
            else:
                o["note"] = "non-canonical accept, not re-run"       # demoted
        out[k] = o
    return out


if __name__ == "__main__":
    import collections
    S = load5()
    c = collections.Counter()
    for k, v in S.items():
        c[(v["origin"], v["accepted"], str(v["rel"]))] += 1
        if v["note"]:
            c[("NOTE", v["note"], k[0].split(":")[-1])] += 1
    for k in sorted(c, key=str):
        print(k, c[k])
    acc = [v for v in S.values() if v["accepted"]]
    print("accepted %d  correct %d  weak %d  n/a %d" % (len(acc), sum(1 for v in acc if v["rel"] is True), sum(1 for v in acc if v["rel"] is False),
                                                        sum(1 for v in acc if v["rel"] is None)))
