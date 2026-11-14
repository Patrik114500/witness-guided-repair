"""Lean 4 feasibility demo with a verifier-feedback repair loop. The model must
implement the def AND prove the spec theorem (both start as `sorry`). Acceptance =
lean compiles with no error and no remaining `sorry`. First Lean signal."""
import os, sys, glob, re, subprocess, tempfile, yaml
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V

LEAN = os.path.expanduser("~/.elan/bin/lean")
TASKDIR = os.path.expanduser("~/vericoding/benchmarks/lean/numpy_simple")
MODEL = os.environ.get("MODEL", "claude:claude-opus-5-5")
N = int(os.environ.get("N", "5"))
ROUNDS = int(os.environ.get("ROUNDS", "4"))
env = dict(os.environ); env["PATH"] = os.path.expanduser("~/.elan/bin") + ":" + env.get("PATH", "")


def verify(src):
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


def block(t):
    m = re.search(r"```(?:lean|lean4)?\s*(.*?)```", t, re.S)
    return (m.group(1) if m else t).strip()


def solve(task, name):
    base = ("You write Lean 4. The file below has a function definition stubbed with `sorry` "
            "and a specification theorem stubbed with `sorry`. Provide (1) a correct "
            "implementation of the definition and (2) a complete proof of the theorem. Return "
            "ONLY the full file in a ```lean block, no imports beyond what is shown.\n\n" + task)
    convo = base
    for r in range(ROUNDS + 1):
        g = block(V.ask(MODEL, convo))
        ok, out = verify(g)
        if ok:
            return True, g
        if ok is None:
            return None, g
        convo = base + "\n\nYour previous attempt failed Lean:\n" + out[-1000:] + "\n\nFix it. Return ONLY the full ```lean file."
    return False, g


def main():
    tasks = sorted(glob.glob(TASKDIR + "/**/*.lean", recursive=True))
    tasks = [t for t in tasks if "import" not in open(t).read().lower()][:N]
    print("LEAN demo  model=%s  tasks=%d  repair_rounds=%d\n" % (MODEL, len(tasks), ROUNDS), flush=True)
    acc = 0
    for t in tasks:
        name = os.path.basename(t)[:30]
        src = open(t).read()
        ok, _ = solve(src, name)
        tag = "ACCEPT" if ok else ("timeout" if ok is None else "fail-after-repair")
        acc += int(bool(ok))
        print("  %-30s %s" % (name, tag), flush=True)
    print("\n=== LEAN: %d/%d accepted (impl + proof verify) ===" % (acc, len(tasks)))


if __name__ == "__main__":
    main()
