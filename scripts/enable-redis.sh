#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Turn ON the shared Redis read cache in production, in one command.
#
# The code is already deployed (app/core/redis_cache.py + read_cache.py) and
# works with or without Redis: /health reports
#   {"cache":{"redis":{"enabled":false,"transport":null}, "postgres":true}}
# until credentials exist. This script attaches them and redeploys the backend.
#
# Where to get credentials (either option, 2 minutes):
#   A) Vercel Dashboard → Storage → Create Database → Upstash Redis → connect it
#      to detomsite-backend. Vercel then injects KV_REST_API_URL +
#      KV_REST_API_TOKEN itself, and you do NOT need this script.
#   B) Upstash console (console.upstash.com) → your Redis database → REST API
#      section → copy UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN, then:
#         bash scripts/enable-redis.sh --url https://xxx.upstash.io --token AAAA...
#
# Usage:
#   bash scripts/enable-redis.sh --url <REST_URL> --token <REST_TOKEN>
#   bash scripts/enable-redis.sh --redis-url rediss://default:pw@host:6379   # needs `pip install redis`
#   bash scripts/enable-redis.sh --status      # only show the live cache state
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORG_ID="team_AeznTxmDmdbQm8nxPjuaibn3"
BACKEND_PROJECT="detomsite-backend"
BACKEND_PROJECT_ID="prj_cZksr4YVlzwUZXzCBT6jYpEvB9eS"
BACKEND_URL="https://detomsite-backend.vercel.app"

REDIS_URL_VALUE=""
REST_URL=""
REST_TOKEN=""
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)       REST_URL="${2:-}"; shift 2 ;;
    --token)     REST_TOKEN="${2:-}"; shift 2 ;;
    --redis-url) REDIS_URL_VALUE="${2:-}"; shift 2 ;;
    --status)    STATUS_ONLY=true; shift ;;
    -h|--help)   sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

show_state() {
  echo "live cache state (${BACKEND_URL}/health):"
  curl -s -m 30 "${BACKEND_URL}/health" | python3 -c \
    'import json,sys; print(json.dumps(json.load(sys.stdin).get("cache"), indent=2))' 2>/dev/null
  echo
}

if [[ "$STATUS_ONLY" == true ]]; then
  show_state
  exit 0
fi

if [[ -z "$REST_URL" && -z "$REDIS_URL_VALUE" ]]; then
  echo "Nothing to do: pass --url + --token (Upstash REST) or --redis-url (plain Redis)." >&2
  show_state
  exit 2
fi
if [[ -n "$REST_URL" && -z "$REST_TOKEN" ]]; then
  echo "A REST URL also needs --token." >&2
  exit 2
fi

set_env() {  # NAME VALUE [--sensitive]
  local name="$1" value="$2" extra="${3:-}"
  # --force overwrites an existing value, --value keeps it non-interactive.
  if (cd "$REPO_ROOT" && vercel env add "$name" production \
        --project "$BACKEND_PROJECT" --value "$value" --force $extra --yes) >/dev/null 2>&1; then
    echo "  ✓ ${name} set"
  else
    echo "  ✗ could not set ${name} (is the Vercel CLI logged in?)" >&2
    return 1
  fi
}

echo "──────── attaching Redis credentials to ${BACKEND_PROJECT} ────────"
if [[ -n "$REST_URL" ]]; then
  # Upstash's own dashboard names; the app reads either pair.
  set_env KV_REST_API_URL "$REST_URL" || exit 1
  set_env KV_REST_API_TOKEN "$REST_TOKEN" --sensitive || exit 1
  set_env UPSTASH_REDIS_REST_URL "$REST_URL" || exit 1
  set_env UPSTASH_REDIS_REST_TOKEN "$REST_TOKEN" --sensitive || exit 1
else
  set_env REDIS_URL "$REDIS_URL_VALUE" --sensitive || exit 1
  echo "  note: REDIS_URL needs the optional 'redis' package, which is NOT in"
  echo "        requirements.txt — use the REST option unless you add it."
fi

echo "──────── redeploying the backend so the cache takes effect ────────"
if (cd "$REPO_ROOT/backend" && VERCEL_ORG_ID="$ORG_ID" VERCEL_PROJECT_ID="$BACKEND_PROJECT_ID" \
      vercel --prod --yes); then
  echo "  ✓ backend redeployed"
else
  echo "  ✗ backend redeploy failed" >&2
  exit 1
fi

echo "──────── verification ────────"
for _ in 1 2 3 4 5 6; do
  state="$(curl -s -m 20 "${BACKEND_URL}/health" || true)"
  if echo "$state" | grep -q '"enabled":true'; then break; fi
  sleep 10
done
show_state

if curl -s -m 20 "${BACKEND_URL}/health" | grep -q '"enabled":true'; then
  echo "✓ Redis cache is live — every instance now serves warm reads."
  echo "  Tune with REDIS_KEY_PREFIX / REDIS_TIMEOUT_SECONDS / REDIS_BREAKER_* if needed."
else
  echo "✗ Redis is still disabled. Check the credentials, then re-run:"
  echo "    bash scripts/enable-redis.sh --status"
fi
