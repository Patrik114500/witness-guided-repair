"""Robust parser for the header of the benchmark method in a task's vc-spec.

The first pipeline read the header with single-line regular expressions. That breaks on
  * a requires / ensures whose expression starts on the next line or spans several lines,
  * tuple types in the signature, e.g. returns (result: (int, int)),
  * a vc-spec that holds more than one method (the first one is the task),
  * the word `requires` inside a lambda in an expression.
parse() handles these: balanced parentheses for the signature, clauses recognised only at the start of a
line, the header ends at the body brace or at the next declaration."""
import re

NL = chr(10)
_DECL = re.compile(r"(method|function|predicate|lemma|ghost|datatype|class|const|type|module|twostate|opaque|static)\b")
_CLAUSE = re.compile(r"(requires|ensures|modifies|decreases|reads)\b(.*)$", re.S)


def _balanced(s, i):
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return -1


def split_top(s):
    out = []; depth = 0; cur = ""
    for ch in s:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    res = []
    for x in out:
        if ":" in x:
            n, t = x.split(":", 1)
            res.append((re.sub(r"^(ghost|nameonly|older|new)\s+", "", n.strip()), t.strip()))
    return res


def split_clauses(lines):
    """[(keyword, expression)] from header lines; a clause starts only at the beginning of a line"""
    clauses = []; cur = None
    for ln in lines:
        st = re.sub(r"//[^" + NL + r"]*", "", ln).strip()      # line comments carry no specification content
        if not st:
            continue
        mk = _CLAUSE.match(st)
        if mk:
            cur = [mk.group(1), mk.group(2).strip()]; clauses.append(cur)
        elif cur is not None:
            cur[1] = (cur[1] + NL + "        " + st) if cur[1] else st
    return [(k, e) for k, e in clauses if e.strip()]


def parse(vc_spec):
    vc_spec = vc_spec or ""
    m = re.search(r"\bmethod\s+(?:\{:[^}]*\}\s*)*(\w+)\s*(<[^>(]*>)?\s*\(", vc_spec)
    if not m:
        return None
    i = m.end() - 1; j = _balanced(vc_spec, i)
    if j < 0:
        return None
    params = split_top(vc_spec[i + 1:j - 1]); end = j; rets = []
    mr = re.match(r"\s*returns\s*\(", vc_spec[j:])
    if mr:
        a = j + mr.end() - 1; b = _balanced(vc_spec, a)
        if b < 0:
            return None
        rets = split_top(vc_spec[a + 1:b - 1]); end = b
    hdr = []
    for n, ln in enumerate(vc_spec[end:].split(NL)):
        st = ln.strip()
        if st.startswith("{") or (n > 0 and _DECL.match(st)):
            break
        code_part = re.sub(r"//[^" + NL + r"]*", "", ln).rstrip()
        if code_part.endswith("{") and code_part.count("{") > code_part.count("}"):
            hdr.append(code_part[:code_part.rfind("{")])       # the body brace sits at the end of the last header line
            break
        hdr.append(ln)
    cl = split_clauses(hdr)
    return {"name": m.group(1), "generic": m.group(2) or "", "params": params, "rets": rets,
            "sig_text": vc_spec[m.start():end].strip(),
            "requires": [e for k, e in cl if k == "requires"], "ensures": [e for k, e in cl if k == "ensures"],
            "modifies": [e for k, e in cl if k == "modifies"], "decreases": [e for k, e in cl if k == "decreases"]}


def head_text(h):
    """signature + requires (+ modifies, decreases): what the code stage has to keep exactly"""
    s = h["sig_text"]
    for e in h["requires"]:
        s += NL + "    requires " + e
    for e in h["modifies"]:
        s += NL + "    modifies " + e
    for e in h["decreases"]:
        s += NL + "    decreases " + e
    return s


def ens_split(text):
    """ensures expressions of a generated specification text ('ensures e' lines, possibly multi-line)"""
    text = text or ""
    lines = []
    for ln in text.split(NL):
        if ln.strip().startswith("{"):
            break
        lines.append(ln)
    cl = split_clauses(lines)
    ens = [re.sub(r";\s*$", "", e).strip() for k, e in cl if k == "ensures"]
    if not cl and text.strip() and "ensures" not in text:
        return [text.strip()]
    return [e for e in ens if e]


if __name__ == "__main__":
    import os, sys, glob, collections
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import vericode_compete as V
    c = collections.Counter(); ex = collections.defaultdict(list)
    for src in ["numpy_simple", "verina", "verified_cogen"]:
        for f in sorted(glob.glob(os.path.join(V.BENCH, src, "yaml", "*.yaml"))):
            parts = V.load(f); vs = parts.get("vc-spec", "") or ""
            h = parse(vs); c[(src, "tasks")] += 1
            if not h:
                c[(src, "noparse")] += 1; ex["noparse"].append(os.path.basename(f)); continue
            old_head = V.sig_head(vs); new_head = head_text(h)
            ws = lambda s: re.sub(r"\s+", "", s)
            if ws(old_head) != ws(new_head):
                c[(src, "head-differs")] += 1; ex["head"].append(os.path.basename(f))
            old_req = re.findall(r"requires\s+(.+)", vs)
            if [ws(x) for x in old_req] != [ws(x) for x in h["requires"]]:
                c[(src, "requires-differ")] += 1; ex["req"].append(os.path.basename(f))
            if [ws(x) for x in V.ensures_list(vs)] != [ws(x) for x in h["ensures"]]:
                c[(src, "ensures-differ")] += 1; ex["ens"].append(os.path.basename(f))
            if len(h["rets"]) != 1:
                c[(src, "rets=%d" % len(h["rets"]))] += 1
            if any("(" in t for _, t in h["rets"] + h["params"]):
                c[(src, "tuple-type")] += 1
            if h["modifies"]:
                c[(src, "modifies")] += 1
            if len(re.findall(r"^\s*method\b", vs, re.M)) > 1:
                c[(src, "several-methods")] += 1
            if not h["ensures"]:
                c[(src, "no-ensures")] += 1
    for k in sorted(c):
        print("%-18s %-18s %d" % (k[0], k[1], c[k]))
    for k, L in ex.items():
        print(k, len(L), L[:12])
