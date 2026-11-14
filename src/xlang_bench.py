"""GIVEN-SPEC cross-language benchmark runner (Verus + Lean) for the fair
pipeline-vs-pipeline comparison with the vericoding leaderboard. The spec
(ensures / theorem) is FIXED by the benchmark; the model only implements (and in
Lean proves). A spec-integrity check rejects outputs that alter the given spec.
Resumable JSONL output. Env: LANG_=verus|lean MODEL OUT ROUNDS N."""
import os, sys, glob, re, subprocess, tempfile, json, yaml
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V

LANG = os.environ.get("LANG_", "verus")
MODEL = os.environ.get("MODEL", "claude:claude-opus-5-5")
ROUNDS = int(os.environ.get("ROUNDS", "4"))
N = int(os.environ.get("N", "999"))
OUT = os.environ.get("OUT", "")

VERUS = os.path.expanduser("~/verus_install/verus-x86-linux/verus")
LEAN = os.path.expanduser("~/.elan/bin/lean")
env = dict(os.environ)
env["PATH"] = os.path.expanduser("~/.cargo/bin") + ":" + os.path.expanduser("~/.elan/bin") + ":" + env.get("PATH", "")

if LANG == "verus":
    TASKDIR = os.path.expanduser("~/vericoding/benchmarks/verus/numpy_simple/yaml")
else:
    TASKDIR = os.path.expanduser("~/vericoding/benchmarks/lean/numpy_simple/files")


def nows(s):
    return re.sub(r"\s+", "", s)


def spec_lines(text):
    """nonempty, non-sorry, non-comment-marker lines of the fixed spec section"""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s == "sorry" or s.startswith("-- <") or s.startswith("// <"):
            continue
        out.append(nows(s))
    return out


def integrity(spec_text, candidate):
    cand = nows(candidate)
    missing = [l for l in spec_lines(spec_text) if l not in cand]
    return (len(missing) == 0), missing


def verify_verus(src):
    with tempfile.NamedTemporaryFile("w", suffix=".rs", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        r = subprocess.run([VERUS, p], capture_output=True, text=True, timeout=200, env=env)
        out = r.stdout + r.stderr
        m = re.search(r"(\d+) verified, (\d+) errors", out)
        ok = bool(m) and int(m.group(1)) >= 1 and int(m.group(2)) == 0 and "error" not in out.replace("0 errors", "")
        return ok, out
    except subprocess.TimeoutExpired:
        return None, "timeout"
    finally:
        os.unlink(p)


def verify_lean(src):
    with tempfile.NamedTemporaryFile("w", suffix=".lean", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        r = subprocess.run([LEAN, p], capture_output=True, text=True, timeout=200, env=env)
        out = r.stdout + r.stderr
        ok = r.returncode == 0 and "sorry" not in out and "error" not in out.lower()
        return ok, out
    except subprocess.TimeoutExpired:
        return None, "timeout"
    finally:
        os.unlink(p)


def block(t, lang):
    m = re.search(r"```(?:rust|verus|lean|lean4)?\s*(.*?)```", t, re.S)
    t = (m.group(1) if m else t).strip()
    if lang == "verus":
        lines = [ln for ln in t.splitlines()
                 if not (ln.strip().startswith("use ") or ln.strip() == "verus! {" or ln.strip().startswith("fn main"))]
        t = "\n".join(lines).strip()
        if t.count("{") < t.count("}"):
            t = t[:t.rfind("}")].rstrip()
    return t


def run_verus_task(y):
    d = yaml.safe_load(open(y))
    pre = d.get("vc-preamble", "use vstd::prelude::*;\n\nverus! {")
    post = d.get("vc-postamble", "\n}\nfn main() {}")
    spec = d.get("vc-spec", "")
    helpers = d.get("vc-helpers", "") or ""
    base = ("You write Verus (verified Rust). Below is a function with its FIXED requires/ensures "
            "specification and a placeholder body. Write a correct implementation (plus any helper "
            "lemmas or loop invariants you need) so that Verus verifies it. You MUST keep the given "
            "signature, requires and ensures EXACTLY as written. Return ONLY a ```rust block with "
            "the complete function(s); do NOT repeat `use`, `verus! {`, the closing brace or "
            "`fn main`.\n\nPreamble:\n%s\n\nSpecification (fixed):\n%s\n" % (pre, spec))
    convo = base
    for _ in range(ROUNDS + 1):
        g = block(V.ask(MODEL, convo), "verus")
        src = pre + "\n" + helpers + "\n" + g + "\n" + post
        okI, missing = integrity(spec, g)
        if not okI:
            convo = base + ("\n\nYou modified the given specification (missing lines: %s). Keep it "
                            "EXACTLY. Return ONLY the ```rust block." % missing[:3])
            continue
        ok, out = verify_verus(src)
        if ok:
            return "accepted", src
        if ok is None:
            return "timeout", src
        convo = base + "\n\nYour attempt failed Verus:\n" + out[-900:] + "\n\nFix it. Return ONLY the ```rust block."
    return "fail", src


def run_lean_task(p):
    src0 = open(p).read()
    m = re.search(r"-- <vc-theorems>(.*?)(?:-- </vc-theorems>|$)", src0, re.S)
    thm = m.group(1) if m else ""
    base = ("You write Lean 4 (no imports, core only). The file below has definition(s) stubbed "
            "with `sorry` and FIXED specification theorem(s) whose proofs are `sorry`. Implement "
            "the definition(s) and prove the theorem(s). You MUST NOT change any theorem "
            "statement or definition signature. Return ONLY the complete file in a ```lean "
            "block.\n\n" + src0)
    convo = base
    for _ in range(ROUNDS + 1):
        g = block(V.ask(MODEL, convo), "lean")
        okI, missing = integrity(thm, g)
        if not okI:
            convo = base + ("\n\nYou modified the given theorem statement (missing: %s). Keep it "
                            "EXACTLY. Return ONLY the full ```lean file." % missing[:2])
            continue
        ok, out = verify_lean(g)
        if ok:
            return "accepted", g
        if ok is None:
            return "timeout", g
        convo = base + "\n\nYour attempt failed Lean:\n" + out[-1000:] + "\n\nFix it. Return ONLY the full ```lean file."
    return "fail", g


def main():
    pat = "/*.yaml" if LANG == "verus" else "/*.lean"
    tasks = sorted(glob.glob(TASKDIR + pat))[:N]
    done = set()
    fout = None
    if OUT:
        if os.path.exists(OUT):
            for l in open(OUT):
                try:
                    done.add(json.loads(l)["task"])
                except Exception:
                    pass
        fout = open(OUT, "a")
    print("GIVEN-SPEC %s  model=%s  tasks=%d  rounds=%d  done=%d\n" % (LANG, MODEL, len(tasks), ROUNDS, len(done)), flush=True)
    acc = 0
    for t in tasks:
        name = os.path.basename(t)
        if name in done:
            continue
        try:
            status, src = (run_verus_task(t) if LANG == "verus" else run_lean_task(t))
        except Exception as e:
            status, src = "error:" + str(e)[:60], ""
        acc += int(status == "accepted")
        print("  %-34s %s" % (name[:34], status), flush=True)
        if fout:
            fout.write(json.dumps({"model": MODEL, "lang": LANG, "task": name,
                                   "status": status, "src": src if status == "accepted" else ""}) + "\n")
            fout.flush()
    print("\n=== %s GIVEN-SPEC: %d accepted this run ===" % (LANG, acc))


if __name__ == "__main__":
    main()
