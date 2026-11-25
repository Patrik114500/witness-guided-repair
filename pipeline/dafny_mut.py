"""Program mutation for Dafny, in the style of MutDafny: how many mutants of a verified body does a specification reject?

For a single-method Dafny program the operators of the body are mutated (comparisons, arithmetic) and each mutant
is verified against the specification. A mutant that no longer verifies is killed, and the kill rate is a
reference-free signal of how much the specification constrains the body. big_run.py records this signal for every
accept (mutation_kill); it is not used for any number of the paper.
Run as a script it measures the kill rate on single-method DafnyBench programs while ensures clauses are dropped.
Env: N (number of tasks), OUT, DAFNY (binary), TIMEOUT."""
import os, re, sys, json, itertools, subprocess, tempfile, glob, random

DAFNY = os.environ.get("DAFNY", os.path.expanduser("~/dafny/dafny/dafny"))
GT = os.path.expanduser("~/DafnyBench/DafnyBench/dataset/ground_truth")
TIMEOUT = int(os.environ.get("TIMEOUT", "60"))
random.seed(0)

OPS = [(" < ", " <= "), (" <= ", " < "), (" > ", " >= "), (" >= ", " > "),
       (" == ", " != "), (" + ", " - "), (" - ", " + "), (" < ", " > ")]


def verify(src):
    with tempfile.NamedTemporaryFile("w", suffix=".dfy", dir="/tmp", delete=False) as f:
        f.write(src); path = f.name
    try:
        r = subprocess.run([DAFNY, "verify", path], capture_output=True, text=True, timeout=TIMEOUT)
        out = r.stdout + r.stderr
        if "0 errors" in out and "verified" in out:
            return True            # verifies
        if "errors" in out or "Error" in out or "assertion" in out:
            return False           # rejected
        return None                # inconclusive (compile error etc.)
    except subprocess.TimeoutExpired:
        return None
    finally:
        os.unlink(path)


def ensures_spans(src):
    """return list of (start,end) char spans of top-level 'ensures ...' clauses."""
    spans = []
    for m in re.finditer(r"\bensures\b", src):
        i = m.start()
        # clause runs until next keyword (ensures/requires/decreases/{/invariant) at line start-ish
        j = m.end()
        depth = 0
        while j < len(src):
            c = src[j]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and src[j:j+8] in ("ensures ", "requires") :
                break
            elif depth == 0 and src.startswith(("\n  ensures", "\n  requires", "\n  decreases", "\n{"), j):
                break
            elif c == "\n":
                # peek next non-space keyword
                k = j + 1
                while k < len(src) and src[k] in " \t":
                    k += 1
                if src.startswith(("ensures", "requires", "decreases", "{", "invariant", "method", "function"), k):
                    break
            j += 1
        spans.append((i, j))
    return spans


def body_span(src):
    """first top-level method body {...} span."""
    mm = re.search(r"\bmethod\b", src)
    if not mm:
        return None
    i = src.find("{", mm.end())
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return (i, j + 1)
    return None


def make_mutants(src, bspan, maxn=8):
    i, j = bspan
    body = src[i:j]
    muts = []
    for a, b in OPS:
        idx = 0
        while True:
            p = body.find(a, idx)
            if p < 0:
                break
            mbody = body[:p] + b + body[p + len(a):]
            muts.append(src[:i] + mbody + src[j:])
            idx = p + 1
    random.shuffle(muts)
    return muts[:maxn]


def pick_tasks(n):
    files = sorted(glob.glob(GT + "/*.dfy"))
    out = []
    for f in files:
        try:
            src = open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if src.count("method ") != 1:
            continue
        if len(ensures_spans(src)) < 1 or len(src) > 1800:
            continue
        if not body_span(src):
            continue
        out.append((f, src))
        if len(out) >= n:
            break
    return out


def run_task(f, src):
    es = ensures_spans(src)
    bs = body_span(src)
    n_ens = len(es)
    base_ok = verify(src)
    if base_ok is not True:
        return None   # ground truth must verify as-is
    muts = make_mutants(src, bs)
    if not muts:
        return None
    out = {"file": os.path.basename(f), "n_ensures": n_ens, "by_strength": {}}
    for r in range(1, n_ens + 1):
        for keep in itertools.combinations(range(n_ens), r):
            drop = [k for k in range(n_ens) if k not in keep]
            # remove dropped ensures spans (from the end to keep indices valid)
            def ablate(s):
                for k in sorted(drop, key=lambda x: -es[x][0]):
                    s = s[:es[k][0]] + s[es[k][1]:]
                return s
            killed = total = 0
            for mt in muts:
                res = verify(ablate(mt))
                if res is None:
                    continue
                total += 1
                if res is False:
                    killed += 1
            s = round(len(keep) / n_ens, 3)
            g = out["by_strength"].setdefault(str(s), {"killed": 0, "total": 0})
            g["killed"] += killed; g["total"] += total
    return out


def main():
    N = int(os.environ.get("N", "25"))
    outp = os.environ.get("OUT", "/tmp/dafny_mut.json")
    tasks = pick_tasks(N)
    rows = []
    for i, (f, src) in enumerate(tasks):
        r = run_task(f, src)
        if r:
            rows.append(r)
            json.dump(rows, open(outp, "w"), indent=2)
            for s, g in sorted(r["by_strength"].items()):
                mk = g["killed"] / g["total"] if g["total"] else float("nan")
                print("  [%d/%d] %s  s=%s  mut_kill=%.3f (%d/%d)"
                      % (i + 1, len(tasks), r["file"][:40], s, mk, g["killed"], g["total"]))
    print("saved", outp, "(%d usable tasks)" % len(rows))


if __name__ == "__main__":
    main()
