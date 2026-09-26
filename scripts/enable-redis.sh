#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Turn ON the shared Redis read cache in production, in one command.
#
# The code is already deployed (app/core/redis_cache.py + read_cache.py) and
# works with or without Redis: /health reports
#   {"cache":{"redis":{"enabled":false,"transport":null}, "postgres":true}}
# until credentials exist. This script attaches them to the LIVE backend and
# waits for /health to report "enabled": true.
#
# The live API is the RENDER service `detomsite-backend`
# (https://detomsite-backend-p9ln.onrender.com) — that is what every portal's
# VITE_API_URL points at. (The Vercel "detomsite-backend" project is a separate,
# unused deployment; the old version of this script targeted that one by
# mistake, so it set the variables on the wrong service and verified the wrong
# URL. If you ever do want the Vercel copy, pass --vercel.)
#
# Where to get credentials (either option, ~2 minutes):
#   A) Render → your service → "Key Value" → Create → copy its REDIS_URL
#      (rediss://default:…@…-6379), then:
#         bash scripts/enable-redis.sh --redis-url rediss://default:pw@host:6379
#      Nothing to install — `redis` is in backend/requirements.txt.
#   B) Upstash (console.upstash.com) → your DB → REST API section → copy
#      UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN, then:
#         bash scripts/enable-redis.sh --url https://xxx.upstash.io --token AAA
#      (uses the httpx transport, no client package needed)
#
# Needs a Render API key (Dashboard → Account Settings → API Keys):
#   export RENDER_API_KEY=rnd_...
#
# Usage:
#   bash scripts/enable-redis.sh --redis-url rediss://default:pw@host:6379
#   bash scripts/enable-redis.sh --url https://xxx.upstash.io --token AAAA...
#   bash scripts/enable-redis.sh --status        # only show the live cache state
#   bash scripts/enable-redis.sh --unset         # remove the credentials again
#   bash scripts/enable-redis.sh --redis-url … --vercel   # Vercel copy instead
#
# Optional overrides: --backend-url, --service-id, --no-deploy
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ─── what we are configuring ───
BACKEND_URL="${DETOMSITE_BACKEND_URL:-https://detomsite-backend-p9ln.onrender.com}"
SERVICE_ID="${RENDER_SERVICE_ID:-}"
SERVICE_NAME="${RENDER_SERVICE_NAME:-detomsite-backend}"
RENDER_API="${RENDER_API_BASE:-https://api.render.com/v1}"
TARGET="render"            # render | vercel

# ─── what we are setting ───
REDIS_URL_VALUE=""
REST_URL=""
REST_TOKEN=""
STATUS_ONLY=false
UNSET_ONLY=false
DO_DEPLOY=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)        REST_URL="${2:-}"; shift 2 ;;
    --token)      REST_TOKEN="${2:-}"; shift 2 ;;
    --redis-url)  REDIS_URL_VALUE="${2:-}"; shift 2 ;;
    --status)     STATUS_ONLY=true; shift ;;
    --unset)      UNSET_ONLY=true; shift ;;
    --vercel)     TARGET="vercel"; shift ;;
    --backend-url) BACKEND_URL="${2:-}"; shift 2 ;;
    --service-id) SERVICE_ID="${2:-}"; shift 2 ;;
    --no-deploy)  DO_DEPLOY=false; shift ;;
    -h|--help)    sed -n '2,37p' "$0"; exit 0 ;;
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

if [[ "$UNSET_ONLY" == false && -z "$REST_URL" && -z "$REDIS_URL_VALUE" ]]; then
  echo "Nothing to do: pass --redis-url (Render Key Value / Redis Cloud) or --url + --token (Upstash REST)." >&2
  show_state
  exit 2
fi
if [[ -n "$REST_URL" && -z "$REST_TOKEN" ]]; then
  echo "A REST URL also needs --token." >&2
  exit 2
fi

# ─── Render helpers ───
require_render_key() {
  if [[ -z "${RENDER_API_KEY:-}" ]]; then
    cat >&2 <<'MSG'
A Render API key is required to set env vars / trigger a deploy.
  Dashboard → Account Settings → API Keys → create one, then:
    export RENDER_API_KEY=rnd_...
(Or paste the variables into the Render dashboard by hand:
 Dashboard → detomsite-backend → Environment, then hit "Save & Deploy".)
MSG
    exit 2
  fi
}

# Look the service up by name so you don't have to hunt for its UUID.
resolve_service_id() {
  [[ -n "$SERVICE_ID" ]] && return 0
  local body
  body="$(curl -s -m 30 -H "Authorization: Bearer ${RENDER_API_KEY}" \
    "${RENDER_API}/services?limit=100")"
  SERVICE_ID="$(printf '%s' "$body" | python3 -c "
import json,sys
name = sys.argv[1]
try:
    svc = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for s in svc if isinstance(svc, list) else svc.get('service', []):
    if s.get('name') == name and s.get('type') == 'web':
        print(s['id']); break
" "$SERVICE_NAME" 2>/dev/null)"
  if [[ -z "$SERVICE_ID" ]]; then
    echo "Could not find a web service named '${SERVICE_NAME}'. Pass --service-id <uuid>." >&2
    exit 2
  fi
  echo "  · resolved service '${SERVICE_NAME}' → ${SERVICE_ID}"
}

# render_set KEY VALUE | render_unset KEY
render_set() {
  curl -s -m 30 -o /dev/null -w '%{http_code}' -X PUT \
    -H "Authorization: Bearer ${RENDER_API_KEY}" -H 'Content-Type: application/json' \
    -d "{\"value\": \"$2\"}" \
    "${RENDER_API}/services/${SERVICE_ID}/env-vars/$1"
}
render_unset() {
  curl -s -m 30 -o /dev/null -w '%{http_code}' -X DELETE \
    -H "Authorization: Bearer ${RENDER_API_KEY}" \
    "${RENDER_API}/services/${SERVICE_ID}/env-vars/$1"
}

vercel_set() {  # NAME VALUE [--sensitive]
  local name="$1" value="$2" extra="${3:-}"
  (cd "$REPO_ROOT" && vercel env add "$name" production \
     --project detomsite-backend --value "$value" --force $extra --yes) >/dev/null 2>&1
}

CACHE_KEYS=(REDIS_URL KV_REST_API_URL KV_REST_API_TOKEN UPSTASH_REDIS_REST_URL UPSTASH_REDIS_REST_TOKEN)

if [[ "$TARGET" == "vercel" ]]; then
  echo "──────── attaching Redis credentials to the Vercel detomsite-backend copy ────────"
  if [[ "$UNSET_ONLY" == true ]]; then
    for k in "${CACHE_KEYS[@]}"; do
      (cd "$REPO_ROOT" && vercel env rm "$k" production --project detomsite-backend --yes) >/dev/null 2>&1 \
        && echo "  ✓ ${k} removed" || echo "  · ${k} not set"
    done
  elif [[ -n "$REDIS_URL_VALUE" ]]; then
    vercel_set REDIS_URL "$REDIS_URL_VALUE" --sensitive && echo "  ✓ REDIS_URL set" || exit 1
  else
    vercel_set KV_REST_API_URL "$REST_URL" && echo "  ✓ KV_REST_API_URL set" || exit 1
    vercel_set KV_REST_API_TOKEN "$REST_TOKEN" --sensitive && echo "  ✓ KV_REST_API_TOKEN set" || exit 1
    vercel_set UPSTASH_REDIS_REST_URL "$REST_URL" && echo "  ✓ UPSTASH_REDIS_REST_URL set" || exit 1
    vercel_set UPSTASH_REDIS_REST_TOKEN "$REST_TOKEN" --sensitive && echo "  ✓ UPSTASH_REDIS_REST_TOKEN set" || exit 1
  fi
  if [[ "$DO_DEPLOY" == true ]]; then
    (cd "$REPO_ROOT/backend" && vercel --prod --yes >/dev/null 2>&1) \
      && echo "  ✓ backend redeployed" || echo "  ! redeploy failed — redeploy by hand" >&2
  fi
else
  require_render_key
  resolve_service_id
  echo "──────── attaching Redis credentials to ${SERVICE_NAME} (Render) ────────"
  if [[ "$UNSET_ONLY" == true ]]; then
    for k in "${CACHE_KEYS[@]}"; do
      code="$(render_unset "$k")"
      [[ "$code" == "204" || "$code" == "200" || "$code" == "404" ]] \
        && echo "  ✓ ${k} removed" || { echo "  ✗ ${k} (HTTP ${code})" >&2; exit 1; }
    done
  elif [[ -n "$REDIS_URL_VALUE" ]]; then
    code="$(render_set REDIS_URL "$REDIS_URL_VALUE")"
    [[ "$code" == "200" || "$code" == "201" ]] || { echo "  ✗ REDIS_URL (HTTP ${code})" >&2; exit 1; }
    echo "  ✓ REDIS_URL set"
  else
    for pair in "KV_REST_API_URL|$REST_URL" "KV_REST_API_TOKEN|$REST_TOKEN" \
                "UPSTASH_REDIS_REST_URL|$REST_URL" "UPSTASH_REDIS_REST_TOKEN|$REST_TOKEN"; do
      code="$(render_set "${pair%%|*}" "${pair#*|}")"
      [[ "$code" == "200" || "$code" == "201" ]] || { echo "  ✗ ${pair%%|*} (HTTP ${code})" >&2; exit 1; }
      echo "  ✓ ${pair%%|*} set"
    done
  fi

  if [[ "$DO_DEPLOY" == true && "$UNSET_ONLY" == false ]]; then
    echo "──────── triggering a Render deploy so the cache takes effect ────────"
    code="$(curl -s -m 40 -o /dev/null -w '%{http_code}' -X POST \
      -H "Authorization: Bearer ${RENDER_API_KEY}" -H 'Content-Type: application/json' \
      -d '{"clearCache": "do_not_clear"}' \
      "${RENDER_API}/services/${SERVICE_ID}/deploys")"
    if [[ "$code" == "200" || "$code" == "201" || "$code" == "202" ]]; then
      echo "  ✓ deploy queued (Render rebuilds from git; ~2-4 min on the free tier)"
    else
      echo "  ! could not queue a deploy (HTTP ${code}) — hit \"Save & Deploy\" in the dashboard" >&2
    fi
  fi
fi

echo "──────── verification (${BACKEND_URL}/health) ────────"
for _ in $(seq 1 18); do
  if curl -s -m 20 "${BACKEND_URL}/health" 2>/dev/null | grep -q '"enabled":true'; then break; fi
  sleep 10
done
show_state

if curl -s -m 20 "${BACKEND_URL}/health" 2>/dev/null | grep -q '"enabled":true'; then
  echo "✓ Redis cache is live — every instance now serves warm reads."
  echo "  Tune with REDIS_KEY_PREFIX / REDIS_TIMEOUT_SECONDS / REDIS_BREAKER_* if needed."
else
  echo "✗ Redis is still disabled. Check the credentials, then re-run:"
  echo "    bash scripts/enable-redis.sh --status"
fi
