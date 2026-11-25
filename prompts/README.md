# The prompts

This folder holds every prompt behind a number of the paper, copied out of the code so that it can be read
without reading the scripts. The six files are written by `make_prompts.py` from the syntax tree of the scripts
in `../pipeline`, so the text of a prompt is the text that the code sends. Only the sentences around the prompts
are written by hand.

| file | what it holds | used in | code |
|---|---|---|---|
| `step1_specification.md` | step 1: the postcondition S from the description | experiments 1 and 3 | `big_run.py`, function `gen_spec_raw` |
| `step2_code.md` | step 2: the body, with the output of the verifier as feedback | experiments 1, 2 and 3 | `big_run.py`, function `gen_code_raw`, and `fix_harness.py`, function `gen_code_fixed` |
| `step3_witness_repair.md` | step 3: the witness, the arbiter, the paths without a witness and the body under S ∧ C | experiment 2, on the accepts of experiments 1 and 3 | `wit2.py` |
| `compared_repairs.md` | the LLM judge and the stronger postcondition of the two repairs that replace S | experiment 2 | `big_run.py`, functions `judge_reason` and `_llm_strengthen` |
| `mbpp_dfy.md` | steps 1 and 2 with five candidate postconditions and few-shot examples | experiment 3, our pipeline on MBPP-DFY | `mbpp_boost.py` |
| `given_specification.md` | step 2 for a specification that the benchmark gives, in Dafny, Verus and Lean | Section 3.1, second paragraph | `cfs_v2.py`, `xlang_bench.py`, `xlang_v3.py` |

## How to read a prompt

Each prompt stands in a block between two lines of `~~~`, under a heading and a sentence that says when it is
sent. The prompt is exactly the text between these two lines, without the line break in front of the closing
line. An empty last line in a block therefore means that the prompt ends with a line break.

A part that the code fills in when it runs is a slot, written `{{like this}}`. The words in the slot say what
stands there and which length limit the code applies. A part that is sent only under a condition stands between
`{{if ...}}` and `{{end if}}`. The slot `{{the first prompt}}` stands for the whole first prompt of the same
loop as it was sent for the task, including the line break at its end where it has one.

Every call is a single user message, and no system prompt is set. A feedback prompt does not continue a
conversation. It repeats the first prompt and adds what its block shows. The sampling settings of the calls are
described in `../pipeline/README.md`.

## Checking the files against the code

```bash
python prompts/make_prompts.py --check
```

The command reads the prompts from `../pipeline` again, compares them with the six files and prints `ok` or
`DIFF` for each, with exit code 1 if a file differs. Without `--check` it rewrites the files. An expression in a
prompt for which the script names no slot stops the run, so no part of a prompt can be dropped silently. Only
the Python standard library is needed.

```bash
python prompts/test_prompts.py
```

This second check does not read the text of the code but runs it. It calls the functions of `../pipeline` that
build the prompts, with the model and the verifier replaced by stand-ins that return fixed answers, and compares
every prompt that these functions send with the block of this folder after its slots are filled with the same
values. Its 61 comparisons cover all 38 blocks, and each prompt is equal to its block character for character.
The check needs `pyyaml`, as the pipeline does, and makes no model call and no verifier call.

## What is not here

The two published pipelines of experiment 3 ran with their own prompts. These belong to their repositories and
are not copied here. Clover's generators `gen_spec_from_doc` and `gen_body_from_spec` are in `clover/clover.py`
of https://github.com/ChuyueSun/Clover, and `clover_v2.py` calls them unchanged (`MODE=clover`). The
reproduction of dafny-synthesis builds its two prompts per attempt from the templates
`Scripts/prompts/COT_SPEC_TEMPLATE.file` and `Scripts/prompts/COT_CODE_TEMPLATE.file` and from the 50-example
file of https://github.com/Mondego/dafny-synthesis. The functions `spec_prompt` and `code_prompt` of
`mbpp_repro.py` show how they are put together.

The runner of the DafnyBench annotation comparison is not in this snapshot (see `../pipeline/README.md`), so its
prompt is missing.

The code holds further model calls on which no number of the paper depends: the first harness in
`vericode_compete.py` (`run_cfs`, `run_nlsc`, `gen_ensures`), `nl_gated_compare.py`, the first witness repair
`witness_repair.disambiguate`, which `wit2.py` replaced, the protocol of `boot_given.py`, and the gated variant
of Clover in `clover_gated.py`. Their prompts are not collected here.
