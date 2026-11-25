# Step 2: the body, with the output of the verifier as feedback

The model writes the body and the proof annotations for a fixed signature, precondition and postcondition, and
gets the output of the verifier back when the program does not verify. Each call is a single message: the
feedback prompt contains the first prompt again and the output of the verifier for the latest attempt. It
contains neither the failed program nor the earlier attempts. When Dafny does not finish within 90 seconds, the
word TIMEOUT stands in the place of its output, in the corrected loop also when Dafny reports that a proof ran
into its time limit. The loop exists in two forms.

## The loop of the first pass (`pipeline/big_run.py`, function `gen_code_raw`)

Used in the first pass of experiment 1, and whenever a repair of experiment 2 that comes from
`big_run.iterated_repair` (LLM judge, determinacy flag, mined invariants) needs a body for a changed
postcondition. The reported runs allowed five attempts (`ITERS=5`). The answer is the content of the first code
block.

## First pass, first call

Sent once per specification.

~~~text
Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. Add the body and ALL needed loop invariants. Use a WHILE loop with explicit invariants, NOT a for loop. Return ONLY a ```dafny code block.

{{preamble and helper declarations of the task}}
{{signature, requires lines and the ensures lines of S}}

~~~

## First pass, after a failed verification

Sent in place of the first prompt.

~~~text
{{the first prompt}}

FAILED verification:
{{the end of the output of Dafny, at most 1200 characters}}

Fix it with a while loop and correct invariants. Return ONLY a ```dafny code block.
~~~

## The corrected loop (`pipeline/fix_harness.py`, function `gen_code_fixed`)

Written after the first pass of experiment 1 (see the stages A to E in `pipeline/README.md`). It removes
declarations that the answer repeats from the preamble, retries an empty response without counting it as an
attempt, uses the strict verifier call, and can reject an answer that verifies only through a bypass
(`guard=True`) or that does not carry the given ensures lines (`enforce_ens`). It has two wordings. The wording
`orig` is the one of the first pass and is used where tasks of experiment 1 are run again: stage B
(`fix_rescue_b.py`, five attempts), stage D (`fix_bypass.py`, four attempts, bypasses rejected) and stage E
(`fix_rerun_e.py`, function `code_loop_locked`, five attempts, bypasses rejected). The wording `v2` does not ask
for a loop where none is needed. It is used by our pipeline on CloverBench (`clover_v2.py`, five attempts) and
for the body under S ∧ C in step 3 (`wit2.py`, function `recode`, five attempts, bypasses rejected).

## Wording `orig`, first call

Sent once per specification.

~~~text
Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. Add the body and ALL needed loop invariants. Use a WHILE loop with explicit invariants, NOT a for loop. Return ONLY a ```dafny code block.

{{preamble and helper declarations of the task}}
{{signature, requires lines and the ensures lines of S}}

~~~

## Wording `orig`, after a failed verification

Sent in place of the first prompt. When the answer holds no method, the words "the answer did not contain the
method" stand in the place of the output of Dafny.

~~~text
{{the first prompt}}

FAILED verification:
{{the end of the output of Dafny, at most 1500 characters}}

Fix it with a while loop and correct invariants. Return ONLY a ```dafny code block.
~~~

## Wording `v2`, first call

Sent once per specification.

~~~text
Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. Add the body. If the body needs a loop, write a WHILE loop with explicit invariants (not a for loop); if it needs no loop, do not add one. Do not repeat declarations that are already given above the method. Return ONLY a ```dafny code block.

{{preamble and helper declarations of the task}}
{{signature, requires lines and the ensures lines of S}}

~~~

## Wording `v2`, after a failed verification

Sent in place of the first prompt. When the answer holds no method, the words "the answer did not contain the
method" stand in the place of the output of Dafny.

~~~text
{{the first prompt}}

FAILED verification:
{{the end of the output of Dafny, at most 1500 characters}}

Fix it; if there is a loop, correct its invariants. Keep the ensures EXACTLY. Return ONLY a ```dafny code block.
~~~

## Both wordings, when the program verifies but an ensures line was changed

Sent in place of the first prompt where the loop enforces the given ensures lines.

~~~text
{{the first prompt}}

Your answer changed or dropped an ensures clause. Keep ALL the given ensures lines EXACTLY as written, character for character. Return ONLY a ```dafny code block.
~~~

## Both wordings, when the program verifies only through a bypass

Sent in place of the first prompt where the loop rejects bypasses. The rules are in `pipeline/fix_cheat.py`
(assume, `{:axiom}`, `{:verify false}`, `{:extern}`), and step 3 also rejects `decreases *` and `expect`.

~~~text
{{the first prompt}}

Your answer verifies only through a verification bypass ({{the bypasses that were found, for example: uses 'assume'}}). That is not allowed. Remove it and make the proof go through honestly. Return ONLY a ```dafny code block.
~~~
