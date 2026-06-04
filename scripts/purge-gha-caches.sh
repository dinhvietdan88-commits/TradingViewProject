#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
# purge-gha-caches.sh
# Immediate GHA cache cleanup script for dinhvietdan88-commits/TradingViewProject
#
# Usage:
#   bash purge-gha-caches.sh              # Dry run (safe — shows what would be deleted)
#   bash purge-gha-caches.sh --execute    # Actually delete caches
#
# Prerequisites:
#   - GitHub CLI (gh) installed and authenticated: gh auth login
#   - jq installed: sudo apt-get install jq / brew install jq
#
# ════════════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO="${REPO:-dinhvietdan88-commits/TradingViewProject}"
EXECUTE="${1:-}"
DRY_RUN=true
[ "$EXECUTE" = "--execute" ] && DRY_RUN=false

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}ℹ️  $*${NC}"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${NC}"; }
deleted() { echo -e "${RED}🗑️  $*${NC}"; }

echo "═══════════════════════════════════════════════════════════"
echo " GHA Cache Purge — $REPO"
[ "$DRY_RUN" = "true" ] && echo " MODE: 🔍 DRY RUN (pass --execute to actually delete)" \
                        || echo " MODE: 🔴 EXECUTE (deleting caches!)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Verify prerequisites ──────────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
  echo "❌ GitHub CLI (gh) not found. Install: https://cli.github.com"
  exit 1
fi
if ! command -v jq &>/dev/null; then
  echo "❌ jq not found. Install: sudo apt-get install jq"
  exit 1
fi

# ── Fetch all caches ──────────────────────────────────────────────────────
info "Fetching all caches from GitHub API..."
ALL_CACHES=$(gh api "repos/$REPO/actions/caches?per_page=100" --paginate \
  | jq -s '[.[].actions_caches[]]')

TOTAL_COUNT=$(echo "$ALL_CACHES" | jq 'length')
TOTAL_BYTES=$(echo "$ALL_CACHES" | jq '[.[].size_in_bytes] | add // 0')
TOTAL_MB=$((TOTAL_BYTES / 1024 / 1024))

echo ""
info "Found ${TOTAL_COUNT} caches using ${TOTAL_MB} MB total"
echo ""

# ── Show breakdown ────────────────────────────────────────────────────────
echo "=== Top 20 Caches by Size ==="
echo "$ALL_CACHES" | jq -r \
  '.[] | "\(.size_in_bytes/1024/1024|floor) MB  \(.key[0:70])  (\(.last_accessed_at[0:10]))"' \
  | sort -rn | head -20
echo ""

# ── Categories to evict ───────────────────────────────────────────────────
CUTOFF_7D=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
          || date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)  # macOS fallback
CUTOFF_14D=$(date -u -d '14 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
           || date -u -v-14d +%Y-%m-%dT%H:%M:%SZ)

FREED_BYTES=0
DELETED_COUNT=0

delete_cache() {
  local ID="$1" KEY="$2" SIZE="$3" REASON="$4"
  local SIZE_MB=$((SIZE / 1024 / 1024))
  if [ "$DRY_RUN" = "true" ]; then
    deleted "[DRY RUN] Would delete: ${SIZE_MB}MB | ${KEY:0:65} | ${REASON}"
  else
    if gh api -X DELETE "repos/$REPO/actions/caches/$ID" 2>/dev/null; then
      deleted "Deleted: ${SIZE_MB}MB | ${KEY:0:65} | ${REASON}"
      FREED_BYTES=$((FREED_BYTES + SIZE))
      DELETED_COUNT=$((DELETED_COUNT + 1))
    else
      warn "Failed to delete cache $ID (may already be evicted)"
    fi
  fi
}

# 1️⃣  Stale build-sentinel caches (>7 days)
echo "=== [1/4] Build sentinel caches older than 7 days ==="
while IFS=$'\t' read -r ID KEY SIZE ACCESSED; do
  delete_cache "$ID" "$KEY" "$SIZE" "build-sentinel >7d"
done < <(echo "$ALL_CACHES" | jq -r \
  --arg c "$CUTOFF_7D" \
  '.[] | select(.key | test("^build-")) | select(.last_accessed_at < $c) | [.id, .key, (.size_in_bytes|tostring), .last_accessed_at] | @tsv')
echo ""

# 2️⃣  Stale test-sentinel caches (>7 days)
echo "=== [2/4] Test sentinel caches older than 7 days ==="
while IFS=$'\t' read -r ID KEY SIZE ACCESSED; do
  delete_cache "$ID" "$KEY" "$SIZE" "test-sentinel >7d"
done < <(echo "$ALL_CACHES" | jq -r \
  --arg c "$CUTOFF_7D" \
  '.[] | select(.key | test("^test-passed-")) | select(.last_accessed_at < $c) | [.id, .key, (.size_in_bytes|tostring), .last_accessed_at] | @tsv')
echo ""

# 3️⃣  Stale Playwright caches (>14 days)
echo "=== [3/4] Playwright browser caches older than 14 days ==="
while IFS=$'\t' read -r ID KEY SIZE ACCESSED; do
  delete_cache "$ID" "$KEY" "$SIZE" "playwright >14d"
done < <(echo "$ALL_CACHES" | jq -r \
  --arg c "$CUTOFF_14D" \
  '.[] | select(.key | test("playwright")) | select(.last_accessed_at < $c) | [.id, .key, (.size_in_bytes|tostring), .last_accessed_at] | @tsv')
echo ""

# 4️⃣  Old uv caches (no weekly segment = pre-patch, safe to delete)
echo "=== [4/4] Old uv caches (pre-weekly-rotation, no W suffix in key) ==="
CURRENT_WEEK=$(date -u +%Y-W%V)
while IFS=$'\t' read -r ID KEY SIZE ACCESSED; do
  # Delete old-format uv caches that don't have week segment
  if ! echo "$KEY" | grep -qE "uv-[0-9]{4}-W"; then
    delete_cache "$ID" "$KEY" "$SIZE" "old-format uv (no weekly rotation)"
  fi
done < <(echo "$ALL_CACHES" | jq -r \
  '.[] | select(.key | test("uv")) | [.id, .key, (.size_in_bytes|tostring), .last_accessed_at] | @tsv')
echo ""

# ── Summary ───────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════"
if [ "$DRY_RUN" = "true" ]; then
  WOULD_FREE_MB=$(echo "$ALL_CACHES" | jq \
    --arg c7 "$CUTOFF_7D" --arg c14 "$CUTOFF_14D" \
    '[.[] | select(
        ((.key | test("^build-|^test-passed-")) and .last_accessed_at < $c7) or
        ((.key | test("playwright")) and .last_accessed_at < $c14) or
        (.key | test("uv") and (.key | test("uv-[0-9]{4}-W") | not))
    ) | .size_in_bytes] | add // 0')
  WOULD_FREE_MB=$((WOULD_FREE_MB / 1024 / 1024))
  warn "DRY RUN complete. Would free approximately ${WOULD_FREE_MB} MB"
  echo ""
  echo "To execute: bash $(basename $0) --execute"
else
  FREED_MB=$((FREED_BYTES / 1024 / 1024))
  success "Deleted ${DELETED_COUNT} caches, freed ~${FREED_MB} MB"
  echo ""
  # Show remaining
  REMAINING=$(gh api "repos/$REPO/actions/caches?per_page=100" --paginate \
    | jq -s '[.[].actions_caches[].size_in_bytes] | add // 0')
  REMAINING_MB=$((REMAINING / 1024 / 1024))
  info "Remaining cache storage: ~${REMAINING_MB} MB"
fi
echo "═══════════════════════════════════════════════════════════"
