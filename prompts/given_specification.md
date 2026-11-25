# Step 2 when the benchmark gives the specification (Section 3.1, second paragraph)

Here the model writes only the body and the proof, for the specification of the benchmark. In Dafny the body of
the answer is verified under the benchmark's own specification, and in Verus and Lean an answer that changes a
line of the given specification is rejected. An answer that verifies only through a bypass is rejected with
feedback. The comparison is with the published results of the vericoding benchmark and of DafnyBench for the
same model. The prompts of those published pipelines are their own and are not part of this repository.

## Dafny (`pipeline/cfs_v2.py`, function `solve`)

Used on numpy_simple and verina with five attempts. `cfs_v3_cont.py` continues the same loop with the same texts
under the acceptance rule of the published pipeline (exit code of the verifier).

## Dafny, first call

Sent once per task.

~~~text
Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY as given, do not weaken them. Add the method body and any helper lemmas or functions you need. If the body needs a loop, write a WHILE loop with explicit invariants (not a for loop); if it needs no loop, do not add one. Do not repeat declarations that are already given above the method. Do not use assume or {:axiom}. Return ONLY a ```dafny code block.

{{preamble and helper declarations of the task}}
{{the specification of the benchmark: signature, requires and ensures lines}}

~~~

## Dafny, after a failed verification

Sent in place of the first prompt. When the answer does not hold the method with a body, the words "the answer
did not contain the method NAME with a body", with the name of the method, stand in the place of the output of
Dafny.

~~~text
{{the first prompt}}

FAILED verification:
{{the end of the output of Dafny, at most 1500 characters}}

Fix it; if there is a loop, correct its invariants. Keep the specification intact. Return ONLY a ```dafny code block.
~~~

## Dafny, when the program verifies only through a bypass

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your answer verifies only through a verification bypass ({{the bypasses that were found, for example: uses 'assume'}}). That is not allowed. Remove it and make the proof go through honestly. Return ONLY a ```dafny code block.
~~~

## Verus and Lean (`pipeline/xlang_bench.py`, run through `xlang_v3.py`)

Used on the numpy_simple tasks of the two languages with five calls per task (`ROUNDS=4`). `xlang_v3.py` repeats
the texts of `xlang_bench.py` and adds the bypass feedback. A run of the verifier that takes longer than 200
seconds ends the task.

## Verus, first call

Sent once per task.

~~~text
You write Verus (verified Rust). Below is a function with its FIXED requires/ensures specification and a placeholder body. Write a correct implementation (plus any helper lemmas or loop invariants you need) so that Verus verifies it. You MUST keep the given signature, requires and ensures EXACTLY as written. Return ONLY a ```rust block with the complete function(s); do NOT repeat `use`, `verus! {`, the closing brace or `fn main`.

Preamble:
{{preamble of the task file}}

Specification (fixed):
{{the specification section of the task file}}

~~~

## Verus, when the answer changed the specification

Sent in place of the first prompt.

~~~text
{{the first prompt}}

You modified the given specification (missing lines: {{a Python list of at most three of the missing lines, without their whitespace}}). Keep it EXACTLY. Return ONLY the ```rust block.
~~~

## Verus, after a failed verification

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your attempt failed Verus:
{{output of Verus, last 900 characters}}

Fix it. Return ONLY the ```rust block.
~~~

## Verus, when the program verifies only through a bypass

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your answer verifies only through a verification bypass ({{the bypasses that were found, for example: uses 'assume'}}). That is not allowed. Remove it and make the proof go through honestly. Return ONLY the ```rust block.
~~~

## Lean, first call

Sent once per task.

~~~text
You write Lean 4 (no imports, core only). The file below has definition(s) stubbed with `sorry` and FIXED specification theorem(s) whose proofs are `sorry`. Implement the definition(s) and prove the theorem(s). You MUST NOT change any theorem statement or definition signature. Return ONLY the complete file in a ```lean block.

{{the task file}}
~~~

## Lean, when the answer changed a theorem statement

Sent in place of the first prompt.

~~~text
{{the first prompt}}

You modified the given theorem statement (missing: {{a Python list of at most two of the missing lines, without their whitespace}}). Keep it EXACTLY. Return ONLY the full ```lean file.
~~~

## Lean, after a failed check

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your attempt failed Lean:
{{output of Lean, last 1000 characters}}

Fix it. Return ONLY the full ```lean file.
~~~

## Lean, when the file checks only through a bypass

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your answer verifies only through a verification bypass ({{the bypasses that were found, for example: uses 'assume'}}). That is not allowed. Remove it and make the proof go through honestly. Return ONLY the full ```lean file.
~~~

## DafnyBench

The runner of the DafnyBench annotation comparison is not in this snapshot (see `pipeline/README.md`), so its
prompt cannot be given here.
