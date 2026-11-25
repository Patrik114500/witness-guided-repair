"""Creates mbpp_repro_m.py and mbpp_boost_m.py: copies of the two MBPP runners with (a) task sharding (SHARD=i/n)
so a model can be run in parallel, and (b) for the baseline, NO_TEMP=1 for reasoning models, which accept only their
default temperature. Nothing else changes; the originals stay as they are."""
import os

P = os.path.dirname(os.path.abspath(__file__)) + os.sep
SH = ('TIDS = sorted(db, key=int)\n'
      'if os.environ.get("SHARD"):\n'
      '    _i, _n = map(int, os.environ["SHARD"].split("/")); TIDS = [t for j, t in enumerate(TIDS) if j % _n == _i]\n'
      'for tid in TIDS:')
LOOP = 'for tid in sorted(db, key=int):'

s = open(P + "mbpp_repro.py").read()
assert s.count(LOOP) == 1, s.count(LOOP)
s = s.replace(LOOP, SH)
OLD = ('        b = json.dumps({"messages": [{"role": "user", "content": prompt}],\n'
       '                        "temperature": TEMP, "max_completion_tokens": 10000})')
assert s.count(OLD) == 1, s.count(OLD)
NEW = ('        _pl = {"messages": [{"role": "user", "content": prompt}], "max_completion_tokens": 10000}\n'
       '        if os.environ.get("NO_TEMP") != "1":\n'
       '            _pl["temperature"] = TEMP      # reasoning models accept only their default temperature\n'
       '        b = json.dumps(_pl)')
s = s.replace(OLD, NEW)
open(P + "mbpp_repro_m.py", "w").write(s)

s = open(P + "mbpp_boost.py").read()
assert s.count(LOOP) == 1, s.count(LOOP)
s = s.replace(LOOP, SH)
open(P + "mbpp_boost_m.py", "w").write(s)
print("written mbpp_repro_m.py and mbpp_boost_m.py")
