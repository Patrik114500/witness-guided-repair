# The tasks

The benchmarks are not part of this repository, so these lists say which of their tasks each experiment ran on.
A task is named as its file or folder is named in the repository of its benchmark (the links are in the
top-level README), in the state of November 2026.

| file | rows | content |
|---|---|---|
| `experiment1_tasks.csv` | 387 | the tasks of experiment 1, with the length of each description, and the nine omitted tasks marked |
| `given_specification_audit.csv` | 2334 | the benchmark-given specifications of the audit in Section 3.1, with the verdict on each |
| `cloverbench_tasks.csv` | 62 | the tasks of CloverBench, and which of them experiment 3 could run |
| `mbpp_dfy_tasks.csv` | 164 | the tasks of MBPP-DFY that have a reference program, and which of them experiment 3 used |

```bash
python tasks/make_task_lists.py --check
```

The command compares the four lists with `../results`. It prints one line per check with `ok` or `DIFF` and
returns exit code 1 if anything differs. Without `--check` it rewrites the first two lists, which follow from
`../results` alone. Only the Python standard library is needed.

## Experiment 1 (Section 3.1, Fig. 2)

`experiment1_tasks.csv` lists the Dafny tasks of the three datasets of the vericoding benchmark that the
experiment used: verina (157), numpy_simple (58) and verified_cogen (172). A task is the file
`benchmarks/dafny/<dataset>/yaml/<task>` of that repository. The column `description_chars` is the length of
the natural-language description in characters, from `../results/desc_len.json`, and `described` is `yes` where
it is not 0.

Nine tasks are left out of the analysis (`in_analysis` is `no`), because an accept on them cannot be judged
against a reference, and `omitted_because` gives the reason. Six verina tasks state a function or a lemma, so
there is no method postcondition to write, and the reference of three tasks has no postcondition. This leaves
378 tasks, 176 of them described. Each of the eleven models ran on all of them, and the accepts are the records
of `../results/gen_audit.jsonl`.

## Specification given (Section 3.1, second paragraph)

`given_specification_audit.csv` has one row for each benchmark-given specification of the eight Dafny datasets
of the vericoding benchmark: apps (677), numpy_triple (603), dafnybench (443), verified_cogen (172), humaneval
(162), verina (157), bignum (62) and numpy_simple (58). It is a table view of `../results/given_audit.jsonl` and
`../results/given_audit_more.jsonl` without the quoted specifications.

| column | meaning |
|---|---|
| `status` | `ok` for the 2179 specifications that can be audited. `no-method-or-no-return` (139) means that the task has no method that returns a value, and `in-place` (16) that the method has a `modifies` clause. |
| `D_determinate` | `yes` when the verifier proves that the specification admits at most one output for every valid input, `no` when it does not, and empty when the query cannot be posed |
| `A_admits_every_output` | `yes` when the verifier proves that the specification admits every output. Tried only when D is not proved. |
| `B_admits_every_output_of_the_right_length` | the same for every output of the right length. Tried only when neither D nor A is proved. |
| `T_body_that_ignores_the_task` | the description of a body that ignores the task and still verifies, for example `constant 0` or `empty sequence`. Tried only when D is not proved, and empty where no such body verifies. |
| `provably_too_weak` | `yes` when A, B or T holds, which is the case for 115 specifications |

The comparison of step 2 with published pipelines in the same paragraph has no lists of its own. In Dafny it
runs on every task file of verina (157) and numpy_simple (58). These are the rows of the two datasets in
`experiment1_tasks.csv`, including the tasks that experiment 1 omits, because here the benchmark gives the
specification. In Verus and Lean it runs on every file of `benchmarks/verus/numpy_simple/yaml` (58 tasks) and of
`benchmarks/lean/numpy_simple/files` (59 tasks) of the vericoding benchmark. The DafnyBench comparison ran on
177 tasks, and the paper reports the 116 of them that need proof annotations to verify (the rows `all` and
`hard` of `../results/given_spec_step2.json`). The lists of these tasks were not in the snapshot from which this
repository was built, so they are missing here, as is the runner (see `../pipeline/README.md`).

## Experiment 2 (Section 3.2, Fig. 3)

Experiment 2 has no task list of its own, because it runs the repairs on accepts. These are the 2625 accepts of
experiment 1 on the 378 tasks above, which are the records of `../results/gen_audit.jsonl` on these tasks, and
the 1875 accepts of experiment 3 on the two benchmarks below, for which this snapshot holds counts and no
records (see `../results/README.md`).

## Experiment 3 (Section 3.3, Fig. 4)

`cloverbench_tasks.csv` lists the 62 task folders of `dataset/CloverBench/textbook_algo` in Clover's repository.
The column `runnable` is `yes` for the 45 tasks that the loader of the experiment reads: the reference file
`<task>_strong.dfy` has a method with a `returns` clause and at least one postcondition (function `load_task`
in `../pipeline/clover_gated.py`). A run of either pipeline goes through all 62 folders, records the other 17 as
`no-sig` and works on these 45. There are three runs per model and pipeline. The list comes from the records
that `../pipeline/ref_audit.py` wrote on the experiment machine. These records are not among the frozen results,
so the check compares the two counts with `../results/given_spec_step2.json`.

`mbpp_dfy_tasks.csv` lists the 164 tasks of MBPP-DFY for which the copy of the benchmark that ships with Clover
(`dataset/MBPP-DFY-153/src`) has a reference program. The column `used` is `yes` for the 159 tasks of the
experiment. Both runners keep a task when its reference file has a method with a `returns` clause that their
header pattern reads and at least one postcondition (function `gt_parts` in `../pipeline/mbpp_repro.py` and
`../pipeline/mbpp_boost.py`). Five tasks do not pass, and `excluded_because` gives the reason: the reference
methods of tasks 591, 625, 632 and 644 return no value, and the header pattern does not read the tuple types
in the signature of task 750. The task file of dafny-synthesis has 228 tasks. Its reproduction goes through all
of them and records the 69 tasks outside this set as `no-gt`, so both pipelines are compared on the same 159
tasks.

The frozen results hold the counts of these runs and the names of the solved tasks, but not the list of all
159 tasks. The list was therefore rebuilt on 25 November 2026 by applying the rule of the runners to the
public reference files of Clover's repository. The check confirms what `../results` can confirm: the list
has 159 used tasks, which is the number of records of every run of both pipelines in
`mbpp_multi_summary.json`, and every task that `e2e_fig3.json` names is on it.
