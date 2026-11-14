"""SELF-SPEC Lean runner (our paper's regime, Lean instance). The model sees only
the preamble + def signature (name/type carry the intent) and must write the
implementation, ITS OWN specification theorem(s), and proofs. The benchmark's
ground-truth theorem (vc-theorems) is NEVER shown — it is stored alongside for a
later offline reliability pass. Acceptance = compiles, no sorry/axiom, has at
least one theorem about the def. Env: MODEL OUT ROUNDS N."""
import os, sys, glob, re, subprocess, tempfile, json, yaml
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V

MODEL = os.environ.get("MODEL", "claude:claude-opus-5-5")
ROUNDS = int(os.environ.get("ROUNDS", "4"))
N = int(os.environ.get("N", "999"))
OUT = os.environ.get("OUT", "")
LEAN = os.path.expanduser("~/.elan/bin/lean")
TASKDIR = os.path.expanduser("~/vericoding/benchmarks/lean/numpy_simple/yaml")
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


def defname(sig):
    m = re.search(r"def\s+(\w+)", sig)
    return m.group(1) if m else ""


def solve(pre, sig, name):
    base = ("You write Lean 4 (core only, NO imports). Below is a function signature. "
            "Write (1) a correct implementation of the definition, (2) your OWN specification "
            "theorem(s) that capture what this function is intended to do, and (3) complete "
            "proofs. No sorry, no axiom. Return ONLY the complete file in a ```lean block.\n\n"
            "Preamble (keep as is):\n%s\n\nSignature to implement and specify:\n%s\n" % (pre, sig))
    convo = base
    dn = defname(sig)
    for _ in range(ROUNDS + 1):
        g = block(V.ask(MODEL, convo))
        if "sorry" in g or re.search(r"\baxiom\b", g):
            convo = base + "\n\nYour answer contained sorry or axiom. Provide complete proofs. Return ONLY the full ```lean file."
            continue
        if not ("theorem" in g and re.search(r"\b" + re.escape(dn) + r"\b", g.split("theorem", 1)[1])):
            convo = base + "\n\nYour answer has no specification theorem about `%s`. Add one with a proof. Return ONLY the full ```lean file." % dn
            continue
        ok, out = verify(g)
        if ok:
            return "accepted", g
        if ok is None:
            return "timeout", g
        convo = base + "\n\nYour attempt failed Lean:\n" + out[-1000:] + "\n\nFix it. Return ONLY the full ```lean file."
    return "fail", g


def main():
    tasks = sorted(glob.glob(TASKDIR + "/*.yaml"))[:N]
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
    print("SELF-SPEC lean  model=%s  tasks=%d  rounds=%d  done=%d\n" % (MODEL, len(tasks), ROUNDS, len(done)), flush=True)
    acc = 0
    for y in tasks:
        name = os.path.basename(y)
        if name in done:
            continue
        d = yaml.safe_load(open(y))
        pre = (d.get("vc-preamble") or "").strip()
        sig = (d.get("vc-definitions") or "").replace("sorry", "").strip()
        gt = (d.get("vc-theorems") or "").strip()
        try:
            status, src = solve(pre, sig, name)
        except Exception as e:
            status, src = "error:" + str(e)[:60], ""
        acc += int(status == "accepted")
        print("  %-34s %s" % (name[:34], status), flush=True)
        if fout:
            fout.write(json.dumps({"model": MODEL, "lang": "lean", "mode": "selfspec",
                                   "task": name, "status": status,
                                   "src": src if status == "accepted" else "",
                                   "gt_theorem": gt}) + "\n")
            fout.flush()
    print("\n=== lean SELF-SPEC: %d accepted this run ===" % acc)


if __name__ == "__main__":
    main()
