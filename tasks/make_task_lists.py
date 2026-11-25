"""Writes the task lists that can be derived from ../results, and checks all four lists against the frozen results.

    python tasks/make_task_lists.py            rewrites experiment1_tasks.csv and given_specification_audit.csv
    python tasks/make_task_lists.py --check    changes nothing, compares the files of this folder with ../results

cloverbench_tasks.csv and mbpp_dfy_tasks.csv are not derived from ../results (see README.md), so they are only
checked: their counts must be the ones that the result files of experiment 3 report, and every MBPP-DFY task that a
result file names must be on the list. Standard library only."""
import collections, csv, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")

# the nine tasks left out of experiment 1, as in ../paper_numbers.py
NO_METHOD_POSTCONDITION = ["verina|verina_advanced_68_task.yaml", "verina|verina_advanced_73_task.yaml",
                           "verina|verina_basic_11_task.yaml", "verina|verina_basic_18_task.yaml",
                           "verina|verina_basic_40_task.yaml", "verina|verina_basic_43_task.yaml"]
NO_REFERENCE_POSTCONDITION = ["verina|verina_advanced_66_task.yaml", "numpy_simple|NpReshape-spec.yaml",
                              "verified_cogen|proofsynthesis_arg_free.yaml"]


def load(name):
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        return json.load(f)


def load_lines(name):
    with open(os.path.join(RES, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def table(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def yn(b):
    return "yes" if b else "no"


def experiment1():
    desc_len = load("desc_len.json")
    rows = []
    for key in sorted(desc_len):
        dataset, task = key.split("|")
        why = ("no method postcondition to write" if key in NO_METHOD_POSTCONDITION else
               "no postcondition in the reference" if key in NO_REFERENCE_POSTCONDITION else "")
        rows.append([dataset, task, desc_len[key], yn(desc_len[key] > 0), yn(not why), why])
    return table(["dataset", "task", "description_chars", "described", "in_analysis", "omitted_because"], rows)


def tri(v):
    return "" if v is None else yn(v)


def given_audit():
    recs = load_lines("given_audit.jsonl") + load_lines("given_audit_more.jsonl")
    rows = []
    for r in sorted(recs, key=lambda r: (r["source"], r["task"])):
        ok = r["status"] == "ok"
        weak = bool(r.get("A") or r.get("B") or r.get("T"))
        rows.append([r["source"], r["task"], r["status"], tri(r.get("D")) if ok else "", tri(r.get("A")) if ok else "",
                     tri(r.get("B")) if ok else "", (r.get("T") or "") if ok else "", yn(weak) if ok else ""])
    return table(["dataset", "task", "status", "D_determinate", "A_admits_every_output",
                  "B_admits_every_output_of_the_right_length", "T_body_that_ignores_the_task", "provably_too_weak"], rows)


DERIVED = {"experiment1_tasks.csv": experiment1, "given_specification_audit.csv": given_audit}


def check():
    bad = []

    def expect(what, got, want):
        print("  %-4s %-78s %s" % ("ok" if got == want else "DIFF", what, got))
        if got != want:
            bad.append(what)

    for name, make in DERIVED.items():
        with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
            expect(name + " equals what ../results gives", f.read() == make(), True)
    e1 = read("experiment1_tasks.csv")
    by = collections.Counter(r["dataset"] for r in e1)
    expect("experiment 1: tasks of verina, numpy_simple, verified_cogen",
           (by["verina"], by["numpy_simple"], by["verified_cogen"]), (157, 58, 172))
    expect("experiment 1: tasks in the analysis", sum(r["in_analysis"] == "yes" for r in e1), 378)
    expect("experiment 1: of them described", sum(r["in_analysis"] == "yes" and r["described"] == "yes" for r in e1), 176)
    ga = read("given_specification_audit.csv")
    expect("audit: specifications, auditable, provably too weak",
           (len(ga), sum(r["status"] == "ok" for r in ga), sum(r["provably_too_weak"] == "yes" for r in ga)), (2334, 2179, 115))
    cb = read("cloverbench_tasks.csv")
    step2 = load("given_spec_step2.json")["cloverbench"]
    expect("CloverBench: tasks and runnable tasks as in given_spec_step2.json",
           (len(cb), sum(r["runnable"] == "yes" for r in cb)), (step2["tasks"], step2["runnable"]))
    mb = read("mbpp_dfy_tasks.csv")
    used = set(r["task"] for r in mb if r["used"] == "yes")
    runs = load("mbpp_multi_summary.json")["runs"]
    ours = set(v["records"] for k, v in runs.items() if k.startswith("ours@"))
    base = set(v["records"] - v["status"].get("no-gt", 0) for k, v in runs.items() if k.startswith("baseline@"))
    expect("MBPP-DFY: tasks used, equal to the records of every run of both pipelines",
           (len(used), ours, base), (159, {159}, {159}))
    named = set()
    for d in load("e2e_fig3.json")["MBPP-DFY"].values():
        for v in d.values():
            if isinstance(v, dict) and "tasks" in v:
                named |= set(v["tasks"])
    expect("MBPP-DFY: tasks that e2e_fig3.json names and the list does not have", sorted(named - used), [])
    print("All task lists agree with ../results." if not bad else "%d check(s) differ." % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    for name, make in DERIVED.items():
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="") as f:
            f.write(make())
        print("written", name)
