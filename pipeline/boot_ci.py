"""How stable is result 1 (more acceptance, smaller share of correct accepts)? Read-only, no verifier calls.
  - bootstrap over TASKS (resampled with replacement, 5000 times): percentile interval of the Spearman correlation
    across the eleven models, for the share form and for the count form;
  - leave-one-MODEL-out: the range of the correlation when any single model is dropped.
On the 183 described tasks and on all 387. Writes /tmp/boot_ci.json."""
import os, sys, json, random, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODEL", "none")
import fix_harness as H
import fix_state5

B = int(os.environ.get("B", "5000"))


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


def rho(a, b):
    return pearson(rank(a), rank(b))


S = fix_state5.load5()
desc = set(t for t, n in json.load(open("/tmp/desc_len.json")).items() if n > 0)
if os.environ.get("TASKFILTER") == "1":
    # same task filter as fix_table5.py TASKFILTER=1: tasks without a reference contract are left out
    pos = json.load(open("/tmp/posable.json"))
    S = {k: v for k, v in S.items() if pos.get("%s|%s" % (k[1], k[2]))}
    desc = set(t for t in desc if pos.get(t))
    print("TASKFILTER: tasks kept %d of %d" % (sum(1 for v in pos.values() if v), len(pos)))
MODELS = list(H.P11)
# per task and model: (accepted, correct, assessable)
T = collections.defaultdict(dict)
for k, v in S.items():
    if k[0] in MODELS:
        T["%s|%s" % (k[1], k[2])][k[0]] = (1 if v["accepted"] else 0, 1 if (v["accepted"] and v["rel"] is True) else 0,
                                           1 if (v["accepted"] and v["rel"] is not None) else 0)
out = {}
for name, tasks in [("described", sorted(t for t in T if t in desc)), ("all", sorted(T))]:
    def stats(sample, models=MODELS):
        acc, cor, ass = [], [], []
        for m in models:
            a = c = s = 0
            for t in sample:
                x = T[t].get(m)
                if x:
                    a += x[0]; c += x[1]; s += x[2]
            acc.append(a); cor.append(c); ass.append(s)
        share = [100.0 * c / s if s else 0.0 for c, s in zip(cor, ass)]
        gap = [a - c for a, c in zip(acc, cor)]
        return rho(acc, share), rho(acc, gap), acc, cor, ass
    r_share, r_gap, acc, cor, ass = stats(tasks)
    random.seed(11)
    bs, bg = [], []
    for _ in range(B):
        smp = [random.choice(tasks) for _ in tasks]
        a, b, _, _, _ = stats(smp)
        bs.append(a); bg.append(b)
    bs.sort(); bg.sort()
    q = lambda v, p: v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]
    loo = []
    for m in MODELS:
        a, b, _, _, _ = stats(tasks, [x for x in MODELS if x != m])
        loo.append((m.split(":")[-1], round(a, 3), round(b, 3)))
    out[name] = {"tasks": len(tasks), "accepted": sum(acc), "correct": sum(cor), "assessable": sum(ass),
                 "rho_share": r_share, "share_ci95": [q(bs, 0.025), q(bs, 0.975)], "share_frac_negative": sum(1 for x in bs if x < 0) / float(B),
                 "rho_gap": r_gap, "gap_ci95": [q(bg, 0.025), q(bg, 0.975)], "gap_frac_positive": sum(1 for x in bg if x > 0) / float(B),
                 "leave_one_model_out_share": [min(x[1] for x in loo), max(x[1] for x in loo)],
                 "leave_one_model_out_gap": [min(x[2] for x in loo), max(x[2] for x in loo)], "loo": loo}
    o = out[name]
    print("%-10s tasks %3d accepted %4d correct %4d" % (name, len(tasks), sum(acc), sum(cor)))
    print("   share form: rho %+.2f | bootstrap over tasks 95%% interval [%+.2f, %+.2f], negative in %.1f%% of resamples | leave one model out: %+.2f .. %+.2f" % (
        r_share, o["share_ci95"][0], o["share_ci95"][1], 100 * o["share_frac_negative"], o["leave_one_model_out_share"][0], o["leave_one_model_out_share"][1]))
    print("   count form: rho %+.2f | bootstrap over tasks 95%% interval [%+.2f, %+.2f], positive in %.1f%% of resamples | leave one model out: %+.2f .. %+.2f" % (
        r_gap, o["gap_ci95"][0], o["gap_ci95"][1], 100 * o["gap_frac_positive"], o["leave_one_model_out_gap"][0], o["leave_one_model_out_gap"][1]))
    print("   leave-one-out detail (model dropped, share rho, count rho):", loo)
json.dump(out, open("/tmp/boot_ci7.json" if os.environ.get("TASKFILTER") == "1" else "/tmp/boot_ci.json", "w"), indent=1)
print("DONE")
