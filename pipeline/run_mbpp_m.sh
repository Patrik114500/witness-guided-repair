#!/bin/bash
# MBPP-DFY with another model: the dafny-synthesis reproduction ("repro") or our loop ("boost"), sharded.
# usage: run_mbpp_m.sh KIND("repro"|"boost") SHARD N MODEL
cd "$(dirname "$0")"
export OLLAMA="${OLLAMA:-http://localhost:11434/v1/chat/completions}"
export ENABLE_LLM_CACHE=0
TAG=$(echo "$4" | tr ":/" "__")
export MODEL="$4" SHARD="$2/$3" OUT="/tmp/mbpp3_$1_${TAG}_s$2.jsonl"
case "$4" in aoai:gpt-5*|aoai:gpt-6*|aoai:o[0-9]*) export NO_TEMP=1;; esac
python3 -u mbpp_$1_m.py
