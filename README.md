# Acceptance is not correctness: witness-guided specification repair for trustworthy LLM vericoding

Code, prompts and results of the paper with this title by Patrik Pánczél, Zoltán Kárász and László Gulyás,
submitted to ESANN 2027 and under review.

A language model can write a Dafny program together with its formal specification, and the verifier then
proves that the two agree. Such an accept is usually counted as success, although the proof is only as
trustworthy as the specification that the model wrote. The paper measures how often an accept is correct
when the model-written postcondition S is judged against the benchmark's reference postcondition G, which the
model never sees: an accept is correct when the verifier proves S ⇒ G. For eleven models, 6 to 20% of a
model's accepts on the tasks with a natural-language description are not shown correct, and this share is
larger for the models with more accepts. The paper then compares ways to repair a specification that looks
too weak. In the experiments, repairs that rewrite the specification also break correct ones. Witness-guided
repair looks for a witness, an input on which S admits two different outputs, lets a model write a clause C
that excludes the unintended output, and keeps S ∧ C only if a body verifies under it. Since S ∧ C implies S,
a correct specification stays correct.

This repository holds what stands behind the numbers and the figures of the paper.

| path | content |
|---|---|
| `results/` | the frozen outputs of the experiments, described in `results/README.md` |
| `paper_numbers.py` | recomputes every reported number of the paper from `results/` and compares it with the printed value |
| `figures/` | the scripts of the four figures and the images they produce |
| `pipeline/` | the experiment code, described in `pipeline/README.md` |
| `prompts/` | every prompt behind a reported number, word for word, in six files written from the code (see `prompts/README.md`) |
| `tasks/` | the task lists of the experiments (see `tasks/README.md`) |

## Checking the numbers

No model, no verifier and no package beyond the Python standard library is needed.

```bash
python paper_numbers.py
```

The script prints one line for each number of the paper, in the order of the sections, with `ok` when the
value computed from `results/` equals the printed one and `DIFF` otherwise. It ends with
`All numbers agree with the paper.` and returns exit code 1 if any number differs. A few lines of its output:

```
Sections 2.3 and 3.1, Fig. 2: acceptance against correctness (results/gen_audit.jsonl, desc_len.json)
  ...
  ok   smallest share of a model's accepts that are not shown correct, %              6 (6.5)
  ok   largest share of a model's accepts that are not shown correct, %               20 (20.3)
  ...
  ok   Spearman rho, accepts against correct share                                    -0.72 (-0.7182)
  ok   its permutation p-value                                                        0.015 (0.0154)
```

The numbers of experiment 1 and of the audit of the given specifications are recomputed from one record per
accept or per specification, including the correlations, the permutation p-values and the bootstrap interval
(with fixed seeds, so the output is the same on every run). The numbers of experiments 2 and 3 are derived
from the counts per repair and the task lists per model that the experiment scripts wrote. The script was
run with Python 3.11, 3.12 and 3.13.

## Redrawing the figures

```bash
pip install matplotlib==3.10.9
python figures/fig1_pipeline.py      # Fig. 1, the pipeline (no data)
python figures/fig2_reliability.py   # Fig. 2, from results/bigrun_v7_described.json
python figures/fig3_repair.py        # Fig. 3, from results/repair_funnel_ext.json
python figures/fig4_endtoend.py      # Fig. 4, from results/e2e_fig3.json
```

Each script writes a PNG of the same name into `figures/` at 600 dpi. With matplotlib 3.10.9 the four images
are identical, pixel for pixel, to the figures of the submitted paper. Other versions of matplotlib were not
tested. `python figures/fig2_reliability.py all` draws the variant of Fig. 2 for all 378 tasks, which the
paper reports only in the text.

## Running the experiments again

`pipeline/` contains the scripts that produced the results, as they were run, and `pipeline/README.md` says
which script belongs to which experiment, where each prompt is, which sampling settings the model calls use,
and what a run needs: Dafny, the benchmark repositories, and access to the models through environment
variables. No endpoint and no key is stored in the code. A new run needs model calls and a long verification
time, and it will not give exactly the frozen counts, because the models are sampled and hosted models change.

## Prompts and tasks

`prompts/` holds the prompts of the three steps and of the compared repairs, and `tasks/` lists the tasks of
each experiment. Both folders can be checked against the code and the frozen results without a model and
without a verifier.

```bash
python prompts/make_prompts.py --check    # the prompt files equal the text in pipeline/
python prompts/test_prompts.py            # the prompts that the code sends equal the prompt files (needs pyyaml)
python tasks/make_task_lists.py --check   # the task lists agree with results/
```

## What this snapshot does not contain

The raw records of the runs, that is every prompt with its response, every accepted program and every verifier
output, are not included. The runner of the DafnyBench annotation comparison in Section 3.1 and the lists of
its tasks are not included either, and its counts are in `results/given_spec_step2.json`. The benchmarks
themselves are not part of this repository. They are available from their authors: the vericoding benchmark
(https://github.com/Beneficial-AI-Foundation/vericoding), Clover and CloverBench
(https://github.com/ChuyueSun/Clover), MBPP-DFY and dafny-synthesis
(https://github.com/Mondego/dafny-synthesis) and DafnyBench (https://github.com/sun-wendy/DafnyBench).

## Third-party material

Three files carry material of the vericoding benchmark, which is released under the MIT License (reproduced in
`third_party/vericoding-LICENSE.txt`). The audit records `results/given_audit.jsonl` and
`results/given_audit_more.jsonl` quote the precondition and the postcondition of each audited task, and
`pipeline/fix_cheat.py` restates the bypass rules of its pipeline.

## Citation

```bibtex
@unpublished{panczel2026acceptance,
  title  = {Acceptance is not correctness: witness-guided specification repair for trustworthy {LLM} vericoding},
  author = {P{\'a}ncz{\'e}l, Patrik and K{\'a}r{\'a}sz, Zolt{\'a}n and Guly{\'a}s, L{\'a}szl{\'o}},
  note   = {Submitted to ESANN 2027},
  year   = {2026}
}
```

The code is released under the MIT License, see `LICENSE`.
