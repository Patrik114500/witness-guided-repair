"""Which accepts of the fixed-call Verus / Lean runs (gs2_*) verify only through a bypass, by the published
rules? Verus: the model block is recovered exactly from the stored source. Writes /tmp/gs3_only_<cell>.txt
(tasks to re-run with the guarded loop) and /tmp/gs3_base.json (honest accepts per cell)."""
import os, sys, json, glob, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_cheat as FC

VER = os.path.expanduser("~/vericoding/benchmarks/verus/numpy_simple/yaml")
LEA = os.path.expanduser("~/vericoding/benchmarks/lean/numpy_simple/files")
NL = chr(10)
base = {}
for cell in ["verus_gpt5", "lean_gpt5", "verus_gpt5mini", "lean_gpt5mini"]:
    lang = cell.split("_")[0]; d = {}
    for f in glob.glob("/tmp/gs2_%s_s*.jsonl" % cell):
        for l in open(f):
            r = json.loads(l); d[r["task"]] = r
    honest = []; byp = []
    for t, r in sorted(d.items()):
        if r["status"] != "accepted":
            continue
        src = r["src"]
        if lang == "verus":
            y = yaml.safe_load(open(os.path.join(VER, t)))
            pre = y.get("vc-preamble", "use vstd::prelude::*;" + NL + NL + "verus! {")
            post = y.get("vc-postamble", NL + "}" + NL + "fn main() {}")
            helpers = y.get("vc-helpers", "") or ""
            head = pre + NL + helpers + NL
            g = src[len(head):len(src) - len(post) - 1] if src.startswith(head) and src.endswith(post) else src
            c = FC.cheats(g, "verus")
        else:
            c = FC.cheats(FC.model_written(src, open(os.path.join(LEA, t)).read()), "lean")
        (byp if c else honest).append(t)
    open("/tmp/gs3_only_%s.txt" % cell, "w").write(NL.join(byp) + (NL if byp else ""))
    base[cell] = {"done": len(d), "accepted": sum(r["status"] == "accepted" for r in d.values()), "honest": honest, "bypass": byp}
    print("%-16s done %d accepted %d | honest %d | bypass %d %s" % (cell, len(d), base[cell]["accepted"], len(honest), len(byp), byp))
json.dump(base, open("/tmp/gs3_base.json", "w"), indent=1)
