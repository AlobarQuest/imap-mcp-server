#!/bin/bash
# IMAP MCP Server launcher
# Fetches passwords from BWS at startup so the app reads them as env vars.
#
# Required env var (set in Coolify):
#   BWS_ACCESS_TOKEN  - Bitwarden Secrets Manager machine account token

set -euo pipefail

if [ -z "${BWS_ACCESS_TOKEN:-}" ]; then
  echo "ERROR: BWS_ACCESS_TOKEN is not set — cannot fetch secrets" >&2
  exit 1
fi

echo "Fetching secrets from BWS..." >&2
echo "BWS_ACCESS_TOKEN length: ${#BWS_ACCESS_TOKEN}" >&2
echo "bws path: $(which bws 2>/dev/null || echo 'NOT FOUND')" >&2

BWS_OUTPUT=$(bws secret list --output json 2>&1) || {
  echo "ERROR: bws secret list failed with output:" >&2
  echo "$BWS_OUTPUT" >&2
  exit 1
}
BWS_JSON="$BWS_OUTPUT"

# Helper: extract a secret value by key name from the JSON array
get_secret() {
  local key="$1"
  echo "$BWS_JSON" | python3 -c "
import sys, json
secrets = json.load(sys.stdin)
for s in secrets:
    if s.get('key') == '$key':
        print(s.get('value', ''))
        sys.exit(0)
print('')
" 2>/dev/null
}

# ── Export IMAP account passwords from BWS ────────────────────────
export IMAP_ACCOUNT_1_PASSWORD=$(get_secret "IMAP_MCP_ADJUSTRIGHT_PASSWORD")
export IMAP_ACCOUNT_2_PASSWORD=$(get_secret "IMAP_MCP_WATKINSHOMESALES_PASSWORD")

# Log which secrets were loaded (without values)
loaded=0
for var in IMAP_ACCOUNT_1_PASSWORD IMAP_ACCOUNT_2_PASSWORD; do
  if [ -n "${!var:-}" ]; then
    loaded=$((loaded + 1))
  else
    echo "WARN: $var not found in BWS" >&2
  fi
done
echo "Loaded $loaded secrets from BWS" >&2

exec python -m src.server
