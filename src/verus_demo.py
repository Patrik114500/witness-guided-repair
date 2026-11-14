"""Verus feasibility demo WITH a verifier-feedback repair loop (like our Dafny path)
plus a weak-spec reliability probe. Framing B: the model generates ensures + impl from
the signature, so weak self-specs can appear (accept != reliable)."""
import os, sys, glob, re, subprocess, tempfile, yaml
sys.path.insert(0, os.path.expanduser("~/verina-lab"))
import vericode_compete as V

VERUS = os.path.expanduser("~/verus_install/verus-x86-linux/verus")
TASKDIR = os.environ.get("TASKDIR", os.path.expanduser("~/vericoding/benchmarks/verus/numpy_simple/yaml"))
MODEL = os.environ.get("MODEL", "aoai:gpt-4o")
N = int(os.environ.get("N", "999"))
ROUNDS = int(os.environ.get("ROUNDS", "4"))
OUT = os.environ.get("OUT", "")
env = dict(os.environ); env["PATH"] = os.path.expanduser("~/.cargo/bin") + ":" + env.get("PATH", "")


def verify(src):
    with tempfile.NamedTemporaryFile("w", suffix=".rs", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        r = subprocess.run([VERUS, p], capture_output=True, text=True, timeout=200, env=env)
        out = r.stdout + r.stderr
        m = re.search(r"(\d+) verified, (\d+) errors", out)
        ok = bool(m) and int(m.group(1)) >= 1 and int(m.group(2)) == 0 and "error[" not in out and "error:" not in out.replace("0 errors", "")
        return ok, out
    except subprocess.TimeoutExpired:
        return None, "timeout"
    finally:
        os.unlink(p)


def block(t):
    m = re.search(r"```(?:rust|verus)?\s*(.*?)```", t, re.S)
    t = (m.group(1) if m else t).strip()
    # keep only the fn/spec/proof bodies: drop wrapper lines so we can re-wrap cleanly
    lines = []
    for ln in t.splitlines():
        s = ln.strip()
        if s.startswith("use ") or s == "verus! {" or s.startswith("fn main"):
            continue
        lines.append(ln)
    out = "\n".join(lines).strip()
    # drop a single dangling trailing brace that would close verus! (postamble does that)
    if out.endswith("}\n}") or out.count("{") < out.count("}"):
        out = out[:out.rfind("}")].rstrip()
    return out


def gen_solution(pre, post, sig, name):
    base = ("You write Verus (Rust verification). Complete the function with `ensures` "
            "postconditions and an implementation that Verus verifies. "
            "Return ONLY a ```rust block with the function(s); do NOT repeat `use`, "
            "`verus! {`, closing brace, or `fn main` (the preamble/postamble already have them).\n\n"
            "Preamble:\n%s\n\nSignature to implement:\n%s\n" % (pre, sig))
    convo = base
    for r in range(ROUNDS + 1):
        g = block(V.ask(MODEL, convo))
        src = pre + "\n" + g + "\n" + post
        ok, out = verify(src)
        if ok:
            return True, src
        if ok is None:
            return None, src
        convo = base + "\n\nYour previous attempt failed Verus:\n" + out[-900:] + "\n\nFix it. Return ONLY the ```rust block."
    return False, src


def weak_probe(src, name):
    """Ask for a deliberately-wrong implementation that keeps the generated ensures.
    If it still verifies, the spec is too weak."""
    p = ("Here is a verified Verus function:\n```rust\n%s\n```\n"
         "Keep its signature and `ensures` EXACTLY, but replace the implementation body with a "
         "DIFFERENT, semantically wrong one that still type-checks (e.g. return an input unchanged, "
         "a constant, or zeros). Return ONLY a ```rust block with the full function(s), no `use`/"
         "`verus! {`/closing brace/`fn main`." % src)
    g = block(V.ask(MODEL, p))
    pre = src.split("// </vc-preamble>")[0] if "</vc-preamble>" in src else "use vstd::prelude::*;\n\nverus! {"
    post = "\n}\nfn main() {}"
    # reuse the real preamble/postamble from src ends
    head = src[:src.find("\n", src.find("verus! {")) + 1] if "verus! {" in src else "use vstd::prelude::*;\nverus! {\n"
    ok, _ = verify(head + "\n" + g + post)
    return bool(ok)


def main():
    import json
    tasks = sorted(glob.glob(TASKDIR + "/**/*.yaml", recursive=True))[:N]
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
    print("VERUS demo  model=%s  tasks=%d  repair_rounds=%d  done=%d\n" % (MODEL, len(tasks), ROUNDS, len(done)), flush=True)
    acc = weak = 0
    for y in tasks:
        name = os.path.basename(y)[:40]
        if name in done:
            continue
        d = yaml.safe_load(open(y))
        pre = d.get("vc-preamble", "use vstd::prelude::*;\n\nverus! {")
        post = d.get("vc-postamble", "\n}\nfn main() {}")
        sig = re.search(r"((?:spec\s+)?fn\s+\w+\s*\([^)]*\)\s*(?:->\s*\([^)]*\))?)", d.get("vc-spec", ""))
        sig = sig.group(1) if sig else d.get("vc-spec", "")[:200]
        ok, src = gen_solution(pre, post, sig, name)
        rec = {"model": MODEL, "task": name, "status": "accepted" if ok else ("timeout" if ok is None else "fail")}
        if ok:
            acc += 1
            w = weak_probe(src, name)
            weak += int(w)
            rec["weak"] = bool(w); rec["src"] = src
            print("  %-30s ACCEPT%s" % (name, "  [WEAK]" if w else "  (reliable)"), flush=True)
        else:
            print("  %-30s %s" % (name, rec["status"]), flush=True)
        if fout:
            fout.write(json.dumps(rec) + "\n"); fout.flush()
    print("\n=== VERUS: %d accepted this run; %d WEAK ===" % (acc, weak))


if __name__ == "__main__":
    main()
