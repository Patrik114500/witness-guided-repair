# Frozen results

These files are the outputs of the experiment scripts in `../pipeline`, frozen at the state that the paper
reports. `../paper_numbers.py` and the scripts in `../figures` read nothing else. The file names are the ones the
scripts wrote on the experiment machine, apart from the prefix `/tmp/`, so every file can be traced to the line
of code that wrote it. The table at the end of `../pipeline/README.md` relates the names used in the code to the
terms of the paper. The most frequent ones are `rel` for correct (the verifier proves S ⇒ G) and `weak` or
`not_shown` for not shown correct.

## Experiment 1 (Section 3.1, Fig. 2)

`gen_audit.jsonl` has one record for each of the 2669 accepts of the eleven models on the 387 tasks, written
by `gen_audit.py`. The fields are `model`, `source` (dataset), `task`, `rel` (true when S ⇒ G is proved, false
when it is not, null when no reference contract can be posed), `det` (1.0 when the determinacy query on S is
proved, 0.0 when it is not, null when it cannot be posed) and `cls` (the reference-free verdict on S:
`determinate`, `weak`, `undecided` or `n/a`). After the nine omitted tasks are left out, 2625 accepts remain,
and every number of the first paragraph of Section 3.1 is recomputed from these records.

`desc_len.json` gives the length of the natural-language description of each task, and 0 where the task only
has a signature. It defines the described tasks (176 of the 378).

`bigrun_v7.json` and `bigrun_v7_described.json` are the tables that `fix_table5.py` wrote with `TASKFILTER=1`,
for all tasks and for the described ones (on the experiment machine `/tmp/fix_final7.json` and
`/tmp/fix_final7_described.json`). They hold several views of each model. The view `before` is the state
after the harness audit and before any repair, and it is the one the paper reports: `n` tasks, `sc` accepts,
`rel` correct, `weak` not shown correct. Fig. 2 is drawn from the described file. `paper_numbers.py` checks that
these tables agree with the per-accept records.

`boot_ci7.json` is the output of `boot_ci.py`: the bootstrap interval of Spearman's ρ over 5000 task resamples.
`paper_numbers.py` repeats the resampling with the same seed and compares.

## Specification given (Section 3.1, second paragraph)

`given_audit.jsonl` (verina, numpy_simple, verified_cogen) and `given_audit_more.jsonl` (apps, bignum,
dafnybench, humaneval, numpy_triple) hold one record for each benchmark-given specification, written by
`given_audit.py` and `given_audit2.py`. A record with `status` equal to `ok` is auditable (2179 of 2334). The
certificates are `D` (determinate), `A` (admits every output), `B` (admits every output of the right length)
and `T` (a body that ignores the task verifies; the field describes the body and `T_body` holds it). A
specification with `A`, `B` or `T` is provably too weak (115). The field `vacuous` was added by a later check
and no number of the paper uses it. The records quote the precondition and the postcondition of each task
from the vericoding benchmark, so that every verdict can be inspected. The benchmark is released under the
MIT License, which is reproduced in `../third_party/vericoding-LICENSE.txt`.

`given_impact3.json` is the output of `given_impact3.py`. It joins the audit with the per-task results that
the vericoding benchmark published, per dataset and model (`models`) and over all datasets (`overall`). For a
model, `solved` counts its solved tasks and `flagged` those of them that rest on a specification that is
provably too weak. Eight models have published results on every dataset (`n` equal to 1989), and the paper
reports these.

`given_spec_step2.json` holds the counts of the comparison of step 2 with published pipelines when the
specification is given: nine dataset-model pairs, and the paired counts of the 116 DafnyBench annotation
tasks. Unlike the other files it was assembled by hand from two summary files of the experiment machine, and
the per-task records behind it are not in this snapshot.

## Experiment 2 (Section 3.2, Fig. 3)

`repair_funnel_ext.json` is the output of `e2e_repair.py` with `AGG=1`. It counts, over the 4500 accepts of
experiments 1 and 3 (`by_source`), what each repair did under each rule. A key of `rules` names the proposer
and the rule, for example `LLM judge|replace` or `LLM judge|add`. The fields are `changes` (accepts whose
specification changed, with a body that verifies under the new one), `stays_correct`, `broken` (a correct
accept whose new specification is no longer proved to imply the reference; `broken_undecided` counts those
of them for which the check could not be posed on the new specification), `repaired` and `still_not_shown`.
Fig. 3 shows the rows `LLM judge|replace`, `determinacy rewrite|replace`, `mined invariants|replace` and
`all four proposers|add`.
The proposal of the invariant miner already is S with the mined clauses conjoined, so its `replace` row is
the repair as it ran, and it adds by design. The ablation of Section 3.2 compares the `replace` and `add`
rows of the LLM judge and the determinacy flag.

## Experiment 3 (Section 3.3, Fig. 4)

`clover_multi_summary.json` is the output of `clover_multi_score.py`: per model and pipeline the three runs on
CloverBench, with the mean, the smallest and the largest number of correct tasks and the number of tasks that
are correct in at least two runs (`majority`).

`mbpp_multi_summary.json` is the summary that `mbpp_rescore2.py` wrote: per model and pipeline one run on
MBPP-DFY, with the verdict on every accepted program (`correct`, `not-shown`, or `interface` for a program whose
signature differs from the task's).

`e2e_fig3.json` is the output of `e2e_fig3.py`. For each benchmark and model it lists the tasks that are
correct with the published pipeline and with ours, before and after step 3 (`*_before`, `*_after`, on
CloverBench the tasks that are correct in at least two of the three runs, together with the count of each
run). Fig. 4 and the pair counts of Section 3.3 compare the published pipeline as it is (`clover_before`,
`baseline_before`) with our full pipeline (`ours_after`).

## What is not here

The raw records of the runs (every prompt, model response, attempt, accepted program and verifier output) are
not part of this snapshot. For experiment 1 and the audit of the given specifications the files above keep one
record per accept or per specification. For experiments 2 and 3 they keep counts per repair and task lists per
model, so those numbers can be checked for consistency with the paper but not recomputed from individual
programs.
