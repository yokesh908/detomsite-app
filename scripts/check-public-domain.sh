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
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="https://www.detomsite.in"
CANDIDATES=(
  "https://detomsite-student.vercel.app"
  "https://detomsite-frontend.vercel.app"
  "https://detomsite-admin.vercel.app"
  "https://detomsite-shopkeeper.vercel.app"
)
DO_BUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --build)  DO_BUILD=true; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

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
entry_domain="${DOMAIN_FP%% *}"
if [[ "$entry_domain" == "entry=none" || "$entry_domain" == "unreachable" || "$entry_domain" == "no response" ]]; then
  echo "? could not fingerprint $DOMAIN"
elif echo "$DOMAIN_FP" | grep -q 'built=unknown'; then
  echo "? $DOMAIN responded but exposed no Last-Modified"
else
  echo "The public domain serves entry=$entry_domain."
  echo "If that hash is not among the candidates above, the domain is attached to a"
  echo "Vercel project in ANOTHER account, and the only ways to update it are:"
  echo "  1. redeploy that project from this repo in the account that owns it, or"
  echo "  2. point detomsite.in at the project that is current — add the domain to"
  echo "     detomsite-student in this account, then set the registrar's A record"
  echo "     to cname.vercel-dns-017.com and keep verifying with this script."
fi
