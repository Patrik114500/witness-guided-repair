"""Model access, the Dafny calls and the task loader that every other script imports as V.

  ask(model, prompt)   one model call; the prefix of the model id picks the provider: "aoai:" Azure OpenAI,
                       "claude:" and "grok:" the same Azure AI Foundry resource, "gemini:" Google AI Studio, no
                       prefix a local model behind an OpenAI-compatible server (Ollama)
  dverify, drun        `dafny verify` and `dafny run` on a source text (fix_harness.dverify2 is the strict call
                       that the reported accepts are held to)
  load, assemble, ...  the parts of a vericoding task file (description, preamble, specification, code)
Run as a script it is the first harness of the study, with two modes:
  MODE=cfs   the specification is given, the model writes the body and the proof; the given ensures must stay
  MODE=nlsc  the model writes the specification from the description, then the body
together with a reference-free completeness estimate of the specification (outputs of the verified body are
perturbed and the postcondition is evaluated on them by execution). The paper uses big_run.py and the fix_*
modules instead of this mode.
Env: MODE, MODELS (comma separated), SOURCES (comma separated), ITERS, KRUN, OUT, LIMIT (tasks per source).
Endpoints and keys come from the environment, see the README of this folder."""
import os, re, glob, json, subprocess, tempfile, urllib.request, random, time, yaml
random.seed(0)
try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
DAFNY = os.environ.get("DAFNY", os.path.expanduser("~/dafny/dafny/dafny"))  # path to the dafny binary
OLLAMA = os.environ.get("OLLAMA", "http://localhost:11434/v1/chat/completions")  # local open-weight models
BENCH = os.environ.get("BENCH", os.path.expanduser("~/vericoding/benchmarks/dafny"))  # clone of github.com/Beneficial-AI-Foundation/vericoding
ITERS = int(os.environ.get("ITERS", "4"))
KRUN = int(os.environ.get("KRUN", "6"))

# Closed-model access. Set your own endpoints/keys via the environment (see README).
CLOSED_PROXY = os.environ.get("CLOSED_PROXY", "")  # optional HTTP proxy, "" disables
AZ_EP = os.environ.get("AZ_EP", "")  # your Azure OpenAI / AI Foundry endpoint, e.g. https://<name>.services.ai.azure.com
AZ_KEY = os.environ.get("AZURE_API_KEY", "") or (
    open(os.path.expanduser("~/.azure_openai_key")).read().strip()
    if os.path.exists(os.path.expanduser("~/.azure_openai_key")) else "")
G_KEY = os.environ.get("GEMINI_API_KEY", "") or (
    open(os.path.expanduser("~/.gemini_key")).read().strip()
    if os.path.exists(os.path.expanduser("~/.gemini_key")) else "")


def _post(url, headers, body, timeout=300):
    req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": CLOSED_PROXY, "https": CLOSED_PROXY}))
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode()


def ask_aoai(dep, prompt):
    b = json.dumps({"messages": [{"role": "user", "content": prompt}], "max_completion_tokens": 10000})
    out = _post("%s/openai/deployments/%s/chat/completions?api-version=2024-10-21" % (AZ_EP, dep),
                {"api-key": AZ_KEY, "Content-Type": "application/json"}, b)
    return json.loads(out)["choices"][0]["message"]["content"]


def ask_grok(dep, prompt):
    b = json.dumps({"model": dep, "messages": [{"role": "user", "content": prompt}], "max_tokens": 10000})
    out = _post("%s/models/chat/completions?api-version=2024-05-01-preview" % AZ_EP,
                {"api-key": AZ_KEY, "Content-Type": "application/json"}, b)
    return json.loads(out)["choices"][0]["message"]["content"]


def ask_claude(dep, prompt):
    b = json.dumps({"model": dep, "max_tokens": 10000, "messages": [{"role": "user", "content": prompt}]})
    out = _post("%s/anthropic/v1/messages" % AZ_EP,
                {"x-api-key": AZ_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, b)
    return "".join(x.get("text", "") for x in json.loads(out)["content"])


def ask_gemini(mdl, prompt, retries=5):
    b = json.dumps({"contents": [{"parts": [{"text": prompt}]}]})
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (mdl, G_KEY)
    for i in range(retries):
        try:
            j = json.loads(_post(url, {"Content-Type": "application/json"}, b))
            if j.get("candidates"):
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception:
            pass
        time.sleep(6 * (i + 1))
    raise RuntimeError("gemini unavailable")


def ask_ollama(model, prompt, temp=0.3):
    data = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp}).encode()
    req = urllib.request.Request(OLLAMA, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def ask(model, prompt, temp=0.3):
    # provider dispatch by prefix; bare name = local model behind an OpenAI-compatible server
    if model.startswith("aoai:"):
        return ask_aoai(model[5:], prompt)
    if model.startswith("claude:"):
        return ask_claude(model[7:], prompt)
    if model.startswith("grok:"):
        return ask_grok(model[5:], prompt)
    if model.startswith("gemini:"):
        return ask_gemini(model[7:], prompt)
    return ask_ollama(model, prompt, temp)


def code_of(t):
    m = re.search(r"```(?:dafny)?\s*(.*?)```", t, re.S)
    return (m.group(1) if m else t).strip()


def dverify(src):
    with tempfile.NamedTemporaryFile("w", suffix=".dfy", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        r = subprocess.run([DAFNY, "verify", p], capture_output=True, text=True, timeout=90)
        o = r.stdout + r.stderr
        return ("0 errors" in o and "verified" in o), o[-1200:]
    except Exception:
        return False, "TIMEOUT"
    finally:
        os.unlink(p)


def drun(src):
    with tempfile.NamedTemporaryFile("w", suffix=".dfy", dir="/tmp", delete=False) as f:
        f.write(src); p = f.name
    try:
        r = subprocess.run([DAFNY, "run", "--target:py", "--no-verify", p], capture_output=True, text=True, timeout=120)
        return r.stdout + r.stderr
    except Exception:
        return ""
    finally:
        os.unlink(p)


def load(path):
    d = yaml.safe_load(open(path, encoding="utf-8"))
    return {k: (d.get(k) or "") for k in ("vc-description", "vc-preamble", "vc-helpers", "vc-spec", "vc-code", "vc-postamble")}


def pre(parts, helpers=None):
    hs = parts["vc-helpers"] if helpers is None else helpers
    return "\n".join(x for x in (parts["vc-preamble"], hs) if x.strip())


def assemble(parts, method_block, helpers=None):
    return "\n".join(x for x in (pre(parts, helpers), method_block, parts["vc-postamble"]) if x.strip()) + "\n"


def ensures_list(vc_spec):
    idx = vc_spec.find("ensures")
    if idx < 0:
        return []
    tail = vc_spec[idx:]
    return [e.strip() for e in re.findall(r"ensures\s+(.+?)(?=\n\s*(?:ensures|requires|decreases|reads|modifies)\b|$)", tail, re.S) if e.strip()]


def spec_intact(output, ens):
    """every given ensures predicate still present (model did not weaken the spec)."""
    norm = re.sub(r"\s+", "", output)
    return all(re.sub(r"\s+", "", e) in norm for e in ens)


def sig_head(vc_spec):
    m = re.search(r"(method\s+\w+\s*\([^)]*\)\s*returns\s*\([^)]*\)(?:\s*requires[^\n]*\n?)*)", vc_spec)
    return (m.group(1).rstrip() if m else vc_spec.split("ensures")[0].rstrip())


# ---- code-from-spec ----
def run_cfs(model, parts):
    ens = ensures_list(parts["vc-spec"])
    base = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY as given, "
            "do not weaken them. Add the method body, any helper lemmas, and ALL needed loop invariants. "
            "Use a WHILE loop with explicit invariants, NOT a for loop. "
            "Return ONLY a ```dafny code block.\n\n" + pre(parts) + "\n" + parts["vc-spec"] + "\n")
    convo = base
    for it in range(1, ITERS + 1):
        try:
            out = ask(model, convo)
        except Exception:
            return {"success": False, "iters": it, "reason": "gen-error"}
        block = code_of(out)
        if ens and not spec_intact(block, ens):
            convo = base + "\n\nYou changed or dropped an ensures clause. Keep ALL ensures EXACTLY. Return ONLY a ```dafny code block."
            continue
        full = assemble(parts, block)
        ok, err = dverify(full)
        if ok:
            return {"success": True, "iters": it, "method": block}
        convo = base + "\n\nFAILED verification:\n" + err + "\n\nFix it with a while loop and correct invariants, keep the spec intact. Return ONLY a ```dafny code block."
    return {"success": False, "iters": ITERS, "reason": "no-verify"}


# ---- NL -> spec -> code ----
def gen_ensures(model, parts, head):
    nl = parts["vc-description"].strip() or "the method's intended behaviour"
    prompt = ("Given this Dafny method signature and a natural-language description, write the POSTCONDITION "
              "(one or more 'ensures ...' lines) capturing FULL correctness. Return ONLY the ensures lines.\n\n"
              "Preamble (available helpers):\n%s\n\nSignature:\n%s\n\nDescription:\n%s\n" % (parts["vc-preamble"][:1500], head, nl[:1500]))
    try:
        txt = ask(model, prompt)
    except Exception:
        return None
    ens = re.findall(r"ensures[^\n]*", txt)
    return "\n    ".join(ens) if ens else None


def run_nlsc(model, parts):
    head = sig_head(parts["vc-spec"])
    gen = gen_ensures(model, parts, head)
    if not gen:
        return {"success": False, "reason": "no-spec"}
    spec = head + "\n    " + gen
    base = ("Complete this Dafny method so it VERIFIES. Keep the signature, requires and ensures EXACTLY. "
            "Add the body, any helper lemmas, and ALL needed loop invariants. Use a WHILE loop with explicit "
            "invariants, NOT a for loop. Return ONLY a ```dafny code block.\n\n" + pre(parts) + "\n" + spec + "\n")
    convo = base; method = None
    for it in range(1, ITERS + 1):
        try:
            out = ask(model, convo)
        except Exception:
            return {"success": False, "reason": "gen-error", "gen_spec": spec}
        block = code_of(out)
        ok, err = dverify(assemble(parts, block))
        if ok:
            method = block; break
        convo = base + "\n\nFAILED verification:\n" + err + "\n\nFix it with a while loop and correct invariants. Return ONLY a ```dafny code block."
    if method is None:
        return {"success": False, "reason": "no-verify", "gen_spec": spec}
    rec = {"success": True, "gen_spec": spec, "gen_ensures": re.findall(r"ensures[^\n]*", gen)}
    rec["completeness"] = measure_completeness(parts, method, re.findall(r"ensures\s+(.+)", gen))
    return rec


# ---- key-free completeness on the measurable subset (reused idea) ----
def parse_sig(vc_spec):
    m = re.search(r"method\s+(\w+)\s*\(([^)]*)\)\s*returns\s*\(([^)]*)\)", vc_spec)
    if not m:
        return None
    name, ps, rs = m.groups()
    params = [(x.split(":")[0].strip(), x.split(":")[1].strip()) for x in ps.split(",") if ":" in x]
    rr = [(x.split(":")[0].strip(), x.split(":")[1].strip()) for x in rs.split(",") if ":" in x]
    return name, params, (rr[0] if rr else None)


def gen_val(t, n=None):
    t = t.replace(" ", "")
    if n is None:
        n = random.randint(2, 4)
    if t == "int": return random.randint(-8, 8), "int"
    if t == "nat": return random.randint(0, 8), "nat"
    if t == "bool": return random.choice([True, False]), "bool"
    if t == "real": return random.randint(-6, 6), "real"
    if t.startswith("array<int>"): return [random.randint(-6, 6) for _ in range(n)], "array<int>"
    if t.startswith("seq<int>"): return [random.randint(-6, 6) for _ in range(n)], "seq<int>"
    return None, None


def lit_param(pn, v, t):
    if t == "array<int>":
        return "var %s := new int[%d];" % (pn, len(v)) + "".join(" %s[%d] := %d;" % (pn, i, x) for i, x in enumerate(v))
    if t == "seq<int>": return "var %s := [%s];" % (pn, ", ".join(str(x) for x in v))
    if t == "bool": return "var %s := %s;" % (pn, "true" if v else "false")
    if t == "real": return "var %s := %d.0;" % (pn, v)
    return "var %s := %d;" % (pn, v)


def perturb(ov, rt):
    rt = rt.replace(" ", "")
    if rt in ("int", "nat", "real"):
        cands = [ov + 1, ov - 1, ov + 3, ov - 3, -ov, 0, 2 * ov + 1]
        return [c for c in dict.fromkeys(cands) if c != ov]
    if rt == "bool": return [not ov]
    if rt in ("seq<int>", "array<int>"):
        ov = list(ov); n = len(ov); out = []
        for i in range(n):
            for d in (1, -1):
                mo = list(ov); mo[i] += d
                if mo != ov: out.append(mo)
        if n:
            cands = [[0]*n, [ov[0]]*n, list(reversed(ov)), [-x for x in ov],
                     [x + 1 for x in ov], ov[1:] + ov[:1], sorted(ov), [ov[0] + 1] + ov[1:]]
            for c in cands:
                if c != ov and c not in out: out.append(c)
        return out
    return []


def ret_bind(rvar, mo, rt):
    rt = rt.replace(" ", "")
    if rt == "array<int>":
        return "var %s := new int[%d];" % (rvar, len(mo)) + "".join(" %s[%d] := %d;" % (rvar, i, x) for i, x in enumerate(mo))
    if rt == "seq<int>": return "var %s := [%s];" % (rvar, ", ".join(str(x) for x in mo))
    if rt == "bool": return "var %s := %s;" % (rvar, "true" if mo else "false")
    if rt == "real": return "var %s := %d.0;" % (rvar, mo)
    return "var %s := %d;" % (rvar, mo)


def measure_completeness(parts, method, ens_exprs):
    """ground-truth-free: the just-verified method is the reference. Returns c in [0,1] or None."""
    sig = parse_sig(parts["vc-spec"])
    if not sig or not sig[2]:
        return None
    name, params, (rvar, rt) = sig
    rt0 = rt.replace(" ", "")
    if rt0 not in ("int", "nat", "bool", "real", "seq<int>", "array<int>"):
        return None
    ptypes = [pt.replace(" ", "") for _, pt in params]
    if any(gen_val(pt)[1] is None for pt in ptypes):
        return None
    if not ens_exprs or any("old(" in e for e in ens_exprs):
        return None
    full_method = assemble(parts, method)
    # PHASE 1: run reference on random inputs
    blocks = []
    for ki in range(KRUN):
        kn = random.randint(2, 4)  # shared length so equal-length preconditions hold
        vals = [gen_val(pt, kn) for pt in ptypes]
        decls = " ".join(lit_param(pn, v, t) for (pn, _), (v, t) in zip(params, vals))
        args = ", ".join(pn for pn, _ in params)
        blocks.append((ki, decls, args))
    # build phase-1 Main
    pb = []
    for ki, decls, args in blocks:
        if rt0 == "array<int>":
            body = 'var r := %s(%s); print "I%d:["; var i:=0; while i<r.Length{print r[i]; if i<r.Length-1{print ",";} i:=i+1;} print "]\\n";' % (name, args, ki)
        elif rt0 == "seq<int>":
            body = 'var r := %s(%s); print "I%d:["; var i:=0; while i<|r|{print r[i]; if i<|r|-1{print ",";} i:=i+1;} print "]\\n";' % (name, args, ki)
        else:
            body = 'var r := %s(%s); print "I%d:", r, "\\n";' % (name, args, ki)
        pb.append("  { %s %s }" % (decls, body))
    out = drun(full_method + "\nmethod Main() {\n" + "\n".join(pb) + "\n}\n")
    io = []
    for ki, decls, args in blocks:
        if rt0 in ("array<int>", "seq<int>"):
            m = re.search(r"I%d:\[([^\]]*)\]" % ki, out)
            if m:
                ov = [int(x) for x in m.group(1).split(",") if x.strip().lstrip("-").isdigit()] if m.group(1).strip() else []
                io.append((decls, ov))
        else:
            m = re.search(r"I%d:(-?\d+(?:\.\d+)?|true|false)" % ki, out)
            if m:
                g = m.group(1); ov = (g == "true") if rt0 == "bool" else int(float(g))
                io.append((decls, ov))
    if not io:
        return None
    pred = "(" + " && ".join("(%s)" % e for e in ens_exprs) + ")"
    cb = []; cid = 0
    for decls, ov in io:
        for mo in perturb(ov, rt0):
            cb.append("  { %s %s var ok := %s; print \"C%d=\", ok, \"\\n\"; }" % (decls, ret_bind(rvar, mo, rt0), pred, cid)); cid += 1
    if not cb:
        return None
    out2 = drun(pre(parts) + "\nmethod Main() {\n" + "\n".join(cb) + "\n}\n")
    k = t = 0
    for m in re.finditer(r"C\d+=(true|false)", out2):
        t += 1; k += (m.group(1) == "false")
    return (k / t) if t else None


def main():
    MODE = os.environ.get("MODE", "cfs")
    MODELS = [m.strip() for m in os.environ.get("MODELS", "qwen2.5-coder:32b").split(",") if m.strip()]
    SOURCES = [s.strip() for s in os.environ.get("SOURCES", "numpy_simple").split(",") if s.strip()]
    LIMIT = int(os.environ.get("LIMIT", "0"))
    OUT = os.environ.get("OUT", "/tmp/vericode.json")
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for source in SOURCES:
        files = sorted(glob.glob(BENCH + "/%s/yaml/*.yaml" % source))
        if LIMIT: files = files[:LIMIT]
        for model in MODELS:
            done = sum(1 for f in files if "%s|%s|%s" % (model, source, os.path.basename(f)) in res)
            print("## %s | %s | %s  (%d tasks, %d done)" % (MODE, model, source, len(files), done), flush=True)
            for f in files:
                task = os.path.basename(f)
                key = "%s|%s|%s" % (model, source, task)
                if key in res:
                    continue
                try:
                    parts = load(f)
                    rec = run_cfs(model, parts) if MODE == "cfs" else run_nlsc(model, parts)
                    if MODE == "cfs" and rec.get("success"):
                        rec["completeness"] = measure_completeness(parts, rec.get("method", ""), ensures_list(parts["vc-spec"]))
                except Exception as e:
                    rec = {"success": False, "reason": "exc:" + str(e)[:80]}
                rec.pop("method", None)
                res[key] = {"model": model, "source": source, "task": task, "mode": MODE, **rec}
                json.dump(res, open(OUT, "w"), indent=1)
            ok = sum(1 for f in files if res.get("%s|%s|%s" % (model, source, os.path.basename(f)), {}).get("success"))
            cs = [res["%s|%s|%s" % (model, source, os.path.basename(f))].get("completeness") for f in files
                  if res.get("%s|%s|%s" % (model, source, os.path.basename(f)), {}).get("success")]
            cs = [c for c in cs if c is not None]
            rel = sum(1 for c in cs if c >= 0.8)
            print("   -> %s %s: success %d/%d = %.1f%%  | measured %d, reliable(c>=.8) %d" % (
                model, source, ok, len(files), 100 * ok / len(files), len(cs), rel), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
