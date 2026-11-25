# The repairs that step 3 is compared with (experiment 2)

Source: `pipeline/big_run.py`, functions `judge_reason`, `_llm_strengthen` and `iterated_repair`. The LLM judge
and the determinacy flag run as they were designed: when the postcondition is flagged, the model writes a
stronger postcondition that takes the place of S, and a body is generated for it with the code loop of the first
pass (`step2_code.md`). This repeats for up to five rounds (`REPAIR_ROUNDS=5`) while the new postcondition is
flagged again and a body verifies. The third repair, mined invariants, makes no model call for the
specification. For a method that returns an integer or an integer array, `miner2.py` runs the accepted program
on generated inputs, and the invariants that hold on the outputs but do not follow from S are appended as
ensures lines.

## LLM judge: is the postcondition complete?

Sent once per round. The postcondition counts as flagged when the last line of the answer contains WEAK.

~~~text
Judge whether this Dafny postcondition FULLY and TIGHTLY specifies the task so that an incorrect implementation cannot satisfy it. First give one sentence of reasoning, then on the last line answer COMPLETE or WEAK.

Task:
{{task description, at most 1000 characters}}

Postcondition:
{{the ensures lines of S}}

~~~

## The stronger postcondition (LLM judge and determinacy flag)

Sent when the postcondition is flagged, by the judge or by the determinacy query of `det_gate.py`, which is a
lemma and has no prompt. The ensures lines of the answer replace S.

~~~text
This Dafny postcondition is too WEAK. Write a STRONGER, complete postcondition (add ensures) so a wrong program cannot satisfy it. Return ONLY ensures lines.

Signature:
{{signature and requires lines of the method}}

Description:
{{task description, at most 1000 characters}}

Weak:
{{the ensures lines of S}}{{if the repair is the LLM judge}}

A reviewer noted: {{the answer of the judge, at most 400 characters}}{{end if}}

~~~

The rule "add" of Fig. 3 for these proposers is a post-hoc analysis and has no prompt of its own: `conj_arms.py`
takes the stored stronger postconditions and accepts them by adding instead of replacing.
