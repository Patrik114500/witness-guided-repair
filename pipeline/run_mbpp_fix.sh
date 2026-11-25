#!/bin/bash
# our loop on the MBPP tasks whose header was taken from the wrong method of the reference file (task_id_784)
# usage: run_mbpp_fix.sh MODEL
cd "$(dirname "$0")"
export OLLAMA="${OLLAMA:-http://localhost:11434/v1/chat/completions}"
export ENABLE_LLM_CACHE=0
TAG=$(echo "$1" | tr ":/" "__")
export MODEL="$1" ONLY_TASKS="784" OUT="/tmp/mbpp3fix_boost_${TAG}.jsonl"
python3 -u mbpp_boost_fix.py
