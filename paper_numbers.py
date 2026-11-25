#!/usr/bin/env python3
"""Recompute every number of the paper from the frozen results in results/ and compare it with the printed value.

    python paper_numbers.py      # one line per number; the exit code is 1 if any of them differs from the paper

No model call, no verifier call, standard library only. What each input file holds is described in
results/README.md. Numbers of experiment 1 are recomputed from the per-accept records (gen_audit.jsonl) and those
of the audit from the per-specification records (given_audit*.jsonl); the other files hold per-arm counts and
per-task lists that the experiment scripts in pipeline/ wrote, and the script derives the paper's numbers from
them.
"""
import collections
import json
import os
import random
import sys
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")

# The eleven models in the order of pipeline/fix_harness.py (P11). The order matters only for the Monte Carlo
# permutation p-values, which shuffle the ranks from this order with a fixed seed.
MODELS = ["claude:claude-opus-5-5", "aoai:gpt-6-astra", "claude:claude-sonnet-4-6", "grok:grok-4.3",
          "qwen2.5-coder:32b", "claude:claude-opus-4-6", "aoai:gpt-5", "aoai:gpt-5-mini", "gpt-oss:20b",
          "claude:claude-haiku-4-5", "aoai:gpt-4o"]
E2E_MODELS = ["gpt-4o", "gpt-5-mini", "haiku-4-5", "sonnet-4-6"]

# Tasks left out of experiment 1 (Section 2.3). Six verina tasks state a function or a lemma, so there is no method
# postcondition to write; three references have no postcondition.
NO_METHOD_POSTCONDITION = ["verina|verina_advanced_68_task.yaml", "verina|verina_advanced_73_task.yaml",
                           "verina|verina_basic_11_task.yaml", "verina|verina_basic_18_task.yaml",
                           "verina|verina_basic_40_task.yaml", "verina|verina_basic_43_task.yaml"]
NO_REFERENCE_POSTCONDITION = ["verina|verina_advanced_66_task.yaml", "numpy_simple|NpReshape-spec.yaml",
                              "verified_cogen|proofsynthesis_arg_free.yaml"]
OMITTED = set(NO_METHOD_POSTCONDITION + NO_REFERENCE_POSTCONDITION)


def load(name):
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        return json.load(f)


def load_lines(name):
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------------------------------- statistics
def rank(v):
    """Ranks from 1, ties get the mean rank."""
    o = sorted(range(len(v)), key=lambda i: v[i])
    rk = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for t in range(i, j + 1):
            rk[o[t]] = (i + j) / 2.0 + 1
        i = j + 1
    return rk


def pearson(a, b):
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** .5
    sb = sum((y - mb) ** 2 for y in b) ** .5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


def spearman(a, b, nperm):
    """Spearman's rho and a two-sided Monte Carlo permutation p-value (fixed seed, as in the experiment scripts)."""
    ra, rb = rank(a), rank(b)
    rho = pearson(ra, rb)
    random.seed(7)
    cnt = 0
    rb2 = rb[:]
    for _ in range(nperm):
        random.shuffle(rb2)
        if abs(pearson(ra, rb2)) >= abs(rho) - 1e-12:
            cnt += 1
    return rho, cnt / nperm


def sign_p(a, b):
    """Two-sided exact sign test on a discordant pairs one way and b the other way."""
    n = a + b
    return min(1.0, 2.0 * sum(comb(n, k) for k in range(0, min(a, b) + 1)) / (2.0 ** n)) if n else 1.0


# ------------------------------------------------------------------------------------------------------ reporting
FAILED = []


def check(label, got, paper, shown=None):
    """One line per number: `got` is compared with the value printed in the paper, `shown` adds the unrounded value."""
    ok = got == paper
    if not ok:
        FAILED.append(label)
    value = "%s" % (got,) if shown is None else "%s (%s)" % (got, shown)
    print("  %-4s %-78s %s%s" % ("ok" if ok else "DIFF", label, value, "" if ok else "   paper: %s" % (paper,)))


def name(model):
    """Model id without the provider prefix of the experiment scripts."""
    return model.split(":", 1)[1] if model.split(":", 1)[0] in ("aoai", "claude", "grok") else model


def pct(a, b):
    return 100.0 * a / b


def section(title):
    print()
    print(title)


# ================================================================================ experiment 1: the measurement
section("Sections 2.3 and 3.1, Fig. 2: acceptance against correctness (results/gen_audit.jsonl, desc_len.json)")
accepts = load_lines("gen_audit.jsonl")            # one record per accept: model, source, task, rel (S => G proved)
desc_len = load("desc_len.json")                   # "source|task" -> length of the natural-language description
tasks_by_source = collections.Counter(k.split("|")[0] for k in desc_len)
check("tasks of verina", tasks_by_source["verina"], 157)
check("tasks of numpy_simple", tasks_by_source["numpy_simple"], 58)
check("tasks of verified_cogen", tasks_by_source["verified_cogen"], 172)
unassessable = set("%s|%s" % (r["source"], r["task"]) for r in accepts if r["rel"] is None)
check("omitted tasks are exactly those whose accepts cannot be judged", unassessable == OMITTED, True)
check("omitted tasks (six without a method postcondition, three without a reference one)", len(OMITTED), 9)
ALL_TASKS = sorted(t for t in desc_len if t not in OMITTED)
DESCRIBED = sorted(t for t in ALL_TASKS if desc_len[t] > 0)
check("tasks that remain", len(ALL_TASKS), 378)
check("of them with a natural-language description", len(DESCRIBED), 176)
check("models", len(set(r["model"] for r in accepts)), 11)

# per task and model: correct (True) or not shown correct (False); a missing entry means no accept
verdict = collections.defaultdict(dict)
for r in accepts:
    t = "%s|%s" % (r["source"], r["task"])
    if t not in OMITTED:
        verdict[t][r["model"]] = r["rel"] is True


def per_model(tasks):
    acc = [sum(1 for t in tasks if m in verdict[t]) for m in MODELS]
    cor = [sum(1 for t in tasks if verdict[t].get(m)) for m in MODELS]
    return acc, cor


def bootstrap(tasks, resamples=5000):
    """Percentile interval of rho(accepts, share correct) over task resamples, as in pipeline/boot_ci.py."""
    random.seed(11)
    rhos = []
    for _ in range(resamples):
        smp = [random.choice(tasks) for _ in tasks]
        acc, cor = per_model(smp)
        rhos.append(pearson(rank(acc), rank([pct(c, a) if a else 0.0 for c, a in zip(cor, acc)])))
    rhos.sort()
    q = lambda p: rhos[min(len(rhos) - 1, max(0, int(round(p * (len(rhos) - 1)))))]
    return q(0.025), q(0.975)


acc_d, cor_d = per_model(DESCRIBED)
print("  model                      accepts  correct  not shown  share correct   (176 described tasks)")
for m, a, c in sorted(zip(MODELS, acc_d, cor_d), key=lambda x: -x[1]):
    print("    %-24s %7d %8d %10d %13.1f%%" % (name(m), a, c, a - c, pct(c, a)))
not_shown = [pct(a - c, a) for a, c in zip(acc_d, cor_d)]
share = [pct(c, a) for a, c in zip(acc_d, cor_d)]
check("smallest share of a model's accepts that are not shown correct, %", round(min(not_shown)), 6, "%.1f" % min(not_shown))
check("largest share of a model's accepts that are not shown correct, %", round(max(not_shown)), 20, "%.1f" % max(not_shown))
check("largest correct share (caption of Fig. 2), %", round(max(share)), 94, "%.1f" % max(share))
check("smallest correct share (caption of Fig. 2), %", round(min(share)), 80, "%.1f" % min(share))
rho, p = spearman(acc_d, share, 50000)
check("Spearman rho, accepts against correct share", round(rho, 2), -0.72, "%+.4f" % rho)
check("its permutation p-value", round(p, 3), 0.015, "%.4f" % p)
lo, hi = bootstrap(DESCRIBED)
check("95% interval from 5000 task resamples, lower end", round(lo, 2), -0.92, "%+.4f" % lo)
check("95% interval from 5000 task resamples, upper end", round(hi, 2), -0.10, "%+.4f" % hi)
stored = load("boot_ci7.json")["described"]["share_ci95"]
check("the interval equals the one stored by pipeline/boot_ci.py", [round(lo, 6), round(hi, 6)] ==
      [round(stored[0], 6), round(stored[1], 6)], True)

# accepts on tasks that few models get accepted (the harder tasks) against the rest
n_models = {t: len(verdict[t]) for t in DESCRIBED}
few = [v for t in DESCRIBED if 1 <= n_models[t] <= 7 for v in verdict[t].values()]
many = [v for t in DESCRIBED if n_models[t] >= 8 for v in verdict[t].values()]
check("correct share on tasks with accepts from at most seven models, %", round(pct(sum(few), len(few))), 66,
      "%.1f, %d of %d" % (pct(sum(few), len(few)), sum(few), len(few)))
check("correct share on the other tasks, %", round(pct(sum(many), len(many))), 95,
      "%.1f, %d of %d" % (pct(sum(many), len(many)), sum(many), len(many)))

acc_a, cor_a = per_model(ALL_TASKS)
check("accepts on all 378 tasks", sum(acc_a), 2625)
check("of them correct, %", round(pct(sum(cor_a), sum(acc_a))), 77,
      "%.1f, %d of %d" % (pct(sum(cor_a), sum(acc_a)), sum(cor_a), sum(acc_a)))
rho, p = spearman(acc_a, [pct(c, a) for a, c in zip(acc_a, cor_a)], 50000)
check("Spearman rho on all tasks", round(rho, 2), -0.59, "%+.4f" % rho)
check("its permutation p-value", round(p, 3), 0.061, "%.4f" % p)

# the same table as written by pipeline/fix_table5.py, which Fig. 2 is drawn from
for name, tasks, acc, cor in (("bigrun_v7_described.json", DESCRIBED, acc_d, cor_d),
                              ("bigrun_v7.json", ALL_TASKS, acc_a, cor_a)):
    table = load(name)["models"]
    same = all(table[m]["before"]["acc"] == a and table[m]["before"]["rel"] == c
               for m, a, c in zip(MODELS, acc, cor))
    check("per-model counts equal the table in results/%s" % name, same, True)

# ================================================================================ benchmark-given specifications
section("Section 3.1: audit of the benchmark-given specifications (results/given_audit*.jsonl, given_impact3.json)")
given = load_lines("given_audit.jsonl") + load_lines("given_audit_more.jsonl")
check("Dafny datasets of the vericoding benchmark", len(set(r["source"] for r in given)), 8)
auditable = [r for r in given if r["status"] == "ok"]
# provably too weak: admits every output (A), every output of the right length (B), or a body that ignores the
# task verifies against it (T)
weak = [r for r in auditable if r.get("A") or r.get("B") or r.get("T")]
check("auditable specifications", len(auditable), 2179, "of %d" % len(given))
check("provably too weak", len(weak), 115)
check("as a share, %", round(pct(len(weak), len(auditable)), 1), 5.3)
impact = load("given_impact3.json")["overall"]
published = {m: v for m, v in impact.items() if isinstance(v, dict) and "solved" in v}
full_n = max(v["n"] for v in published.values())
full = sorted((m for m in published if published[m]["n"] == full_n), key=lambda m: -published[m]["solved"])
check("models with published per-task results on every dataset", len(full), 8)
print("  model                      solved   on a provably too weak specification")
for m in full:
    print("    %-24s %6d   %3d (%.1f%%)" % (m, published[m]["solved"], published[m]["flagged"],
                                          pct(published[m]["flagged"], published[m]["solved"])))
shares = [pct(published[m]["flagged"], published[m]["solved"]) for m in full]
check("smallest share of solved tasks that rest on one, %", round(min(shares)), 3, "%.1f" % min(shares))
check("largest share, %", round(max(shares)), 6, "%.1f" % max(shares))
rho, p = spearman([published[m]["solved"] for m in full], shares, 100000)
check("Spearman rho, solved tasks against this share", round(rho, 2), 0.88, "%+.4f" % rho)
check("its permutation p-value", round(p, 3), 0.007, "%.4f" % p)

section("Section 3.1: step 2 with a given specification against published pipelines (results/given_spec_step2.json)")
step2 = load("given_spec_step2.json")
rows = [r for r in step2["rows"] if r["in_total"]]
for r in step2["rows"]:
    print("    %-40s published %3d   ours %3d%s" % (r["label"], r["published"], r["ours"],
                                                  "" if r["in_total"] else "   (not in the total)"))
check("dataset-model pairs", len(rows), 9)
check("tasks solved by step 2", sum(r["ours"] for r in rows), 461)
check("tasks solved by the published pipelines", sum(r["published"] for r in rows), 442)
db = step2["dafnybench_gpt4o_paired"]
hard = [r for r in rows if r["label"].startswith("DafnyBench")][0]
check("DafnyBench annotation tasks", hard["tasks"], 116)
check("of them solved, published and ours (gpt-4o)", [hard["published"], hard["ours"]], [80, 89])
check("paired exact test on %d against %d tasks, p" % (db["only_ours"], db["only_published"]),
      round(sign_p(db["only_ours"], db["only_published"]), 3), 0.035)

# ======================================================================================= experiment 2: repairs
section("Section 3.2, Fig. 3: the four repairs (results/repair_funnel_ext.json)")
funnel = load("repair_funnel_ext.json")
R = funnel["rules"]
check("accepts of the first and third experiment", funnel["common"], 4500)
check("of them from the first experiment", funnel["by_source"]["big run"], 2625)
check("accepts not shown correct", funnel["not_shown"], 873)
for label, key, broken, repaired in (("LLM judge, replaces S", "LLM judge|replace", 29, 34),
                                     ("determinacy flag, replaces S", "determinacy rewrite|replace", 8, 45),
                                     ("mined invariants", "mined invariants|replace", 0, 4),
                                     ("ours, adds a clause", "all four proposers|add", 0, 75)):
    check("Fig. 3, %s: broken and repaired" % label, [R[key]["broken"], R[key]["repaired"]], [broken, repaired])
rep = [R["LLM judge|replace"], R["determinacy rewrite|replace"]]
add = [R["LLM judge|add"], R["determinacy rewrite|add"]]
check("same proposals, replacing: correct specifications broken", sum(r["broken"] for r in rep), 37)
check("same proposals, replacing: accepts repaired", sum(r["repaired"] for r in rep), 79)
check("same proposals, adding: correct specifications broken", sum(r["broken"] for r in add), 0)
check("same proposals, adding: accepts repaired", sum(r["repaired"] for r in add), 74)
p = sign_p(sum(r["broken"] for r in rep), sum(r["broken"] for r in add))
check("exact sign test on 37 against 0, p < 0.001", p < 0.001, True, "%.1e" % p)
check("mined invariants, added as a clause: broken", R["mined invariants|add"]["broken"], 0)
check("our step 3: accepts repaired", R["all four proposers|add"]["repaired"], 75)
check("our step 3: correct specifications changed", R["all four proposers|add"]["stays_correct"], 1086)
check("our step 3: correct specifications broken", R["all four proposers|add"]["broken"], 0)
check("repairs from the witness search alone", R["witness-guided|add"]["repaired"], 51)

# ================================================================================ experiment 3: end to end
section("Section 3.3, Fig. 4: end-to-end comparison (results/e2e_fig3.json, *_multi_summary.json)")
e2e = load("e2e_fig3.json")
clover_summary = load("clover_multi_summary.json")
mbpp_summary = load("mbpp_multi_summary.json")
check("CloverBench tasks and runnable ones", [step2["cloverbench"]["tasks"], step2["cloverbench"]["runnable"]],
      [62, 45])
check("CloverBench records per run, three runs per pipeline and model",
      all(clover_summary[m][p]["records"] == [62, 62, 62] for m in E2E_MODELS for p in ("clover", "ours")), True)
check("MBPP-DFY tasks", set(mbpp_summary["runs"]["ours@" + m]["records"] for m in E2E_MODELS), {159})
print("  model          CloverBench: Clover  ours  (runs)                  MBPP-DFY: dafny-synthesis  ours")
pairs = {"CloverBench": [0, 0], "MBPP-DFY": [0, 0]}
ahead, gain, beats_best, interface, ahead_anyway = [], [], [], [], []
for m in E2E_MODELS:
    c, b = e2e["CloverBench"][m], e2e["MBPP-DFY"][m]
    # CloverBench: a task counts for a pipeline if it is correct in at least two of its three runs
    c_pub, c_our = set(c["clover_before"]["majority"]), set(c["ours_after"]["majority"])
    b_pub, b_our = set(b["baseline_before"]["tasks"]), set(b["ours_after"]["tasks"])
    pairs["CloverBench"][0] += len(c_our - c_pub)
    pairs["CloverBench"][1] += len(c_pub - c_our)
    pairs["MBPP-DFY"][0] += len(b_our - b_pub)
    pairs["MBPP-DFY"][1] += len(b_pub - b_our)
    ahead += [len(c_our) > len(c_pub), len(b_our) > len(b_pub)]
    gain += [len(c_our) - len(c["ours_before"]["majority"]), len(b_our) - b["ours_before"]["n"]]
    beats_best.append(min(c["ours_after"]["runs"]) > max(c["clover_before"]["runs"]))
    other = mbpp_summary["baseline@" + m]["proof"].get("interface", 0)
    interface.append(other)
    ahead_anyway.append(len(b_our) > len(b_pub) + other)
    print("    %-12s %19d %5d  %-24s %24d %5d" % (m, len(c_pub), len(c_our),
          "%s against %s" % (c["clover_before"]["runs"], c["ours_after"]["runs"]), len(b_pub), len(b_our)))
check("ours is correct on more tasks with every model, on both benchmarks", all(ahead), True)
check("CloverBench: task-model pairs correct only with ours, only with Clover", pairs["CloverBench"], [28, 1])
check("MBPP-DFY: correct only with ours, only with dafny-synthesis", pairs["MBPP-DFY"], [105, 32])
for name in ("CloverBench", "MBPP-DFY"):
    p = sign_p(*pairs[name])
    check("%s: exact sign test, p < 0.001" % name, p < 0.001, True, "%.1e" % p)
check("most correct tasks that step 3 adds for one model", max(gain), 3)
check("every run of ours beats Clover's best run (caption of Fig. 4)", all(beats_best), True)
check("dafny-synthesis programs with a different interface, fewest and most per model",
      [min(interface), max(interface)], [4, 8])
check("ours stays ahead if these counted as correct", all(ahead_anyway), True)

print()
if FAILED:
    print("%d number(s) differ from the paper:" % len(FAILED))
    for f in FAILED:
        print("  " + f)
    sys.exit(1)
print("All numbers agree with the paper.")
