"""v3 (2026-11-21): the undecided specifications split by the witness run (given_witness.py):
  witness-unintended  a confirmed witness, and the arbiter reads the description as wanting one of the outputs
  witness-intended    a confirmed witness, and the arbiter reads both outputs as intended
  witness-other       a confirmed witness without a description, or an unclear arbiter
  open                no confirmed witness
Writes /tmp/given_impact3.json.

What the weak GIVEN specifications mean for the PUBLISHED scores, on every Dafny benchmark of the vericoding
set that has released per-task outcomes. Read-only: joins the reference-free audit (/tmp/given_audit.jsonl and
/tmp/given_audit_more.jsonl) with ~/vericoding/experiments/plotdata/aggregate.csv.
For every benchmark and published model: tasks solved, and how many of them sit on a specification that is
  flagged   provably unconstrained (A), provably shape-only (B), or satisfied by a task-ignoring program (T)
  certified provably determinate (D)
  open      neither
Writes /tmp/given_impact_all.json."""
import os, csv, json, random, collections

P = os.path.expanduser("~/vericoding/experiments/plotdata")
BD = os.path.expanduser("~/vericoding/benchmarks/dafny")
BM = {"apps": "apps", "bignum": "bignum", "dafnybench": "dafnybench", "humaneval": "humaneval", "numpy-simple": "numpy_simple",
      "numpy-triple": "numpy_triple", "verina": "verina"}
A = {}
for f in ("/tmp/given_audit.jsonl", "/tmp/given_audit_more.jsonl"):
    for l in open(f):
        o = json.loads(l); A[(o["source"], o["task"].replace(".yaml", ""))] = o
WIT = {}
for l in open("/tmp/given_witness.jsonl"):
    try:
        w = json.loads(l)
    except Exception:
        continue
    if w.get("status") not in ("api-fail", "error"):
        WIT[(w["source"], w["task"].replace(".yaml", ""))] = w
names = {}
for b in BM.values():
    for l in open("%s/%s/dafny_%s.jsonl" % (BD, b, b)):
        try:
            r = json.loads(l); names[(b, r["id"])] = r["source_id"]
        except Exception:
            pass


def cls(o):
    if o is None:
        return "missing"
    if o.get("status") != "ok":
        return "not audited"
    if o.get("A") or o.get("B") or o.get("T"):
        return "flagged"
    if o.get("D"):
        return "certified"
    w = WIT.get((o["source"], o["task"].replace(".yaml", "")))
    if w and w.get("witness"):
        a = w.get("arbiter")
        return "witness-unintended" if a == "UNINTENDED" else ("witness-intended" if a == "INTENDED" else "witness-other")
    return "open"


def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); rk = [0.0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for t in range(i, j + 1):
            rk[o[t]] = (i + j) / 2.0 + 1
        i = j + 1
    return rk


def pearson(a, b):
    n = len(a); ma = sum(a) / n; mb = sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** .5; sb = sum((y - mb) ** 2 for y in b) ** .5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


def spearman(a, b, nperm=100000):
    ra, rb = rank(a), rank(b); rho = pearson(ra, rb)
    random.seed(7); cnt = 0; rb2 = rb[:]
    for _ in range(nperm):
        random.shuffle(rb2)
        if abs(pearson(ra, rb2)) >= abs(rho) - 1e-12:
            cnt += 1
    return rho, cnt / nperm


best = {}
for r in csv.DictReader(open(P + "/aggregate.csv")):
    if r["Language"] != "dafny" or r["Benchmark"] not in BM:
        continue
    b = BM[r["Benchmark"]]
    k = (r["LLM"], b, names.get((b, r["Task ID"]), r["Task ID"]))
    best[k] = max(best.get(k, 0), int(r["Success"]))
out = {"benchmarks": {}, "models": {}, "overall": {}}
tot = collections.defaultdict(collections.Counter)
print("%-13s %5s | %9s %5s %7s %8s | flagged share of the specs" % ("benchmark", "tasks", "certified", "open", "flagged", "not aud."))
allc = collections.Counter()
for b in sorted(set(BM.values())):
    tasks = sorted(set(t for (m, bb, t) in best if bb == b))
    tc = collections.Counter(cls(A.get((b, t))) for t in tasks)
    allc.update(tc)
    aud = tc["certified"] + tc["open"] + tc["flagged"]
    out["benchmarks"][b] = {"tasks": len(tasks), **{k: tc[k] for k in ("certified", "open", "witness-unintended", "witness-intended", "witness-other", "flagged", "not audited", "missing")}}
    print("%-13s %5d | %9d %5d %7d %8d | %.1f%% of %d audited%s" % (b, len(tasks), tc["certified"], tc["open"], tc["flagged"], tc["not audited"],
          100.0 * tc["flagged"] / max(1, aud), aud, ("  (names not matched: %d)" % tc["missing"]) if tc["missing"] else ""))
    models = sorted(set(mm for (mm, bb, t) in best if bb == b))
    rows = []
    for m in models:
        sol = [t for t in tasks if best.get((m, b, t))]
        c = collections.Counter(cls(A.get((b, t))) for t in sol)
        d = {"n": len(tasks), "solved": len(sol), **{k: c[k] for k in ("flagged", "certified", "open", "witness-unintended", "witness-intended", "witness-other", "not audited", "missing")}}
        out["models"]["%s|%s" % (b, m)] = d
        tot[m].update({"solved": len(sol), "n": len(tasks), **{k: c[k] for k in ("flagged", "certified", "open", "witness-unintended", "witness-intended", "witness-other", "not audited", "missing")}})
        rows.append((m, d))
    if len(rows) >= 5 and tc["flagged"]:
        r1, p1 = spearman([d["solved"] for _, d in rows], [100.0 * d["flagged"] / max(1, d["solved"]) for _, d in rows])
        out["benchmarks"][b]["rho_solved_share"] = [r1, p1]
        print("      per model solved / on flagged: %s | solved vs share: rho %+.2f (p=%.3f)" % (
            ", ".join("%s %d/%d" % (m.split("-")[0][:6] + m[-4:], d["solved"], d["flagged"]) for m, d in sorted(rows, key=lambda x: -x[1]["solved"])), r1, p1))
print("%-13s %5d | %9d %5d %7d %8d | %.1f%% of %d audited" % ("ALL", sum(allc.values()), allc["certified"], allc["open"], allc["flagged"], allc["not audited"],
      100.0 * allc["flagged"] / max(1, allc["certified"] + allc["open"] + allc["flagged"]), allc["certified"] + allc["open"] + allc["flagged"]))
out["overall"]["specs"] = dict(allc)
print()
print("published models over all seven benchmarks:")
M = sorted(tot, key=lambda m: -tot[m]["solved"])
for m in M:
    c = tot[m]
    out["overall"][m] = dict(c)
    print("  %-20s solved %4d of %4d | certified %4d open %4d flagged %3d (%.1f%% of solved) not audited %3d" % (
        m, c["solved"], c["n"], c["certified"], c["open"], c["flagged"], 100.0 * c["flagged"] / max(1, c["solved"]), c["not audited"]))
full = [m for m in M if tot[m]["n"] == max(tot[x]["n"] for x in M)]
r1, p1 = spearman([tot[m]["solved"] for m in full], [100.0 * tot[m]["flagged"] / max(1, tot[m]["solved"]) for m in full])
out["overall"]["rho_solved_share"] = [r1, p1, len(full)]
r2, p2 = spearman([tot[m]["solved"] for m in full], [100.0 * (tot[m]["flagged"] + tot[m]["witness-unintended"]) / max(1, tot[m]["solved"]) for m in full])
out["overall"]["rho_solved_share_with_witness"] = [r2, p2, len(full)]
print("  solved vs share on flagged or witnessed-unintended specs: rho %+.2f (p=%.3f)" % (r2, p2))
for m in M:
    c = tot[m]
    print("  %-20s witness: unintended %3d intended %3d other %3d | open %4d" % (m, c["witness-unintended"], c["witness-intended"], c["witness-other"], c["open"]))
print("  models with outcomes on every benchmark: %d | solved vs share on flagged specs: rho %+.2f (p=%.3f)" % (len(full), r1, p1))
# how much easier are the flagged tasks
fl = [(b, t) for (b, t), o in A.items() if cls(o) == "flagged" and b in set(BM.values())]
ce = [(b, t) for (b, t), o in A.items() if cls(o) == "certified" and b in set(BM.values())]
sr = lambda L: sum(best.get((m, b, t), 0) for (b, t) in L for m in M) / max(1.0, sum(1 for (b, t) in L for m in M if (m, b, t) in best))
out["overall"]["solve_rate"] = {"flagged": sr(fl), "certified": sr(ce)}
print("  mean published solve rate: tasks with a flagged spec %.1f%%, tasks with a provably determinate spec %.1f%%" % (100 * sr(fl), 100 * sr(ce)))
json.dump(out, open("/tmp/given_impact3.json", "w"), indent=1)
print("DONE")
