#!/bin/bash
# CloverBench with another model: both pipelines of clover_v2.py, unchanged.
# usage: run_clover_v3.sh MODE("clover"|"ours") "REPS"(e.g. "1 2 3") SHARD(0..5) MODEL
cd "$(dirname "$0")"
export OLLAMA="${OLLAMA:-http://localhost:11434/v1/chat/completions}"
export ENABLE_LLM_CACHE=0
TAG=$(echo "$4" | tr ":/" "__")
for REP in $2; do
  MODE="$1" SEED_TAG="r$REP" SHARD="$3/6" MODEL="$4" OUT="/tmp/clover_v3_${TAG}_$1_r${REP}_s$3.jsonl" python3 -u clover_v2.py
done
