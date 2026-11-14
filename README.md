# Witness-guided specification repair for trustworthy LLM vericoding

Code and data accompanying the ESANN 2027 submission
**"Witness-guided specification repair for trustworthy LLM vericoding"**
(Pánczél, Kárász, Gulyás — Eötvös Loránd University).

In verified code generation a language model writes both the formal specification
and the program, and verifier acceptance is reported as success. We show that a
third of accepted Dafny solutions satisfy a specification that misses the intended
behaviour, that a single solver *determinacy* query flags these weak specifications
far better than an LLM judge, that every flag-driven repair arm is net-harmful, and
that **witness-guided repair** is the only arm with zero regressions. The paper PDF is
in [`paper/`](paper/).

> **Snapshot notice.** The numbers here are a running snapshot (the headline corpus is
> `results/dafny_results_snapshot.jsonl.gz`, 3511 deduplicated runs at the time of
> freezing). Regenerating from this file reproduces the figures and the reported
> numbers exactly; re-running the pipeline against live models will differ by model
> version and sampling.

## What is in here

```
paper/       the submission (LaTeX source, esannV2 class, figures, compiled PDF)
src/         the instrumented vericoding harness (self-contained Dafny pipeline)
figures/     figure-generation scripts + the aggregated cell data (cells.json)
results/     frozen result snapshots the paper's numbers are computed from
  dafny_results_snapshot.jsonl.gz   main corpus (9 models x 3 Dafny families)
  cloverbench_gpt4o.jsonl           our loop on CloverBench (Sec. "Against published pipelines")
  mbpp_ours2.jsonl, mbpp_tests_post.jsonl   our loop on MBPP-DFY
  crosslang/                        Verus + Lean follow-up runs (given-spec and self-spec)
```

## Reproducing the paper's numbers (no GPU, no API keys)

The headline numbers are derived offline from the frozen snapshot.

```bash
pip install -r requirements.txt
cd results && gunzip -k dafny_results_snapshot.jsonl.gz && cd ..

# per-model acceptance/reliability, signal F1s, repair-arm deltas, non-det confound:
python src/paper_numbers.py          # reads /tmp/big_run_*.jsonl by default; see note below

# regenerate the figures from the aggregated cells:
cd figures && python fig23_split.py   # writes fig23a_results.png, fig23b_results.png
```

`paper_numbers.py` globs `/tmp/big_run_*.jsonl`; point it at
`results/dafny_results_snapshot.jsonl` (copy it there, or edit the glob) to run against the
frozen corpus. `figures/fig23_split.py` reads `figures/cells.json` (the aggregated
model x benchmark table) and needs no raw data.

## Re-running the pipeline from scratch

You need the **vericoding benchmark**, a **Dafny** toolchain, and at least one model backend.

1. **Benchmark.** Clone the Dafny families used as the corpus:
   `git clone https://github.com/Beneficial-AI-Foundation/vericoding` and set
   `BENCH=/path/to/vericoding/benchmarks/dafny`. (The Verus and Lean subsets of the
   same benchmark drive the cross-language runs.)
2. **Dafny.** Install Dafny 4.x + Z3 and set `DAFNY=/path/to/dafny`.
3. **Models.** The harness talks to:
   - **Azure OpenAI / AI Foundry** — set `AZ_EP=https://<your-endpoint>` and
     `AZURE_API_KEY=...` (or put the key in `~/.azure_openai_key`). Claude models on
     Foundry use the Anthropic Messages route; GPT models the OpenAI route.
   - **Local open-weight models** via an Ollama-compatible server — set
     `OLLAMA=http://localhost:11434/v1/chat/completions`.
   - **Gemini** (optional) — `GEMINI_API_KEY` or `~/.gemini_key`.
   No endpoints or keys are baked in; everything is read from the environment.
4. **Run.** `MODELS=... SOURCES=numpy_simple,verina,verified_cogen OUT=/tmp/run.jsonl python src/big_run.py`
   produces, per task, the NL→spec→code→verify loop (ITERS rounds), the five
   answer-key-free signals, the three held-out oracles, the repair arms, and the
   witness arm. `src/witness_repair.py` is the witness arm; `src/valuecore.py` the
   non-determinism-aware oracle; `src/paper_numbers.py` aggregates.

### Comparisons against published pipelines

- **CloverBench** (`results/cloverbench_gpt4o.jsonl`): our loop vs Clover's consistency
  gate on the same gpt-4o. Clover itself is at `github.com/ChuyueSun/Clover`; the gate
  wrapper used here lives in that checkout.
- **MBPP-DFY** (`results/mbpp_ours2.jsonl` + `_tests_post`): `src/mbpp_ours.py`, compared
  against the figures reported by Misu et al. (FSE 2024, `github.com/Mondego/dafny-synthesis`).

### Cross-language follow-up (Verus + Lean)

`src/xlang_bench.py` (given-spec: implement a fixed specification), `src/verus_demo.py`
and `src/lean_selfspec.py` (self-spec: the model writes its own specification) run the
same acceptance / weak-specification lens in Verus (needs a `verus` binary + rustup) and
Lean 4 (needs an `elan`/`lean` toolchain). Frozen outputs are in `results/crosslang/`.

## Headline results on the frozen snapshot

(From `results/dafny_results_snapshot.jsonl.gz`. The compiled PDF reports a
marginally earlier freeze of the same running corpus, so its counts differ
slightly; both converge in the camera-ready version.)

| | value |
|---|---|
| deduplicated runs / oracle-evaluated acceptances | 3511 / ~1875 |
| accepted solutions that do **not** entail the intent | ~34% |
| best model acceptance vs reliability (opus-5-5) | 98% accept, 65% reliable |
| determinacy signal F1 (vs LLM judge) | 0.78 vs 0.41 |
| repair arms, net reliability change | invariant −48, judge −104, determinacy −26 |
| **witness-guided repair** | 57 activations, 3 repaired, **0 broken** |
| vs Clover (gpt-4o, CloverBench) | both ~94–95% reliable; our loop accepts 50% more |
| vs Misu GPT-4 (MBPP-DFY) | our budget model verifies 74% vs their 58% |

## Citation

```bibtex
@inproceedings{panczel2027witness,
  title     = {Witness-guided specification repair for trustworthy LLM vericoding},
  author    = {P{\'a}ncz{\'e}l, Patrik and K{\'a}r{\'a}sz, Zolt{\'a}n and Guly{\'a}s, L{\'a}szl{\'o}},
  booktitle = {European Symposium on Artificial Neural Networks (ESANN)},
  year      = {2027}
}
```

Released under the MIT License (see [`LICENSE`](LICENSE)). This is research code; it is
organised for reproducibility of the paper, not as a packaged library.
