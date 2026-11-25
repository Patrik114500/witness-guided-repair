# Step 1: the postcondition from the description

Source: `pipeline/big_run.py`, function `gen_spec_raw`. Used in experiment 1 for every model and task (K = 1,
also where stage E runs a task again from the start), by our pipeline on CloverBench (`clover_v2.py`,
`MODE=ours`), and as the last candidate on MBPP-DFY when none of the K = 5 candidates of `mbpp_dfy.md` leads to
an accept. The model sees the description, the preamble and the signature with the precondition, never the
reference postcondition.

From every `ensures` in the answer to the end of its line is taken as one clause of S, with a closing semicolon
removed. The postcondition is then checked for well-formedness by verifying the signature with it and a body
that assumes false (`witness_repair.spec_syntax_ok`). A task without a description gets the words "the method's
intended behaviour" in the place of the description. There are at most four calls (`retries=3`). The
postcondition of the last answer is kept even if Dafny still rejects it, and a task whose last answer has no
ensures line gets no specification.

## First call

Sent once per task.

~~~text
Given this Dafny method signature and a natural-language description, write the POSTCONDITION (one or more 'ensures ...' lines) capturing FULL correctness. Return ONLY the ensures lines.

Preamble:
{{preamble of the task, at most 1500 characters}}

Signature:
{{signature and requires lines of the method}}

Description:
{{task description, at most 1500 characters}}

~~~

## When the answer has no ensures line

Sent in place of the first prompt.

~~~text
{{the first prompt}}
Your previous answer contained no 'ensures' lines. Output ONLY ensures lines.
~~~

## When Dafny rejects the postcondition

Sent in place of the first prompt.

~~~text
{{the first prompt}}
Your previous postcondition is NOT valid Dafny. Dafny reports:
{{the last 1200 characters of the output of Dafny, cut after the first 900}}
Previous attempt:
{{the postcondition of the previous answer}}

Valid Dafny ensures-line patterns (copy the SYNTAX, adapt the content):
  ensures 0 <= result < a.Length
  ensures forall i :: 0 <= i < a.Length ==> result >= a[i]
  ensures exists k :: 0 <= k < a.Length && a[k] == result
  ensures result.Length == a.Length && forall i :: 0 <= i < a.Length ==> result[i] == a[i] + 1
Common MISTAKES to avoid: Python syntax (for/in, len(), ** ), calling helper functions that are not
in the preamble, array indexing without the bounds conjunct FIRST, 'ensures' followed by prose.

Rewrite it as syntactically valid Dafny ensures lines only.
~~~
