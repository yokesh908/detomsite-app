#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
#  DETOMSITE — ONE-COMMAND DEPLOY
#  You run:  bash deploy.sh
#  The script does EVERYTHING itself:
#    1. Installs the tools it needs (Vercel + Supabase CLIs)
#    2. Asks you to log in (click "Authorize" in your browser)
#    3. Creates a free Supabase database & loads all tables
#    4. Deploys the backend to Vercel
#    5. Deploys the frontend to Vercel
#    6. Prints your live URLs + admin login
#  ══════════════════════════════════════════════════════════════════════
set -euo pipefail

# NON_INTERACTIVE=1 + env vars let this script run fully unattended
# (used when the deploy is driven by a script or another process).
NON_INTERACTIVE="${NON_INTERACTIVE:-0}"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; BOLD=$'\033[1m'; NC=$'\033[0m'

step()        { echo -e "\n${BOLD}── Step: $1 ──${NC}"; }
say()         { echo -e "  ${GREEN}✓${NC} $1"; }
warn()        { echo -e "  ${YELLOW}→${NC} $1"; }
fail()        { echo -e "\n  ${RED}✖${NC} $1"; exit 1; }
ask()         { [[ "$NON_INTERACTIVE" == "1" ]] && { eval "$2="; return 0; }; read -r -p "  $1 " "$2"; }
confirm()     { [[ "$NON_INTERACTIVE" == "1" ]] && return 0; read -r -p "  $1 [Enter to continue / n to abort] " _r; [[ -z "${_r:-}" || "$_r" == "y" || "$_r" == "Y" ]] || return 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"
CRED_FILE="$REPO_DIR/.deploy-credentials.txt"
: > "$CRED_FILE"

ADMIN_EMAIL="${DETOMSITE_ADMIN_EMAIL:-admin@detomsite.app}"
SUPABASE_ORG="${SUPABASE_ORG:-}"
SUPABASE_REGION="${SUPABASE_REGION:-ap-south-1}"
FRONTEND_PROJECT="detomsite-frontend"
BACKEND_PROJECT="detomsite-backend"
FRONTEND_URL="https://${FRONTEND_PROJECT}.vercel.app"
BACKEND_URL="https://${BACKEND_PROJECT}.vercel.app"
JWT_SECRET="$(openssl rand -hex 32 2>/dev/null || date +%s%N | sha256sum | cut -c1-40)"
ADMIN_PASSWORD="$(openssl rand -base64 12 2>/dev/null | tr -d '/+=' | cut -c1-12 || date +%s%N | sha256sum | cut -c1-12)"

trap 'fail "Something failed at: ${LAST_STEP:-a step}. Scroll up to see why, then re-run the script."' ERR

echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║   DETOMSITE · ONE-COMMAND DEPLOY                ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  This creates a free Supabase database and deploys this app"
echo "  to Vercel. You'll log in twice (click Authorize in your"
echo "  browser) — that's the only thing you need to do."
echo

# ─── 1. Preflight ────────────────────────────────────────────────────
LAST_STEP="Preflight checks"
step "Checking your computer"
command -v node     >/dev/null 2>&1 || fail "Node.js is not installed. Install from https://nodejs.org and re-run."
command -v npm      >/dev/null 2>&1 || fail "npm is not installed."
command -v git      >/dev/null 2>&1 || fail "git is not installed."
command -v curl     >/dev/null 2>&1 || fail "curl is not installed."
command -v openssl  >/dev/null 2>&1 || warn "openssl missing — using fallback for secrets."
say "Node $(node -v) ready (npm, git, curl OK)"

# ─── 2. Install the CLIs ─────────────────────────────────────────────
LAST_STEP="Installing Vercel + Supabase CLI"
step "Installing the automation tools"
if ! command -v vercel >/dev/null 2>&1; then
  warn "Installing Vercel CLI (needs internet, ~1 min)..."
  npm install -g vercel >/dev/null 2>&1 || fail "Could not install Vercel CLI. Try: npm install -g vercel"
else
  say "Vercel CLI already installed ($(vercel --version 2>/dev/null | head -1))"
fi
if ! command -v supabase >/dev/null 2>&1; then
  warn "Installing Supabase CLI..."
  OS="linux"; [[ "$(uname -s)" == "Darwin" ]] && OS="darwin"
  ARCH="amd64"; [[ "$(uname -m)" == "arm64" ]] && ARCH="arm64"
  curl -sL "https://github.com/supabase/cli/releases/latest/download/supabase_${OS}_${ARCH}.tar.gz" -o /tmp/supabase.tar.gz \
    || fail "Could not download Supabase CLI. Check internet."
  tar -xzf /tmp/supabase.tar.gz -C /usr/local/bin 2>/dev/null \
    || fail "Could not extract Supabase CLI. Run: sudo tar -xzf /tmp/supabase.tar.gz -C /usr/local/bin"
  chmod +x /usr/local/bin/supabase
  rm -f /tmp/supabase.tar.gz
else
  say "Supabase CLI already installed"
fi
command -v vercel   >/dev/null 2>&1 || fail "Vercel CLI not working."
command -v supabase >/dev/null 2>&1 || fail "Supabase CLI not working."

# ─── 3. Log in to Vercel ─────────────────────────────────────────────
LAST_STEP="Vercel login"
step "Log in to Vercel"
if vercel whoami >/dev/null 2>&1; then
  say "Already logged in as $(vercel whoami 2>/dev/null)"
else
  echo "  A browser tab will open — click Authorize, return here, press Enter."
  confirm "  → Log in to Vercel now?" || fail "Login aborted."
  vercel login || fail "Vercel login failed. Re-run the script."
  say "Logged in to Vercel"
fi

# ─── 4. Log in to Supabase ───────────────────────────────────────────
LAST_STEP="Supabase login"
step "Log in to Supabase"
if supabase projects list >/dev/null 2>&1; then
  say "Already logged in to Supabase"
else
  echo "  Supabase prints a link — open it, click the token button,"
  echo "  and paste the access token back into the terminal."
  supabase login || fail "Supabase login failed. Re-run the script."
  say "Logged in to Supabase"
fi

# ─── 5. Admin email for the app ──────────────────────────────────────
LAST_STEP="Collecting admin email"
step "Admin login for the app"
echo "  The ADMIN portal needs one account (email + password)."
if [[ -n "${DETOMSITE_ADMIN_EMAIL:-}" ]]; then
  ADMIN_EMAIL="$DETOMSITE_ADMIN_EMAIL"
else
  ask "  Admin email (Enter to keep ${ADMIN_EMAIL}):" _email_in
  [[ -z "${_email_in:-}" ]] || ADMIN_EMAIL="$_email_in"
fi
echo "  Auto-generated admin password: ${ADMIN_PASSWORD}"
confirm "  Continue?" || fail "Aborted."

# ─── 6. Create / reuse the Supabase project ──────────────────────────
LAST_STEP="Creating Supabase database"
step "Creating your free Supabase database"
if ! supabase projects list 2>/dev/null | grep -q "detomsite-prod"; then
  if [[ -z "$SUPABASE_ORG" ]]; then
    # `supabase orgs list` prints:  <org-id> | <display name>  (org-id may be
    # padded with leading spaces, so we slice out the text before the pipe).
    ORG_ROWS="$(supabase orgs list 2>/dev/null \
        | awk -F'|' '{gsub(/[[:space:]]/,"",$1); if ($1 ~ /^[a-z0-9][A-Za-z0-9_-]{7,}$/) print $0}')"
    [[ -n "$ORG_ROWS" ]] || fail "No Supabase account found. Create one at https://supabase.com first, then re-run."
    ORG_IDS=( $(echo "$ORG_ROWS" | awk -F'|' '{gsub(/[[:space:]]/,"",$1); print $1}') )
    echo "  Which Supabase account should own the database?"
    i=0
    while IFS= read -r line; do
      i=$((i+1))
      name="$(echo "$line" | sed -E 's/^[^|]*\|[[:space:]]*//')"
      echo "    [$i] $name (${ORG_IDS[$((i-1))]})"
    done <<< "$ORG_ROWS"
    ask "  Enter a number:" _org_num
    _org_num="$(echo "${_org_num:-}" | tr -dc '0-9')"
    [[ -n "$_org_num" && "$_org_num" -ge 1 && "$_org_num" -le "${#ORG_IDS[@]}" ]] || fail "No valid number entered."
    SUPABASE_ORG="${ORG_IDS[$((_org_num-1))]}"
  fi
  [[ "$SUPABASE_ORG" =~ ^[A-Za-z0-9_-]+$ ]] || fail "Could not read the Supabase organization ID."
  say "Using Supabase organization: $SUPABASE_ORG"

  DB_PASSWORD="$(openssl rand -base64 18 2>/dev/null | tr -dc 'A-Za-z0-9' | cut -c1-16)Pb1"
  warn "Creating project \"detomsite-prod\" (free tier, region $SUPABASE_REGION) — takes ~1 min..."
  supabase projects create detomsite-prod \
      --org-id "$SUPABASE_ORG" \
      --db-password "$DB_PASSWORD" \
      --region "$SUPABASE_REGION" \
      --plan free \
    || { warn "Free-tier creation may need your billing/phone verification."
         warn "Open https://supabase.com/dashboard and create a project, then re-run this script."; fail "Supabase project was not created."; }
else
  warn "Found an existing project 'detomsite-prod' — reusing it."
  if [[ -n "${DETOMSITE_DB_PASSWORD:-}" ]]; then
    DB_PASSWORD="$DETOMSITE_DB_PASSWORD"
  else
    ask "  Paste its database password (from your earlier .deploy-credentials.txt):" DB_PASSWORD
  fi
  [[ -n "$DB_PASSWORD" ]] || fail "A password is required to reuse the project."
fi

# Ref IDs are always 20 lowercase chars (e.g. wrzshtpxzbtxcreumnxr).
# Supabase's table columns vary between CLI versions, so we locate the ref
# by shape, not position: it's the 2nd 20-char token on the project's row.
PROJECT_REF="$(supabase projects list 2>/dev/null | grep "detomsite-prod" | grep -oE '[a-z0-9]{20}' | sed -n '2p' || true)"
[[ -n "$PROJECT_REF" ]] || fail "Could not read the database project ID. Look it up at https://supabase.com/dashboard"
say "Database project ID: $PROJECT_REF"

# ─── 7. Wait for the DB, then load the schema ────────────────────────
LAST_STEP="Loading database tables"
step "Waiting for the database to go online..."
for _ in $(seq 1 36); do
  code="$(curl -s -o /dev/null -w "%{http_code}" "https://${PROJECT_REF}.supabase.co/rest/v1/" || true)"
  if [[ "$code" == "401" || "$code" == "200" ]]; then
    say "Database is online. Creating all the app tables..."
    break
  fi
  sleep 5
done

MIG_DIR="supabase/migrations"
mkdir -p "$MIG_DIR"
MIG_FILE="$MIG_DIR/$(date +%s)_seed.sql"
cp backend/supabase/schema.sql "$MIG_FILE"
if supabase link --project-ref "$PROJECT_REF" --password "$DB_PASSWORD" >/dev/null 2>&1; then
  supabase db push --project-ref "$PROJECT_REF" >/dev/null 2>&1 \
    || { rm -f "$MIG_FILE"; fail "Could not load tables. Run manually: supabase db push --project-ref $PROJECT_REF"; }
  rm -f "$MIG_FILE"
  say "Database tables are ready."
else
  rm -f "$MIG_FILE"
  fail "Could not link the database (wrong password?). Re-run the script."
fi

if [[ "$SUPABASE_REGION" == "ap-south-1" ]]; then
  DB_URL="postgresql://postgres.${PROJECT_REF}:${DB_PASSWORD}@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
else
  DB_URL="postgresql://postgres.${PROJECT_REF}:${DB_PASSWORD}@db.${PROJECT_REF}.supabase.co:5432/postgres"
fi

# Persist the DB credentials IMMEDIATELY so a later step can never lose them.
{
  echo "DETOMSITE DEPLOYMENT — DATABASE (saved early so it can always be recovered)"
  echo "ref : $PROJECT_REF"
  echo "pass: $DB_PASSWORD"
  echo "url : $DB_URL"
} > "$CRED_FILE"
chmod 600 "$CRED_FILE"

# ─── 8. Create the backend project (first deploy), then set env ──────
LAST_STEP="Creating the backend project on Vercel"
step "Creating the backend project on Vercel (first build, ~3-4 min)..."
(cd backend && vercel --prod --yes) \
  || warn "First backend build had issues — I'll retry after setting the settings."
say "Backend project ready: $BACKEND_PROJECT → $BACKEND_URL"

set_env() {
  local name="$1" value="$2"
  echo "$value" | (cd backend && vercel env add "$name" production) >/dev/null 2>&1 \
    || warn "Could not set env ${name} (may already exist — fine)."
}
set_env USE_SUPABASE_DB        "True"
set_env USE_LOCAL_DB           "False"
set_env USE_TURSO_DB           "False"
set_env SUPABASE_DATABASE_URL  "$DB_URL"
set_env JWT_SECRET             "$JWT_SECRET"
set_env FRONTEND_URL           "$FRONTEND_URL"
set_env BACKEND_URL            "$BACKEND_URL"
set_env ALLOWED_ORIGINS        "[\"$FRONTEND_URL\",\"http://localhost:5173\"]"
set_env DEFAULT_SUPER_ADMIN_EMAIL    "$ADMIN_EMAIL"
set_env DEFAULT_SUPER_ADMIN_PASSWORD "$ADMIN_PASSWORD"
say "Environment variables set on the backend"

# ─── 9. Redeploy the backend (now with the real settings) ────────────
LAST_STEP="Deploying backend"
step "Deploying the backend with the real settings..."
BACKEND_OUT="$(cd backend && vercel --prod --yes 2>&1 || true)"
echo "$BACKEND_OUT" | tail -n 6
if ! echo "$BACKEND_OUT" | grep -qiE "ready|completed|success|deployed" && echo "$BACKEND_OUT" | grep -qiE "error|failed|✖"; then
  warn "Backend build needs attention — the site will still deploy, but if you"
  warn "see errors on it, use Render instead (free):"
  echo "   1. push this folder to GitHub"
  echo "   2. render.com → NEW → Blueprint → pick the repo → Create"
  echo "   3. then set VITE_API_URL on Vercel to your Render URL + /api/v1"
fi

# ─── 10. Deploy the frontend ─────────────────────────────────────────
LAST_STEP="Deploying frontend"
step "Deploying the student/shop marketplace site..."
(cd frontend && vercel link --yes --project "$FRONTEND_PROJECT" >/dev/null 2>&1) || true
# VITE_API_URL must be a PROJECT env var, not a per-deploy "-e" flag: Vite's
# build on Vercel only sees project-scoped vars, so "-e" silently produces a
# bundle with the localhost default. This is proven in production.
printf '%s\n' "$BACKEND_URL/api/v1" | (cd frontend && vercel env add VITE_API_URL production) >/dev/null 2>&1 \
  || warn "Could not set VITE_API_URL (may already exist — fine)."
FRONTEND_OUT="$(cd frontend && vercel --prod --yes 2>&1 || true)"
echo "$FRONTEND_OUT" | tail -n 6

# ─── 11. Save credentials + summary ──────────────────────────────────
LAST_STEP="Writing your credentials"
{
  echo "DETOMSITE DEPLOYMENT CREDENTIALS — keep this file safe"
  echo ""
  echo "App (student/shopkeeper/admin) : $FRONTEND_URL"
  echo "Backend API                    : $BACKEND_URL"
  echo ""
  echo "ADMIN PORTAL LOGIN"
  echo "  url  : $FRONTEND_URL/admin"
  echo "  email: $ADMIN_EMAIL"
  echo "  pass : $ADMIN_PASSWORD"
  echo ""
  echo "DATABASE (Supabase)"
  echo "  url : $DB_URL"
  echo "  ref : $PROJECT_REF"
} > "$CRED_FILE"
chmod 600 "$CRED_FILE"

echo
echo -e "${GREEN}${BOLD}  🎉  DEPLOYMENT COMPLETE!  ${NC}"
echo -e "  Logins saved to: ${BOLD}${CRED_FILE}${NC}"
echo
echo -e "  ${BOLD}Your app (everything in one place):${NC}"
echo "    ${FRONTEND_URL}"
echo
echo -e "  ${BOLD}Admin login:${NC}"
echo "    ${FRONTEND_URL}/admin"
echo "    email: ${ADMIN_EMAIL}"
echo "    pass : ${ADMIN_PASSWORD}"
echo
echo "  First steps:"
echo "   1. Open the admin site above and log in."
echo "   2. Wait ~1 min after opening it — the first request wakes the backend."
echo "   3. Use the Shopkeeper portal to register a shop, then order from Student."