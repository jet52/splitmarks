#!/usr/bin/env bash
# check-sensitive.sh — scan pushed commits for likely confidential ND-court data.
# Invoked by .githooks/pre-push; bypass with `git push --no-verify`.

set -euo pipefail

ZERO="0000000000000000000000000000000000000000"
errors=0

# Placeholders used in our own docs; do not flag.
PLACEHOLDER_DOCKETS='20990001|20990002|20990003|20990004|20000000|12345678|99999999'
PLACEHOLDER_DC='00-0000-CV-00000'

# Allow repo-local additions: one literal regex per line in .sensitive-check-allow
ALLOW_FILE=".sensitive-check-allow"
allow_grep() {
  if [ -f "$ALLOW_FILE" ]; then
    grep -vE "$(paste -sd '|' "$ALLOW_FILE")" || true
  else
    cat
  fi
}

scan_range() {
  local range="$1"

  # Added lines only (diff +...)
  local added
  added=$(git log --format='' -p "$range" 2>/dev/null | grep -E '^\+' || true)

  # 1. ND Supreme Court docket 2000-2026 series
  local sc_hits
  sc_hits=$(echo "$added" \
    | grep -oE '\b20(0[0-9]|1[0-9]|2[0-6])[0-9]{4}\b' \
    | grep -vE "\b($PLACEHOLDER_DOCKETS)\b" \
    | allow_grep | sort -u || true)
  if [ -n "$sc_hits" ]; then
    echo "[pre-push] possible real Supreme Court docket(s):"
    echo "$sc_hits" | sed 's/^/  /'
    errors=$((errors+1))
  fi

  # 2. ND district-court docket NN-YYYY-XX-NNNNN
  local dc_hits
  dc_hits=$(echo "$added" \
    | grep -oE '\b[0-9]{2}-20(0[0-9]|1[0-9]|2[0-6])-[A-Z]{2}-[0-9]{5}\b' \
    | grep -vE "^$PLACEHOLDER_DC\$" \
    | allow_grep | sort -u || true)
  if [ -n "$dc_hits" ]; then
    echo "[pre-push] possible real district-court docket(s):"
    echo "$dc_hits" | sed 's/^/  /'
    errors=$((errors+1))
  fi

  # 3. Confidential-case captions
  local cap_hits
  cap_hits=$(echo "$added" \
    | grep -iE 'Adoption[- ]of[- ][A-Z]{2,5}\b|\bIn re [A-Z]{2,5}\b|Interest of [A-Z]\.|Termination[- ]of[- ]Parental' \
    | grep -vE 'Example|Sample|Placeholder' \
    | allow_grep | head -5 || true)
  if [ -n "$cap_hits" ]; then
    echo "[pre-push] possible confidential-case caption(s):"
    echo "$cap_hits" | sed 's/^/  /'
    errors=$((errors+1))
  fi

  # 4. Binary documents being added
  local bins
  bins=$(git diff --diff-filter=A --name-only "$range" 2>/dev/null \
    | grep -iE '\.(pdf|docx|doc|rtf|xlsx|pptx)$' \
    | allow_grep || true)
  if [ -n "$bins" ]; then
    echo "[pre-push] binary document(s) being added:"
    echo "$bins" | sed 's/^/  /'
    errors=$((errors+1))
  fi
}

while read -r local_ref local_sha remote_ref remote_sha; do
  [ "$local_sha" = "$ZERO" ] && continue  # branch deletion
  if [ "$remote_sha" = "$ZERO" ]; then
    # New branch: scan local commits not reachable from any existing remote
    range_args="$local_sha --not --remotes"
    scan_range "$range_args"
  else
    scan_range "$remote_sha..$local_sha"
  fi
done

if [ $errors -gt 0 ]; then
  echo
  echo "[pre-push] $errors sensitive-content check(s) failed."
  echo "[pre-push] Review above, or bypass once with: git push --no-verify"
  exit 1
fi
