# Our pipeline on MBPP-DFY: five candidate postconditions (experiment 3)

Source: `pipeline/mbpp_boost.py`. dafny-synthesis draws up to five fresh attempts per task with dynamic few-shot
prompting, so on this benchmark our step 1 also draws K = 5 candidate postconditions and uses few-shot examples.
The examples come from the public 50-example file of dafny-synthesis: the first three entries whose
postcondition calls no helper function of its own example, leaving out the task itself. The model sees the
description and the signature of the reference method, never its postcondition.

Identical candidates are dropped, a candidate that Dafny rejects gets one corrective call, and the well-formed
candidates are ordered without the reference: those that the determinacy query proves first, those it flags
last. The candidates go to the code loop below in this order, with five attempts each, until one program
verifies with the ensures lines of its candidate unchanged. If none does, one more postcondition is generated
with the prompt of `step1_specification.md`.

## Candidate postcondition

Sent five times per task (see the sampling settings in `pipeline/README.md`).

~~~text
Given a Dafny method signature and a natural-language description, write the POSTCONDITION (one or more 'ensures ...' lines) capturing FULL correctness: it must pin down the output uniquely wherever the description does. Use ONLY the signature's parameters and result variable with plain Dafny expressions and quantifiers; do NOT call helper functions or predicates. Return ONLY the ensures lines.

Examples:
{{three examples in the form shown below, separated by empty lines}}

Task:
{{task description, at most 1500 characters}}
Signature:
{{signature and requires lines of the reference method}}
Postcondition:

~~~

## Form of one example

Three of these stand in the slot of the examples.

~~~text
Task:
{{description of the example task}}
Signature:
{{its method signature}}
Postcondition:
{{its ensures lines}}
~~~

## When Dafny rejects a candidate

Sent once for that candidate, in place of the first prompt.

~~~text
{{the first prompt}}
Your previous postcondition is NOT valid Dafny here. Dafny reports:
{{the last 1200 characters of the output of Dafny, cut after the first 800}}
Previous attempt:
{{the postcondition of the previous answer}}
Rewrite it as self-contained, syntactically valid ensures lines only.
~~~

## Code loop, first call

Sent once per candidate that is tried.

~~~text
Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY as given. You may add helper functions, predicates and lemmas before the method, and any loop style with the invariants and asserts the verifier needs. Return ONLY a ```dafny code block.

{{signature and requires lines of the reference method}}
    {{the ensures lines of the candidate}}

~~~

## Code loop, after a failed attempt

Sent in place of the first prompt.

~~~text
{{the first prompt}}
Previous attempt:
```dafny
{{the program of the previous answer, at most 3500 characters}}
```
{{if an ensures line was changed}}You changed or dropped the given ensures lines; keep them EXACTLY.
{{end if}}{{if the program does not verify}}Verification failed:
{{the end of the output of Dafny, at most 1200 characters}}
{{end if}}Fix it. Return ONLY a ```dafny code block.
~~~
