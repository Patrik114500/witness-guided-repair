#!/bin/bash
# the three replace arms of the big run on the accepts whose specification changed after it (arms_rerun.py)
# usage: run_arms_rerun.sh MODEL WORKERS CAP
cd "$(dirname "$0")"
export OLLAMA="${OLLAMA:-http://localhost:11434/v1/chat/completions}"
TAG=$(echo "$1" | tr ":/" "__")
MODEL="$1" WORKERS="$2" CAP="$3" python3 -u arms_rerun.py >> /tmp/arms_rerun_$TAG.log 2>&1
