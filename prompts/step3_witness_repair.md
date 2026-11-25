# Step 3: witness-guided repair

Source: `pipeline/wit2.py`. Used in experiment 2 on every accept whose postcondition S the determinacy query
flags: on the accepts of experiment 1 by `wit2.py` itself, and on the accepts of the two pipelines of experiment
3 by `e2e_repair.py`. The model proposes, and a check decides each time: a witness counts only if execution or a
proof confirms it, a clause C has to be well-formed in the method, and S ∧ C replaces S only if a body verifies
under it. The model is never asked to rewrite the existing lines of S. The defaults of the script, which it
calls the standard budget, are three rounds per accept (`ROUNDS`), two answers per witness search (`WIT_TRIES`),
two answers per clause (`CLAUSE_TRIES`) and five attempts for the body (`ITERS`).

## 1. The witness

Function `find_witness2`. The model is asked for an input and two different outputs that S both admits.
`check_witness` then confirms that the input satisfies the precondition, that both outputs satisfy S and that
they differ, by running the compiled predicates or, where they do not compile, by a proof of the same facts.
When no answer of the model is confirmed, an enumeration over small integers, booleans and integer arrays is
tried without a model call (`witness_repair.find_witness`, for methods with one return value).

## Witness search, first call

Sent once per round.

~~~text
You are checking a Dafny postcondition for under-specification.

Task description:
{{task description, at most 1500 characters}}

{{if the task has declarations above the method}}Declarations available to the specification:
{{these declarations, at most 3000 characters}}

{{end if}}Method signature and precondition:
{{signature and requires lines of the method}}

Postcondition under test:
    {{the ensures lines of the current postcondition S}}

Find ONE concrete input that satisfies the precondition, and TWO DIFFERENT outputs that BOTH satisfy the postcondition under test for that input. If you can, choose the pair so that one output is what the task description asks for and the other is clearly wrong: that exposes a missing requirement. Keep it tiny (lengths at most 4, small numbers).

If the postcondition admits exactly one output for every valid input, answer with the single word DETERMINATE.

Otherwise answer in exactly this format and nothing else:
INPUT:
<Dafny statements declaring every parameter: {{the parameters with their types, or (none)}}>
OUTPUT1:
<Dafny statements declaring the return variable(s): {{the return variables with their types}}>
OUTPUT2:
<the same variable(s) with a different value>

Rules for the statements: one `var name: type := value;` per variable, literal values only. Sequences: `var s: seq<int> := [1, 2, 3];`. Arrays: `var a: array<int> := new int[3] [1, 2, 3];` (empty: `new int[0]`). Strings: `var t: string := "ab";`. No method calls, no loops, no assume or assert. If the method has no parameters, leave INPUT empty.
~~~

## Witness search, after a rejected answer

Sent in place of the first prompt. The reason is the one the checker returns, for example that the answer was
not in the format, that an output does not satisfy the postcondition, or that the two outputs are the same
value.

~~~text
{{the first prompt}}

Your previous answer was rejected by the checker: {{the reason the checker gives}}.
Previous answer:
{{the previous answer, at most 700 characters}}

Give a corrected answer in the same format, or DETERMINATE.
~~~

## 2. The clause for a confirmed witness

Function `arbiter`. The model first says whether the description leaves the choice between the two outputs open.
If it answers INTENDED, the specification is left as it is. If it answers UNINTENDED, it names the correct
output and writes additional ensures lines C. The lines that keep S ∧ C well-formed are then evaluated on the
witness (`check_clause`): they have to accept the output that the model called correct and reject the other one,
or both if it called neither correct. A clause that fails goes back to the model once with the reason. A clause
for which the evaluation gives no result is passed on to the last test, a body that verifies under S ∧ C.

## Arbiter, first call

Sent once per confirmed witness.

~~~text
A Dafny method has to implement this task:
{{task description, at most 1500 characters}}

{{if the task has declarations above the method}}Declarations available to the specification:
{{these declarations, at most 3000 characters}}

{{end if}}Signature and precondition:
{{signature and requires lines of the method}}

Its current postcondition:
    {{the ensures lines of the current postcondition S}}

For this input
    {{the input of the witness as Dafny statements, or (no parameters)}}
the current postcondition accepts BOTH of the following outputs.
Output A:
    {{the first output of the witness as Dafny statements}}
Output B:
    {{the second output of the witness as Dafny statements}}

According to the task description, is it INTENDED that both outputs are acceptable for this input (the task leaves the choice open), or UNINTENDED (the task determines the answer, so at least one of the two is wrong)?
Line 1: exactly INTENDED or UNINTENDED.
If UNINTENDED, line 2: `CORRECT: A`, `CORRECT: B` or `CORRECT: NEITHER`. Then, in a ```dafny block, write ADDITIONAL postcondition lines (each starting with `ensures`) that every correct output of the task satisfies for every valid input, and that reject the wrong output above. The existing ensures lines stay exactly as they are: do not repeat or rewrite them. Use only the method's parameters, its return variable(s){{if the task declares functions}} and the functions already declared for this task ({{names of at most 12 of these functions}}){{end if}}. Do not introduce new functions.
~~~

## Arbiter, after a rejected clause

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your previous answer:
{{the previous answer, at most 1200 characters}}

It was rejected: {{the reason of the rejection}}.
Answer again in the same format (line 1 UNINTENDED, line 2 CORRECT: ..., then the ```dafny block with corrected ADDITIONAL ensures lines only).
~~~

## 3. The paths without a witness

Function `flag_strengthen` runs when no witness could be confirmed and only the flag of the determinacy query
stands. Function `force_det` runs for the accepts whose postcondition the model called complete although the
solver could not prove that it determines the output. There the solver decides: the added lines are kept only if
the determinacy query is proved with them. Both follow the same rule of adding.

## Flag only, first call

Sent when no witness was confirmed.

~~~text
A Dafny method has to implement this task:
{{task description, at most 1500 characters}}

{{if the task has declarations above the method}}Declarations available to the specification:
{{these declarations, at most 3000 characters}}

{{end if}}Signature and precondition:
{{signature and requires lines of the method}}

Its current postcondition:
    {{the ensures lines of the current postcondition S}}

A solver check could NOT prove that this postcondition determines the output uniquely for every valid input, so it may be missing a requirement of the task.
According to the task description, is the output of the method uniquely determined by its input?
Line 1: exactly one of
  INTENDED    (the description leaves the choice open, several different outputs are acceptable)
  COMPLETE    (the output is unique and the current postcondition already pins it down)
  UNINTENDED  (the output is unique but the current postcondition does not pin it down)
If UNINTENDED, then write, in a ```dafny block, ADDITIONAL postcondition lines (each starting with `ensures`) that every correct output of the task satisfies for every valid input and that state the missing requirement(s). The existing ensures lines stay exactly as they are: do not repeat or rewrite them. Use only the method's parameters, its return variable(s){{if the task declares functions}} and the functions already declared for this task ({{names of at most 12 of these functions}}){{end if}}. Do not introduce new functions.
~~~

## Flag only, after a rejected answer

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your previous answer:
{{the previous answer, at most 1200 characters}}

It was rejected: {{the reason of the rejection}}.
Answer again in the same format (line 1 UNINTENDED, then the ```dafny block with corrected ADDITIONAL ensures lines only).
~~~

## Solver decides, first call

Sent in the pass over the accepts that the model called complete.

~~~text
A Dafny method has to implement this task:
{{task description, at most 1500 characters}}

{{if the task has declarations above the method}}Declarations available to the specification:
{{these declarations, at most 3000 characters}}

{{end if}}Signature and precondition:
{{signature and requires lines of the method}}

Its current postcondition:
    {{the ensures lines of the current postcondition S}}

A solver was asked to prove that this postcondition admits at most one output for every valid input, and it could NOT. So either the postcondition leaves something open, or it pins the output down only in a way the solver cannot follow.
If the task description itself leaves the choice open (several different outputs are acceptable), answer with the single word INTENDED.
Otherwise write, in a ```dafny block, ADDITIONAL postcondition lines (each starting with `ensures`) that every correct output satisfies and that make the unique output explicit: state directly what is still open (for example the exact length, the value of every element, which index is returned when several qualify, the order of the elements). The existing ensures lines stay exactly as they are: do not repeat or rewrite them. Use only the method's parameters, its return variable(s){{if the task declares functions}} and the functions already declared for this task ({{names of at most 12 of these functions}}){{end if}}. Do not introduce new functions.
~~~

## Solver decides, after a rejected answer

Sent in place of the first prompt.

~~~text
{{the first prompt}}

Your previous answer:
{{the previous answer, at most 1200 characters}}

It was rejected: {{the reason of the rejection}}.
Answer again: a ```dafny block with corrected ADDITIONAL ensures lines only, or the single word INTENDED.
~~~

## 4. The body under S ∧ C

Function `recode`. The accepted body is first verified again under S ∧ C without a model call. Only when that
fails is the model asked, through the code loop of step 2 in the wording `v2` (see `step2_code.md`), where the
text below stands in the place of the specification. If no body verifies, the accept keeps S and its old body.

## Specification part of the code prompt

Placed in the code prompt of step 2.

~~~text
{{signature and requires lines of the method}}
    {{the ensures lines of S followed by the added clauses C}}

A previous version of this method verified against the postcondition WITHOUT its last ensures line(s). Reuse and adapt it (strengthen the loop invariants if needed):
```dafny
{{the accepted program for S}}
```
~~~
