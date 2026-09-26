#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Which deployment is the public domain actually serving, and is it current?
#
# detomsite.in is NOT one of the projects this account can deploy: it is attached
# to a Vercel project in a different account, so `vercel --prod` here can never
# update it. That is easy to believe and hard to prove, so this script proves it
# and keeps proving it: it fingerprints the public domain and every candidate
# alias, then reports a verdict.
#
# A Vite build's entry chunk is content-hashed, so an identical hash means the
# public site is running byte-for-byte the same source as that alias.
#
# Usage:
#   bash scripts/check-public-domain.sh                 # default domain + candidates
#   bash scripts/check-public-domain.sh --domain https://www.example.com
#   bash scripts/check-public-domain.sh --build         # also build locally and compare
#   bash scripts/check-public-domain.sh --dns           # print the DNS records still needed
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="https://www.detomsite.in"
# The project that holds the current build of the student portal.
TARGET_PROJECT="detomsite-student"
CANDIDATES=(
  "https://detomsite-student.vercel.app"
  "https://detomsite-frontend.vercel.app"
  "https://detomsite-admin.vercel.app"
  "https://detomsite-shopkeeper.vercel.app"
)
DO_BUILD=false
DO_DNS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --build)  DO_BUILD=true; shift ;;
    --dns)    DO_DNS=true; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# The DNS records still missing before the public domain can serve this account's
# build. Read straight from the Vercel API so the values are never stale.
print_dns_requirements() {
  local token
  token="$(python3 -c "
import json, os
p = os.path.expanduser('~/.local/share/com.vercel.cli/auth.json')
print(json.load(open(p))['token'] if os.path.exists(p) else '')
" 2>/dev/null)"
  if [[ -z "$token" ]]; then
    echo "No Vercel CLI token on this machine — check the dashboard instead."
    return
  fi
  local body
  body="$(curl -s -m 30 -H "Authorization: Bearer ${token}" \
    "https://api.vercel.com/v9/projects/${TARGET_PROJECT}/domains?limit=20" 2>/dev/null)"
  printf '%s' "$body" | python3 -c "
import json, sys
try:
    items = json.load(sys.stdin).get('domains', [])
except Exception:
    sys.exit('could not read the domain list')
pending = 0
for d in items:
    name = d.get('name', '')
    if name.endswith('.vercel.app'):
        continue
    if d.get('verified'):
        continue
    pending += 1
    print(f'  {name}: NOT verified yet')
    for v in d.get('verification') or []:
        print(f\"      {v.get('type')}  {v.get('domain')}  {v.get('value')}\")
if not pending:
    print('  every custom domain on this project is verified')
" 2>/dev/null
}

# Fingerprint one URL: entry chunk hash, <title>, and the asset build time.
fingerprint() {
  local url="$1" html entry title lastmod
  # A Vercel edge hiccup or a non-zero curl exit must not read as "unreachable"
  # when the page actually came back, so judge by the body, not the exit code.
  html="$(curl -sL -m 60 --retry 2 --retry-delay 2 "$url" 2>/dev/null)"
  if [[ -z "$html" ]]; then echo "unreachable"; return; fi
  entry="$(printf '%s' "$html" | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1)"
  title="$(printf '%s' "$html" | grep -o '<title>[^<]*</title>' | head -1 | sed 's/<[^>]*>//g')"
  lastmod="$(curl -sL -m 40 --retry 2 -o /dev/null -D - "$url" 2>/dev/null \
             | grep -i '^last-modified:' | head -1 | cut -d' ' -f2- | tr -d '\r')"
  echo "entry=${entry:-none} | built=${lastmod:-unknown} | title=${title:-none}"
}

echo "──────── public domain ────────"
printf '%-42s ' "$DOMAIN"
DOMAIN_FP="$(fingerprint "$DOMAIN")"
echo "$DOMAIN_FP"

echo
echo "──────── candidates this account can deploy ────────"
for url in "${CANDIDATES[@]}"; do
  printf '%-42s ' "$url"
  fp="$(fingerprint "$url")"
  echo "$fp"
  if [[ "${fp%% *}" == "${DOMAIN_FP%% *}" ]]; then
    echo "    ✓ same entry chunk as the public domain"
  fi
done

if [[ "$DO_BUILD" == true ]]; then
  echo
  echo "──────── local build of frontend/student ────────"
  if (cd "$REPO_ROOT/frontend/student" && npm run build >/tmp/check-dom-build.log 2>&1); then
    local_built="$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' "$REPO_ROOT/frontend/student/dist/index.html" | head -1)"
    printf '%-42s ' "local dist"
    echo "entry=${local_built:-none}"
    if [[ "${local_built%% *}" == "${DOMAIN_FP%% *}" ]]; then
      echo "    ✓ the public domain IS current with this source"
    else
      echo "    ✗ the public domain is STALE — it does not match this build"
    fi
  else
    echo "    build failed — see /tmp/check-dom-build.log"
  fi
fi

echo
echo "──────── verdict ────────"
# DOMAIN_FP starts with "entry=<hash>", so strip the label before comparing.
entry_domain="${DOMAIN_FP%% *}"
entry_hash="${entry_domain#entry=}"
if [[ "$entry_hash" == "none" || "$entry_hash" == "unreachable" || "$entry_hash" == "no response" ]]; then
  echo "? could not fingerprint $DOMAIN"
elif echo "$DOMAIN_FP" | grep -q 'built=unknown'; then
  echo "? $DOMAIN responded but exposed no Last-Modified"
else
  echo "The public domain serves $entry_hash."
  echo "If that hash is not among the candidates above, the domain is attached to a"
  echo "Vercel project in ANOTHER account, and the only ways to update it are:"
  echo "  1. redeploy that project from this repo in the account that owns it, or"
  echo "  2. point detomsite.in at the project that is current — it is already added"
  echo "     to ${TARGET_PROJECT} below, so this is just the DNS change."
fi

if [[ "$DO_DNS" == true ]]; then
  echo
  echo "──────── DNS still needed on ${TARGET_PROJECT} ────────"
  print_dns_requirements
  cat <<'TIP'
  Add those TXT records at your registrar, then also point www at Vercel:
      www.detomsite.in   CNAME   cname.vercel-dns-017.com
      detomsite.in       A       76.76.21.21
  Vercel verifies within a minute or two. Re-run this script afterwards; the
  hashes should match. (The apex currently 308-redirects to www — that redirect
  has to be re-created on the target project in the dashboard: Project →
  Settings → Domains → detomsite.in → Redirect.)
TIP
fi
