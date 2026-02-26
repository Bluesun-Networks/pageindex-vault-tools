#!/bin/bash
# Index all markdown files in an Obsidian vault using PageIndex.
#
# Usage:
#   bash index_vault.sh
#
# Configure these variables or set them as environment variables:
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────
VAULT="${VAULT_PATH:-$HOME/src/shared-vault/}"
RESULTS="${INDEX_DIR:-$HOME/src/PageIndex/vault-index}"
PAGEINDEX_DIR="${PAGEINDEX_DIR:-$HOME/src/PageIndex}"
MODEL="${PAGEINDEX_MODEL:-gpt-4o-2024-11-20}"
LOGFILE="${RESULTS}/indexing.log"
ERRLOG="${RESULTS}/indexing-errors.log"
MIN_LINES=3  # Skip files with fewer lines than this

# ── LLM Provider ──────────────────────────────────────────────────
# Set PAGEINDEX_PROVIDER=bedrock to use Amazon Bedrock instead of OpenAI.
# Bedrock uses the standard AWS credential chain (env vars, ~/.aws/credentials, IAM role).
# Optional: BEDROCK_MODEL_ID, AWS_REGION (default: us-west-2)
# These env vars are passed through to PageIndex automatically.
export PAGEINDEX_PROVIDER="${PAGEINDEX_PROVIDER:-openai}"
export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
export BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-}"

# ── Setup ──────────────────────────────────────────────────────────
mkdir -p "$RESULTS"

if [[ -f "$PAGEINDEX_DIR/venv/bin/activate" ]]; then
    source "$PAGEINDEX_DIR/venv/bin/activate"
fi

cd "$PAGEINDEX_DIR"

# ── Find files ─────────────────────────────────────────────────────
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(find "$VAULT" -name "*.md" \
  -not -path "*/.obsidian/*" \
  -not -path "*/.trash/*" \
  -not -path "*/attachments/*" \
  -not -path "*/thumbnails/*" \
  -not -path "*/.git/*" \
  | sort)

TOTAL=${#FILES[@]}
echo "$(date): Starting vault indexing — $TOTAL files" | tee "$LOGFILE"
echo "" > "$ERRLOG"

SUCCESS=0
FAILED=0
SKIPPED=0

# ── Index each file ───────────────────────────────────────────────
for i in "${!FILES[@]}"; do
  FILE="${FILES[$i]}"
  REL_PATH="${FILE#$VAULT}"

  # Create output path mirroring vault structure
  OUT_DIR="$RESULTS/$(dirname "$REL_PATH")"
  OUT_FILE="$OUT_DIR/$(basename "$REL_PATH" .md)_structure.json"

  # Skip if already indexed
  if [[ -f "$OUT_FILE" ]]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Skip tiny files
  LINES=$(wc -l < "$FILE")
  if [[ $LINES -lt $MIN_LINES ]]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  mkdir -p "$OUT_DIR"

  NUM=$((i + 1))
  echo "[$NUM/$TOTAL] Indexing: $REL_PATH" | tee -a "$LOGFILE"

  if python run_pageindex.py \
    --md_path "$FILE" \
    --model "$MODEL" \
    --if-add-node-summary yes \
    2>>"$ERRLOG"; then
    # Move result from PageIndex default output to structured location
    TEMP_RESULT="./results/$(basename "$REL_PATH" .md)_structure.json"
    if [[ -f "$TEMP_RESULT" ]]; then
      mv "$TEMP_RESULT" "$OUT_FILE"
      SUCCESS=$((SUCCESS + 1))
    fi
  else
    echo "  FAILED: $REL_PATH" | tee -a "$LOGFILE" "$ERRLOG"
    FAILED=$((FAILED + 1))
  fi
done

echo "" | tee -a "$LOGFILE"
echo "$(date): Vault indexing complete" | tee -a "$LOGFILE"
echo "  Total: $TOTAL | Success: $SUCCESS | Failed: $FAILED | Skipped: $SKIPPED" | tee -a "$LOGFILE"
