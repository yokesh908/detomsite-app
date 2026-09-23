#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Redeploy the two Vite projects whose Vercel "Root Directory" is a subfolder.
#
#   detomsite-frontend  → Root Directory "frontend"         → deploy from repo root
#   detomsite-student   → Root Directory "frontend/student" → deploy from repo root
#
# Deploying them from inside their own folder makes Vercel look for
# "<folder>/frontend" and fail with:
#   Error: The specified Root Directory "frontend" does not exist.
# That is exactly the error the last two deploys hit, so this script always runs
# from the repository root.
#
# The repo-root .vercelignore keeps the 143 MB upload down to a few MB.
#
# Usage:  bash scripts/deploy-root-dir-projects.sh [student|frontend|both]
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Same scope/IDs as frontend/.vercel/project.json and frontend/student/.vercel/project.json.
ORG_ID="team_AeznTxmDmdbQm8nxPjuaibn3"
FRONTEND_PROJECT_ID="prj_SrMY5EGH8A87snFS34iNeX7blJd9"   # detomsite-frontend
STUDENT_PROJECT_ID="prj_TXnp0z3dRA1tpaAX1Y5Na2R7746V"    # detomsite-student

TARGET="${1:-both}"

deploy() {
  local project="$1" project_id="$2"
  echo "──────── deploying ${project} from ${REPO_ROOT} ────────"
  # VERCEL_PROJECT_ID overrides the repo-root .vercel link, which points at
  # detomsite-frontend — the documented way to deploy a specific project
  # non-interactively.
  if VERCEL_ORG_ID="$ORG_ID" VERCEL_PROJECT_ID="$project_id" \
       vercel --prod --yes; then
    echo "✓ ${project} deployed"
  else
    echo "✗ ${project} deploy failed" >&2
    return 1
  fi
}

status=0
case "$TARGET" in
  frontend) deploy detomsite-frontend "$FRONTEND_PROJECT_ID" || status=1 ;;
  student)  deploy detomsite-student  "$STUDENT_PROJECT_ID"  || status=1 ;;
  both)     deploy detomsite-frontend "$FRONTEND_PROJECT_ID" || status=1
            deploy detomsite-student  "$STUDENT_PROJECT_ID"  || status=1 ;;
  *) echo "usage: $0 [student|frontend|both]" >&2; exit 2 ;;
esac

# Verify what actually went live (the /health endpoint of the API too, so a
# backend change can be confirmed in the same run).
echo "──────── verification ────────"
curl -s -m 30 https://detomsite-backend.vercel.app/health || true
echo
for site in detomsite-frontend detomsite-student; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 30 "https://${site}.vercel.app/")"
  echo "${site}: HTTP ${code}"
done

exit "$status"
