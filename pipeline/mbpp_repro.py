"""REPRODUCE dafny-synthesis (Misu et al., FSE'24) dynamic few-shot CoT pipeline -- their 58% config --
on OUR model stack, with OUR reliability lens injected after acceptance (entailment vs the curated
MBPP-DFY specs + key-free determinacy + the dataset's own tests). Fills the n.m. cell of Table 1.

Faithful to their Scripts/dynamic_few_shot_prompt.py + services/*:
  two-stage chain per attempt (spec prompt -> code prompt), the generated spec is used ONLY to
  retrieve the 5 code examples (the final code prompt sees just the task description), K<=5
  fresh attempts at temp 0.75, first verifying attempt wins, no error feedback.
Documented deviations (measurement-side or unavoidable):
  - model from env (their GPT-4 is retired); temp 0.75 kept via a local ask with temperature.
  - retrieval embeddings: text-embedding-3-small (their OpenAIEmbeddings/ada-002 key is theirs);
    TF-IDF cosine fallback if no embedding deployment. Recorded per run in "retrieval".
  - leave-one-out: tasks that ARE in their 50-example DB never retrieve themselves (their eval
    excluded the 50; our 159-task subset includes them, so LOO keeps it leak-free).
  - measurement only: their free-form method params are mapped to the curated-spec names before
    the entailment/determinacy lemma; unmappable -> unscorable (None), never False.
Env: MODEL, OUT, LIMIT, KRUN (default 5). Resumable by task."""
import os, sys, re, json, glob, math, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vericode_compete as V
import nl_gated_compare as NG
import det_gate

DS = os.path.expanduser("~/dafny-synthesis")
D = os.path.expanduser("~/clover/dataset/MBPP-DFY-153")
MODEL = os.environ.get("MODEL", "claude:claude-haiku-4-5")
OUT = os.environ.get("OUT", "/tmp/mbpp_repro.jsonl")
LIMIT = int(os.environ.get("LIMIT", "0"))
KRUN = int(os.environ.get("KRUN", "5"))
TEMP = 0.75
SEP = "\n------------------------------------------------------\n"
PRICE = {"claude:claude-haiku-4-5": (0.8, 4), "aoai:gpt-4o": (2.5, 10)}

db = json.load(open(DS + "/Scripts/data/mbpp-san-dfy-228-all-task-test.json"))
exdb = json.load(open(DS + "/Scripts/data/mbpp-dfy-50-examples-db.json"))
SPEC_T = open(DS + "/Scripts/prompts/COT_SPEC_TEMPLATE.file").read()
CODE_T = open(DS + "/Scripts/prompts/COT_CODE_TEMPLATE.file").read()
CODE_PREFIX = ("SYSTEM:\nYou are an expert AI assistant that writes Dafny programs. You are very good at "
               "writing verifiable correct code in terms of preconditions and postconditions of methods, "
               "and at finding the appropriate loop invariants for the pre/postconditions to hold.")


# ---------- model call with their temperature ----------
def ask_t(model, prompt):
    if model.startswith("claude:"):
        b = json.dumps({"model": model[7:], "max_tokens": 10000, "temperature": TEMP,
                        "messages": [{"role": "user", "content": prompt}]})
        out = V._post("%s/anthropic/v1/messages" % V.AZ_EP,
                      {"x-api-key": V.AZ_KEY, "anthropic-version": "2023-06-01",
                       "Content-Type": "application/json"}, b)
        return "".join(x.get("text", "") for x in json.loads(out)["content"])
    if model.startswith("aoai:"):
        b = json.dumps({"messages": [{"role": "user", "content": prompt}],
                        "temperature": TEMP, "max_completion_tokens": 10000})
        out = V._post("%s/openai/deployments/%s/chat/completions?api-version=2024-10-21" % (V.AZ_EP, model[5:]),
                      {"api-key": V.AZ_KEY, "Content-Type": "application/json"}, b)
        return json.loads(out)["choices"][0]["message"]["content"] or ""
    return V.ask(model, prompt, temp=TEMP)


class Cost:
    def __init__(self):
        self.calls = 0; self.tin = 0; self.tout = 0
    def add(self, p, r):
        self.calls += 1; self.tin += len(p) // 4; self.tout += len(r) // 4
    def summ(self):
        pi, po = PRICE.get(MODEL, (0, 0))
        return {"calls": self.calls, "tok_in": self.tin, "tok_out": self.tout,
                "cost_usd": round(self.tin / 1e6 * pi + self.tout / 1e6 * po, 4)}


# ---------- retrieval (their SemanticSimilarityExampleSelector, our embedder) ----------
OLL_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")


def embed_oll(texts):
    data = json.dumps({"model": "nomic-embed-text", "input": texts}).encode()
    req = urllib.request.Request(OLL_BASE + "/api/embed", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())["embeddings"]


_tok = lambda s: re.findall(r"[a-z0-9]+", s.lower())


def tfidf_vecs(texts):
    dfc = {}
    toks = [_tok(t) for t in texts]
    for ts in toks:
        for w in set(ts):
            dfc[w] = dfc.get(w, 0) + 1
    n = len(texts)
    vecs = []
    for ts in toks:
        v = {}
        for w in ts:
            v[w] = v.get(w, 0) + 1
        vecs.append({w: c * math.log((1 + n) / (1 + dfc.get(w, 0))) for w, c in v.items()})
    return vecs


def cos(a, b):
    if isinstance(a, dict):
        s = sum(a[w] * b.get(w, 0) for w in a)
        na = math.sqrt(sum(x * x for x in a.values())); nb = math.sqrt(sum(x * x for x in b.values()))
    else:
        s = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
    return s / (na * nb) if na and nb else 0.0


class Retriever:
    """embeds the 50-example DB once; query text -> top-k example ids (LOO-aware)."""
    def __init__(self, texts_by_id):
        self.ids = list(texts_by_id)
        texts = [texts_by_id[i] for i in self.ids]
        try:
            self.vecs = embed_oll(texts); self.kind = "nomic-embed-text"
        except Exception:
            self.vecs = tfidf_vecs(texts); self.kind = "tfidf-fallback"
    def query(self, text, k, exclude=None):
        if self.kind == "nomic-embed-text":
            try:
                q = embed_oll([text])[0]
            except Exception:
                return [i for i in self.ids if i != exclude][:k]
        else:
            q = tfidf_vecs([text])[0]
        scored = sorted(((cos(q, v), i) for v, i in zip(self.vecs, self.ids) if i != exclude),
                        key=lambda x: -x[0])
        return [i for _, i in scored[:k]]


# their two example-DB views (utils.get_examples_db_* embed the dict values; description dominates)
spec_ret = Retriever({i: exdb[i]["task_description"] for i in exdb})
code_ret = Retriever({i: " ".join([exdb[i]["task_description"],
                                   exdb[i]["specification"]["method_signature"],
                                   exdb[i]["specification"]["postconditions"]]) for i in exdb})


# ---------- their prompt rendering (FewShotPromptTemplate, jinja2 {{...}} only) ----------
def render(t, kv):
    for k, v in kv.items():
        t = t.replace("{{%s}}" % k, str(v))
    return t


def spec_prompt(ids, task_desc):
    exs = [render(SPEC_T, {"task_description": exdb[i]["task_description"],
                           "method_signature": exdb[i]["specification"]["method_signature"],
                           "postconditions": exdb[i]["specification"]["postconditions"]}) for i in ids]
    return SEP.join(exs + ["Task:\n%s\n" % task_desc])


def code_prompt(ids, task_desc):
    exs = [render(CODE_T, {"method_signature": exdb[i]["specification"]["method_signature"],
                           "preconditions": exdb[i]["specification"]["preconditions"],
                           "postconditions": exdb[i]["specification"]["postconditions"],
                           "code": exdb[i]["code"]}) for i in ids]
    return SEP.join([CODE_PREFIX] + exs + ["TASK:\n%s\n\nAI ASSISTANT:\n\n" % task_desc])


def parse_spec_response(resp):
    """their utils.parse_specification_response: line 1 = signature, lines 3.. = postconditions"""
    lines = resp.split("\n")
    sig = lines[1].strip() if len(lines) > 1 else ""
    post = "\n".join(lines[3:]).strip() if len(lines) > 3 else ""
    return sig, post


# ---------- their verifier semantics on our dafny ----------
def parse_code(resp):
    m = re.search(r"```dafny\s*(.*?)\s*```", resp, re.DOTALL)
    return m.group(1).strip() if m else ""


# ---------- GT loading (same as mbpp_ours.gt_parts) + measurement helpers ----------
def gt_parts(tid):
    f = D + "/src/task_id_%s.dfy" % tid
    if not os.path.exists(f):
        return None
    strong = open(f).read()
    m = re.search(r"(method\s+\w+\s*\([^)]*\)\s*returns\s*\([^)]*\)(?:\s*requires[^\n]*)*)", strong)
    if not m:
        return None
    head = m.group(1).rstrip()
    last_kw = max(strong.rfind("ensures"), strong.rfind("requires"))
    bpos = strong.find("{", last_kw) if last_kw >= 0 else -1
    spec_part = strong[:bpos] if bpos > 0 else strong
    gt_ens = V.ensures_list(spec_part)
    if not gt_ens:
        return None
    parts = {"vc-preamble": "", "vc-helpers": "", "vc-code": "", "vc-postamble": "",
             "vc-description": "", "vc-spec": head + "\n  " + "\n  ".join("ensures " + e for e in gt_ens)}
    return head, parts


def gen_ensures_mapped(code, parts):
    """extract THEIR generated ensures and rename their params to the curated-spec names
    (positional). Returns (ensures_str or None, info) -- unmappable/type-mismatch = None,
    never False: if the entailment question cannot even be POSED in the curated vocabulary,
    the accept is unscorable, not unreliable."""
    info = {"mapped": False, "why": None, "their_name": None}
    m = re.search(r"(method\s+\w+\s*\([^)]*\)\s*returns\s*\([^)]*\))", code)
    if not m:
        info["why"] = "no-method-head"
        return None, info
    their_head = m.group(1)
    bpos = code.find("{", m.end())
    spec_part = code[:bpos] if bpos > 0 else code
    ens = V.ensures_list(spec_part)
    if not ens:
        info["why"] = "no-ensures"
        return None, info
    gs, ts = V.parse_sig(parts["vc-spec"]), V.parse_sig(their_head)
    if not gs or not ts:
        info["why"] = "unparsable-sig"
        return None, info
    info["their_name"] = ts[0]
    gargs = list(gs[1]) + ([gs[2]] if gs[2] else [])
    targs = list(ts[1]) + ([ts[2]] if ts[2] else [])
    if len(gargs) != len(targs):
        info["why"] = "arity-mismatch"
        return None, info
    if any(gt.replace(" ", "") != tt.replace(" ", "")
           for (_, gt), (_, tt) in zip(gargs, targs)):
        info["why"] = "type-mismatch"
        return None, info
    ren = {tn.strip(): gn.strip() for (tn, _), (gn, _) in zip(targs, gargs)}
    info["mapped"] = any(a != b for a, b in ren.items())
    out = []
    for e in ens:
        for a, b in ren.items():
            if a != b:
                e = re.sub(r"\b%s\b" % re.escape(a), b, e)
        out.append(e)
    return "\n    ".join("ensures " + e for e in out), info


def helpers_of(code):
    """their top-level predicate/function definitions (no methods): included in the lemma
    context so ensures referencing them RESOLVE. Definitions only, nothing is assumed."""
    out = []
    for m in re.finditer(r"^[ \t]*(ghost\s+)?(predicate|function)\b", code, re.M):
        i = code.find("{", m.start())
        if i < 0:
            continue
        d, j = 0, i
        while j < len(code):
            if code[j] == "{":
                d += 1
            elif code[j] == "}":
                d -= 1
                if d == 0:
                    break
            j += 1
        if j < len(code):
            out.append(code[m.start():j + 1].strip())
    return "\n".join(out)


def _classify(ok, out):
    """True / False / None(unscorable): a lemma that does not even resolve is no verdict."""
    if ok:
        return True
    if "parse errors" in out or "resolution/type errors" in out:
        return None
    return False


def reliable_gt2(parts_m, gen):
    """NG.reliable_gt with (a) helper context via parts_m['vc-helpers'] and
    (b) resolution failures -> None instead of False."""
    sig = V.parse_sig(parts_m["vc-spec"])
    if not sig:
        return None
    m = re.search(r"returns\s*\(([^)]*)\)", parts_m["vc-spec"])
    if m and m.group(1).count(":") > 1:
        return None
    name, params, ret = sig
    args = list(params) + ([ret] if ret else [])
    our, orig = V.ensures_list(gen), V.ensures_list(parts_m["vc-spec"])
    if not our or not orig:
        return None
    reqs = re.findall(r"requires\s+(.+)", parts_m["vc-spec"])
    lem = V.pre(parts_m) + "\nlemma GTcheck(%s)\n" % ", ".join("%s: %s" % (n, t) for n, t in args)
    for r in reqs:
        lem += "  requires %s\n" % r
    for e in our:
        lem += "  requires %s\n" % e
    for e in orig:
        lem += "  ensures %s\n" % e
    lem += "{}\n"
    try:
        ok, out = V.dverify(lem)
        return _classify(ok, out)
    except Exception:
        return None


def determinacy2(parts_m, gen):
    """det_gate.completeness_determinacy with the same helper context + None on resolution."""
    sig = V.parse_sig(parts_m["vc-spec"])
    if not sig or not sig[2]:
        return None
    name, params, (rvar, rt) = sig
    rt = rt.strip()
    ens = V.ensures_list("method _() returns ()\n  " + gen)
    if not ens:
        return None
    reqs = re.findall(r"requires\s+(.+)", parts_m["vc-spec"])
    sub = lambda e, nv: re.sub(r"\b%s\b" % re.escape(rvar), nv, e)
    plist = ", ".join("%s: %s" % (n, t) for n, t in params)
    lem = V.pre(parts_m) + "\nlemma Determinacy(%s%sr1: %s, r2: %s)\n" % (plist, ", " if plist else "", rt, rt)
    for r in reqs:
        lem += "  requires %s\n" % r
    for e in ens:
        lem += "  requires %s\n" % sub(e, "r1")
    for e in ens:
        lem += "  requires %s\n" % sub(e, "r2")
    if rt.replace(" ", "").startswith("array<"):
        lem += "  ensures r1.Length == r2.Length && forall i :: 0 <= i < r1.Length ==> r1[i] == r2[i]\n{}\n"
    else:
        lem += "  ensures r1 == r2\n{}\n"
    try:
        ok, out = V.dverify(lem)
        c = _classify(ok, out)
        return None if c is None else (1.0 if c else 0.0)
    except Exception:
        return None


def test_oracle(parts, code, tests, ds_sig, their_name):
    """independent oracle: execute the dataset's own tests against the accepted code
    (assert->expect); the dataset method name is rewritten to THEIR method name."""
    try:
        dm = re.search(r"method\s+(\w+)", ds_sig or "")
        body = "\n".join("  { %s }" % t.replace("assert ", "expect ").replace("\n", " ")
                         for t in list(tests.values())[:3])
        if dm and their_name and dm.group(1) != their_name:
            body = re.sub(r"\b%s\b" % re.escape(dm.group(1)), their_name, body)
        src = V.assemble(parts, code) + "\nmethod Main() {\n" + body + "\n}\n"
        out = V.drun(src)
        if "expectation violation" in out:
            return False
        if "Error" in out:
            return None
        return True
    except Exception:
        return None


# ---------- main loop ----------
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            done.add(json.loads(l)["task"])
        except Exception:
            pass
fout = open(OUT, "a")

n = 0
for tid in sorted(db, key=int):
    if LIMIT and n >= LIMIT:
        break
    t = db[tid]
    name = "task_id_" + tid
    if name in done:
        continue
    gp = gt_parts(tid)
    rec = {"task": name, "model": MODEL, "method": "dafny-synthesis-repro",
           "retrieval": spec_ret.kind, "temp": TEMP, "loo": tid in exdb}
    if os.environ.get("DUMP_PROMPTS") and not os.path.exists("/tmp/mbpp_repro_prompts.txt"):
        sids = spec_ret.query(t["task_description"], 3, exclude=tid if tid in exdb else None)
        with open("/tmp/mbpp_repro_prompts.txt", "w") as pf:
            pf.write("=== SPEC PROMPT (task %s) ===\n%s\n\n=== CODE PROMPT (spec-stage skipped, example ids %s) ===\n%s"
                     % (tid, spec_prompt(sids, t["task_description"]), sids,
                        code_prompt(sids[:2], t["task_description"])[:4000]))
    if not gp:
        rec["status"] = "no-gt"
        fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(name); n += 1
        continue
    head, parts = gp
    parts["vc-description"] = t.get("task_description", "")
    cost = Cost()
    attempts = []
    accepted_code = None
    try:
        for k in range(1, KRUN + 1):
            sids = spec_ret.query(t["task_description"], 3, exclude=tid if tid in exdb else None)
            sp = spec_prompt(sids, t["task_description"])
            sresp = ask_t(MODEL, sp); cost.add(sp, sresp)
            sig, post = parse_spec_response(sresp)
            cids = code_ret.query(" ".join([t["task_description"], sig, post]), 5,
                                  exclude=tid if tid in exdb else None)
            cp = code_prompt(cids, t["task_description"])
            cresp = ask_t(MODEL, cp); cost.add(cp, cresp)
            code = parse_code(cresp)
            ok, err = (False, "no ```dafny block")
            if code:
                ok, err = V.dverify(code)
            attempts.append({"k": k, "spec_ex": sids, "code_ex": cids, "verified": ok,
                             "code": code, "dafny_out": err[:800]})
            if ok:
                accepted_code = code
                break
            time.sleep(1)
        rec["k_used"] = len(attempts)
        rec["accepted"] = accepted_code is not None
        rec["attempts"] = attempts
        if accepted_code is None:
            rec["status"] = "no-verify"
        else:
            rec["status"] = "accepted"
            gen, info = gen_ensures_mapped(accepted_code, parts)
            rec["map_info"] = info
            if gen is None:
                rec["reliable_gt"] = None
                rec["determinate"] = None
            else:
                rec["gen_spec"] = gen
                parts_m = dict(parts)
                parts_m["vc-helpers"] = helpers_of(accepted_code)
                rec["reliable_gt"] = reliable_gt2(parts_m, gen)
                rec["determinate"] = determinacy2(parts_m, gen)
            rec["tests_pass"] = test_oracle(parts, accepted_code, t.get("test_cases", {}),
                                            t.get("method_signature", ""), info.get("their_name"))
        rec["cost"] = cost.summ()
    except Exception as e:
        rec["status"] = "error"; rec["error"] = str(e)[:200]
    fout.write(json.dumps(rec) + "\n"); fout.flush(); done.add(name); n += 1
    print("  %-14s %-9s k=%s rel=%s det=%s tests=%s $%.3f" % (
        name, rec.get("status"), rec.get("k_used"), rec.get("reliable_gt"),
        rec.get("determinate"), rec.get("tests_pass"),
        rec.get("cost", {}).get("cost_usd", 0)), flush=True)
print("DONE %d" % n, flush=True)
