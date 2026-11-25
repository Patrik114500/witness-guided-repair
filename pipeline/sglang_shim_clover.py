"""Minimal shim of the OLD sglang frontend DSL used by Clover, backed by our OpenAI-compatible endpoint."""
import os, json, urllib.request
_BK = {"model": os.environ.get("SHIM_MODEL", "gpt-oss:20b"),
       "url": os.environ.get("SHIM_CHAT_URL", "http://localhost:11434/v1/chat/completions")}

class OpenAI:
    def __init__(self, model, *a, **k): self.model = model
def set_default_backend(b):
    if isinstance(b, OpenAI): _BK["model"] = b.model

CALLS = [0]
def get_calls(): return CALLS[0]
def reset_calls(): CALLS[0] = 0

def _chat(messages, max_tokens=1024, temperature=0.3, **kw):
    CALLS[0] += 1
    body = json.dumps({"model": _BK["model"], "messages": messages,
                       "max_tokens": max_tokens, "temperature": temperature}).encode()
    req = urllib.request.Request(_BK["url"], data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

class _Msg:
    def __init__(self, role, content): self.role = role; self.content = content
class _Gen:
    def __init__(self, name, kw): self.name = name; self.kw = kw
def system(c): return _Msg("system", c)
def user(c): return _Msg("user", c) if isinstance(c, str) else _RoleCtxMaker("user")
def assistant(x): return x if isinstance(x, _Gen) else _Msg("assistant", x)
def gen(name, **kw): return _Gen(name, kw)
def flush_cache(*a, **k): pass

class _VarsHolder:
    def __init__(self, v): self.vars = v
class _State:
    def __init__(self, msgs=None, vars=None):
        self.messages = [dict(m) for m in (msgs or [])]
        self.vars = dict(vars or {}); self._role = None
    def __iadd__(self, x):
        if isinstance(x, _Gen):
            out = _chat(self.messages, **x.kw)
            self.vars[x.name] = out
            self.messages.append({"role": "assistant", "content": out})
        elif isinstance(x, _Msg):
            self.messages.append({"role": x.role, "content": x.content})
        elif isinstance(x, str):
            self.messages.append({"role": self._role or "user", "content": x})
        return self
    def __getitem__(self, k): return self.vars[k]
    @property
    def state(self): return _VarsHolder(self.vars)
    def copy(self): return _CopyCtx(self)
    def user(self): return _RoleCtx(self, "user")
    def assistant(self): return _RoleCtx(self, "assistant")
    def system(self): return _RoleCtx(self, "system")

class _CopyCtx:
    def __init__(self, s): self.src = s
    def __enter__(self):
        self.tmp = _State(self.src.messages, self.src.vars); return self.tmp
    def __exit__(self, *a):
        self.src.vars.update(self.tmp.vars); return False
class _RoleCtx:
    def __init__(self, s, role): self.s = s; self.role = role
    def __enter__(self): self.s._role = self.role; return self.s
    def __exit__(self, *a): self.s._role = None; return False
class _RoleCtxMaker:  # for `with s.user():` style when user() called w/o args (not used here, safety)
    def __init__(self, role): self.role = role

class _Fn:
    def __init__(self, f): self.f = f
    def __call__(self, *args, **kw):
        # old-sglang direct call: fresh state injected as first arg, return the function's return value
        s = _State(); return self.f(s, *args, **kw)
    def run(self, *args, **kw):
        s = _State(); ret = self.f(s, *args, **kw); s.ret_value = ret; return s
    def run_batch(self, batch, **kw):
        return [self.run(**b) for b in batch]
def function(f): return _Fn(f)
