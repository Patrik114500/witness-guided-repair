"""Verification-bypass rules, copied from the published vericoding pipeline
(~/vericoding/src/vericoding/processing/cheat_checker.py) so that our accepts are held to the same standard:
an output that verifies but contains one of these patterns in model-written text is NOT a success, and the
loop tells the model to remove it. The patterns are matched on raw text, exactly as they do."""
import re

RULES = {
    "lean": [(r"\bsorry\b", "uses 'sorry'"), (r"\badmit\b", "uses 'admit'"), (r"\baxiom\b", "introduces an axiom"),
             (r"\bunsafe\b", "uses unsafe operations"), (r"\bUnchecked\.cast\b", "bypasses type checking"),
             (r"@\[extern", "uses extern functions")],
    "dafny": [(r"\{:axiom\}", "uses '{:axiom}'"), (r"\bassume\b", "uses 'assume'")],
    "verus": [(r"assume", "uses 'assume'"), (r"\badmit\b", "uses 'admit'"),
              (r"#\[verifier::external", "uses a verifier external attribute"),
              (r"#\[verifier::exec_allows_no_decreases_clause\]", "uses exec_allows_no_decreases_clause")],
}
# not in their list, but a verifier bypass all the same; we reject it for our own accepts
EXTRA = {"dafny": [(r"\{:verify\s+false\}", "uses '{:verify false}'"), (r"\{:extern", "uses '{:extern}'")], "lean": [], "verus": []}
NL = chr(10)


def cheats(model_text, lang, extra=True):
    """descriptions of the bypasses found in model-written text"""
    out = []
    for pat, desc in RULES[lang] + (EXTRA[lang] if extra else []):
        if re.search(pat, model_text or ""):
            out.append(desc)
    return out


def model_written(candidate, original):
    """the lines of a full candidate file that the benchmark file does not already contain
    (stands in for 'editable sections' when the model returns a whole file, as in Lean)"""
    keep = set(l.strip() for l in (original or "").split(NL))
    return NL.join(l for l in (candidate or "").split(NL) if l.strip() not in keep)


def message(found):
    return ("Your answer verifies only through a verification bypass (%s). That is not allowed. "
            "Remove it and make the proof go through honestly." % ", ".join(found))
