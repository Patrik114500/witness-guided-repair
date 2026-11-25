"""Canonical re-statement of an accepted method (separate module, imported by fix_harness users).

An accept counts under the INTENDED contract only if the accepted body also verifies when the method is
stated with the benchmark's own signature + requires (head) and the generated ensures. A pipeline that
lets the model write its own preconditions can otherwise "verify" by assuming more than the task allows."""
import re

_SPECKW = ("ensures", "requires", "invariant", "decreases", "modifies", "reads")
NL = chr(10)


def split_method(code, name):
    """(text before the method, body text starting at its opening brace) for method `name`, or None."""
    m = re.search(r"method\s+(?:\{:[^}]*\}\s*)*" + re.escape(name) + r"\b", code or "")
    if not m:
        return None
    rest = code[m.start():]
    pos = 0
    for i, ln in enumerate(rest.split(NL)):
        st = ln.strip()
        if i > 0 and st.startswith("{"):
            return code[:m.start()], rest[pos + ln.find("{"):]
        if st.endswith("{") and not st.startswith(_SPECKW):
            return code[:m.start()], rest[pos + ln.rfind("{"):]
        pos += len(ln) + 1
    return None


def canonical_program(code, name, head, gen):
    sp = split_method(code, name)
    if not sp:
        return None
    before, body = sp
    return before + head + NL + "    " + gen + NL + body
