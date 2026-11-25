"""Creates mbpp_boost_fix.py from mbpp_boost_m.py: the task's header is taken from the reference file's MAIN method
(the method with a result that no other method calls), not from the first method with a result, and ONLY_TASKS
restricts the run to the given task ids. Only task_id_784 is affected: its reference file holds a helper method
(FirstEvenOddIndices) before the task's method (ProductEvenOdd), and our loop was given the helper's header."""
import os

P = os.path.dirname(os.path.abspath(__file__)) + os.sep
s = open(P + "mbpp_boost_m.py").read()
old_start = s.index("def gt_parts(tid):")
old_end = s.index("def test_oracle(")
NEW = '''def gt_parts(tid):
    """header and reference postcondition of the reference file's MAIN method (mbpp_rescore2.main_method)"""
    import fix_hdr as HDR
    import mbpp_rescore2 as R2
    f = D + "/src/task_id_%s.dfy" % tid
    if not os.path.exists(f):
        return None
    strong = open(f).read()
    h = R2.main_method(strong)
    if not h or not h["ensures"]:
        return None
    head = HDR.head_text(h)
    parts = {"vc-preamble": "", "vc-helpers": "", "vc-code": "", "vc-postamble": "",
             "vc-description": "", "vc-spec": head + "\\n  " + "\\n  ".join("ensures " + e for e in h["ensures"])}
    return head, parts


'''
s = s[:old_start] + NEW + s[old_end:]
LOOP = "for tid in TIDS:"
assert s.count(LOOP) == 1
s = s.replace(LOOP, 'ONLY_T = [x.strip() for x in os.environ.get("ONLY_TASKS", "").split(",") if x.strip()]\n'
                    'if ONLY_T:\n    TIDS = [t for t in TIDS if t in ONLY_T]\n' + LOOP)
open(P + "mbpp_boost_fix.py", "w").write(s)
print("written mbpp_boost_fix.py")
