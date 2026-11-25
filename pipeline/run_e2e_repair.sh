#!/bin/bash
# e2e_repair.py for one model (figure 2 extended to the end-to-end accepts of figure 3)
# usage: run_e2e_repair.sh MODEL WORKERS CAP [OUT] [SMOKE]
cd "$(dirname "$0")"
export OLLAMA="${OLLAMA:-http://localhost:11434/v1/chat/completions}"
TAG=$(echo "$1" | tr ":/" "__")
OUT="${4:-/tmp/e2e_rep_$TAG.jsonl}"
MODEL="$1" WORKERS="$2" CAP="$3" OUT="$OUT" SMOKE="${5:-0}" python3 -u e2e_repair.py >> "${OUT%.jsonl}.log" 2>&1
