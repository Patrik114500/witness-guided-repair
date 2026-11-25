# The experiment code

These are the scripts that produced the results of the paper, as they were run. They are research code: each
script is one stage of an experiment, reads the outputs of earlier stages and writes its own, and the parameters
are environment variables read at the top of the file. The prompts are part of the code, at the places named
below. Nothing in this folder is needed to check the numbers or to redraw the figures, which work from the
frozen files in `../results` (see the top-level README).

## What the scripts expect

The scripts were written for one machine and keep its layout. A run needs the following.

| what | where the scripts look for it |
|---|---|
| Dafny 4.x with Z3 | `DAFNY` (default `~/dafny/dafny/dafny`) |
| the vericoding benchmark, https://github.com/Beneficial-AI-Foundation/vericoding | `~/vericoding`, the Dafny tasks through `BENCH` (default `~/vericoding/benchmarks/dafny`) |
| Clover and CloverBench, https://github.com/ChuyueSun/Clover | `~/clover` |
| MBPP-DFY and the dafny-synthesis pipeline, https://github.com/Mondego/dafny-synthesis | `~/dafny-synthesis`, and the copy of MBPP-DFY that ships with Clover under `~/clover/dataset` |
| DafnyBench, https://github.com/sun-wendy/DafnyBench | `~/DafnyBench` |
| Verus and Lean 4, only for the given-specification runs in those languages | `~/verus_install`, `~/.elan` |
| Python 3 with `pyyaml` | |

The models are reached through `vericode_compete.py`. The prefix of a model id selects the provider: `aoai:`
is an Azure OpenAI deployment, `claude:` and `grok:` are deployments of the same Azure AI Foundry resource,
`gemini:` is Google AI Studio, and an id without a prefix is a local model behind an OpenAI-compatible server
such as Ollama. Endpoints and keys come from the environment and none is stored in the code.

```bash
export AZ_EP=https://<your-resource>.services.ai.azure.com    # Azure OpenAI / AI Foundry
export AZURE_API_KEY=...                                      # or the key in ~/.azure_openai_key
export OLLAMA=http://localhost:11434/v1/chat/completions      # local models
export GEMINI_API_KEY=...                                     # optional, or ~/.gemini_key
export CLOSED_PROXY=http://proxy:port                         # optional HTTP proxy for the cloud calls
```

Clover's generators call their model through the `sglang` frontend. `sglang_shim_clover.py` is a small stand-in
that sends those calls to the same endpoint as ours, so that both pipelines use the same model. The scripts
import it as `sglang` from `~/clover/shim`, so it has to be copied there as `sglang.py`.

Intermediate outputs are JSON-lines files under `/tmp` (for example `/tmp/big_run*.jsonl`,
`/tmp/fix_scores5.jsonl`, `/tmp/wit2_<model>.jsonl`). Each script names its inputs and outputs in its
docstring. Most scripts can be resumed: they skip the records that the output file already holds.

## Names in the code and names in the paper

The code grew over several weeks and keeps its working names. The paper's terms map to them as follows.

| in the code | in the paper |
|---|---|
| big run | experiment 1 (steps 1 and 2 on verina, numpy_simple and verified_cogen) |
| arm | a repair |
| reliable, `rel` | correct: the verifier proves S ⇒ G |
| weak | not shown correct |
| canonical | the accepted body verifies under the benchmark's own signature and precondition |
| result 1, figure 1 | Section 3.1 first paragraph, Fig. 2 |
| result 4 | Section 3.1 second paragraph (specification given) |
| result 2, figure 2 | Section 3.2, Fig. 3 |
| result 3, figure 3 | Section 3.3, Fig. 4 |
| `arm_ours` in `big_run.py` and in the stored records | the mined-invariants repair |
| witness arm v2, `wit2.py` | the witness search and the arbiter of step 3 |
| the row "all four proposers, add" of the repair tables | "ours" in Fig. 3: step 3 with its four proposers |
| stages A to E | corrections of the harness after the first pass of experiment 1 |

Dates in the docstrings are those of November 2026, and "published" always refers to the pipeline or the
numbers of the cited benchmark paper.

## Shared modules

| file | role |
|---|---|
| `vericode_compete.py` | model access, the Dafny calls and the loader of the task files (imported as `V`) |
| `fix_harness.py` | the corrected harness: the strict verifier call `dverify2` (an unfinished proof is not a proof), the model call with retries and cost tracking (`Asker`), removal of repeated preamble members, the code loop `gen_code_fixed`, and the eleven models `P11` |
| `fix_hdr.py` | parser of the method header of a task (signature, requires, ensures) |
| `fix_canon.py` | restates an accepted method with the benchmark's own signature and precondition |
| `fix_cheat.py` | the bypass rules of the published vericoding pipeline (assume, axiom), restated from its `cheat_checker.py` (MIT License, see `../third_party/vericoding-LICENSE.txt`), and two further ones that we also reject (`{:verify false}`, `{:extern}`) |
| `fix_oracle.py` | the correctness check S ⇒ G and the determinacy check |
| `det_gate.py`, `miner2.py`, `witness_repair.py`, `dafny_mut.py`, `mut_gate.py`, `nl_gated_compare.py` | earlier modules that the later ones still import: the determinacy lemma, the invariant miner, the first witness search, the first version of the loop, and mutation-based signals that the paper does not use |

## Experiment 1: what an accept is worth

| file | role |
|---|---|
| `big_run.py` | steps 1 and 2 for every model and task, with every prompt, response, attempt and verifier output stored. The prompts are in `gen_spec_raw` (specification from the description), `gen_code_raw` (body), `judge_reason` (LLM judge) and `_llm_strengthen` (the stronger postcondition of the two replacing repairs). The reported run used `ITERS=5` and `REPAIR_ROUNDS=5`. |
| `fix_rescue_a.py`, `fix_rescue_b.py`, `fix_score.py`, `fix_bypass.py`, `fix_rerun_e.py` | stages A to E: tasks that the first pass lost to a harness artifact are re-assembled or re-run (repeated preamble member, empty model response, an accept that needed a bypass, a method header cut at a line break) |
| `fix_oracle_v4.py`, `fix_audit5.py`, `fix_audit6.py` | re-scoring of every accept: two-state postconditions, the specification of record read from the accepted program, and everything checked again with the strict verifier call |
| `fix_state.py`, `fix_state5.py` | one loader of the final state of every task, used by all later stages |
| `fix_table5.py` | the tables of experiment 1. `TASKFILTER=1` leaves out the nine tasks without a posable contract and `TASKSET=described` keeps the described tasks. Wrote `bigrun_v7.json` and `bigrun_v7_described.json`. |
| `boot_ci.py` | bootstrap interval of the correlation over tasks. Wrote `boot_ci7.json`. |
| `gen_audit.py` | one record per accept with the correctness verdict and the reference-free certificates. Wrote `gen_audit.jsonl`. |
| `rev_entail.py`, `ce_test.py` | two supplementary checks of the accepts that are not shown correct (reverse entailment with determinacy, and execution against the reference). The paper does not report them. |

## Specification given (Section 3.1, second paragraph)

| file | role |
|---|---|
| `given_audit.py`, `given_audit2.py` | the reference-free audit of the benchmark-given specifications of the eight Dafny datasets: determinate (D), admits every output (A), admits every output of the right shape (B), a body that ignores the task verifies (T). Wrote `given_audit.jsonl` and `given_audit_more.jsonl`. |
| `given_witness.py`, `given_impact3.py` | the witness search on the undecided specifications, and the join of the audit with the published per-task results of eight models. Wrote `given_impact3.json`. |
| `cfs_v2.py`, `cfs_v3_cont.py` | step 2 on given Dafny specifications (numpy_simple, verina), under our acceptance rule and under the published one |
| `xlang_bench.py`, `xlang_v2.py`, `xlang_v3.py`, `xlang_bypass_lists.py` | the same comparison on the Verus and Lean tasks |
| `plain_lock_check.py`, `strict_reval.py` | independent re-checks of the accepts behind these comparisons (specification kept verbatim, strict verifier call) |
| `boot_given.py` | helper functions that the audit imports. Its own protocol, a loop with a self-built example library, is not part of the paper. |

The runner of the DafnyBench annotation comparison (80 against 89 solved tasks with gpt-4o) is not in this
snapshot. Its counts are in `../results/given_spec_step2.json`.

## Experiment 2: the four repairs

| file | role |
|---|---|
| `arms_rerun.py` | the LLM judge, the determinacy flag and the mined invariants, run unchanged (`big_run.iterated_repair`) on the accepts whose specification of record changed after the first pass |
| `wit2.py` | witness-guided repair. `WIT_PROMPT` asks the model for a witness, `check_witness` confirms it by execution or proof, `ARB_PROMPT` is the arbiter, and `FLAG_PROMPT` and `FORCE_PROMPT` are the paths without a witness. A clause is kept only if a body verifies under S ∧ C. Besides the bypass rules it rejects `decreases *` and `expect`. It ran in three passes per model (plain, then `PASS2=1`, then `PASS3=1`); the shell script that chained them is not in this snapshot. |
| `conj_arms.py`, `conj_bypass_check.py` | the post-hoc ablation: the stored proposals of the replacing repairs, accepted by adding instead |
| `repair_full.py`, `repair_funnel.py` | the counts of broken and repaired accepts on the accepts of experiment 1 |
| `e2e_repair.py` | the same repairs on the accepts of experiment 3. `AGG=1` wrote `repair_funnel_ext.json`, the counts over all 4500 accepts. |

## Experiment 3: against two published pipelines

| file | role |
|---|---|
| `clover_v2.py` | CloverBench with both pipelines and the same model: `MODE=clover` runs Clover's own generators and soundness check, `MODE=ours` runs our steps 1 and 2 |
| `clover_gated.py` | loader of CloverBench and helper functions for the Clover runs |
| `clover_multi_score.py` | scores every accepted record of both pipelines by one rule. Wrote `clover_multi_summary.json`. |
| `mbpp_repro.py` | reproduction of the dafny-synthesis pipeline (dynamic few-shot prompting, five attempts) |
| `mbpp_boost.py` | our pipeline on MBPP-DFY with K = 5 candidate postconditions |
| `make_mbpp_m.py`, `make_mbpp_fix.py` | write the variants of the two runners that the run scripts start (`mbpp_repro_m.py`, `mbpp_boost_m.py`, `mbpp_boost_fix.py`): task sharding, no temperature for reasoning models, and the header of task 784 taken from the right method |
| `mbpp_rescore2.py` | scores every accepted MBPP program of both pipelines by one rule. Wrote `mbpp_multi_summary.json`. |
| `e2e_fig3.py` | joins the accepts with the repair of step 3. Wrote `e2e_fig3.json`. |
| `ref_audit.py` | the reference specifications of the two benchmarks, put through the audit of `given_audit.py` |

The run scripts `run_arms_rerun.sh`, `run_clover_v3.sh`, `run_e2e_repair.sh`, `run_mbpp_m.sh` and
`run_mbpp_fix.sh` show how the model runs of experiments 2 and 3 were started. The usage line is at the top of
each.

## Order of a full run

Experiment 1 starts with `big_run.py` (one process per model, for example
`MODELS=aoai:gpt-4o ITERS=5 REPAIR_ROUNDS=5 OUT=/tmp/big_run_closed_gpt4o.jsonl python3 big_run.py`), followed by
the stages A to E, the audits, and then `fix_table5.py`, `boot_ci.py` and `gen_audit.py`. Experiment 2 runs
`arms_rerun.py` and `wit2.py` per model, then `conj_arms.py`, `repair_full.py` and `repair_funnel.py`.
Experiment 3 runs the two benchmarks per model and pipeline, scores them with `clover_multi_score.py` and
`mbpp_rescore2.py`, repairs the accepts with `e2e_repair.py`, and ends with `e2e_fig3.py`. Copying the files
named in the tables from `/tmp` into `../results` then lets `../paper_numbers.py` and the figure scripts read
the new run.

A new run will not give the same counts as the frozen ones. The models are sampled at temperature 0.3, hosted
models change over time, and a proof that finishes within the time limit on one machine can time out on
another.
