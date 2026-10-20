#!/usr/bin/env bash
# Runs every automated check: backend tests with a coverage gate, frontend lint,
# frontend tests, and a production build. Stops at the first failure.
#
#   ./scripts/check.sh            run everything
#   ./scripts/check.sh backend    backend tests only
#   ./scripts/check.sh frontend   frontend lint, tests and build only
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
what="${1:-all}"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# Prefer the project's virtualenv when there is one.
python_bin=python
for candidate in "$root/backend/.venv/bin/python" "$root/backend/.venv/Scripts/python.exe"; do
  [[ -x "$candidate" ]] && python_bin="$candidate"
done

if [[ "$what" == "all" || "$what" == "backend" ]]; then
  step "Backend tests (coverage gate lives in backend/.coveragerc)"
  command -v ffmpeg >/dev/null || echo "note: ffmpeg not found, so the real-media tests will be skipped"
  (cd "$root/backend" && "$python_bin" -m pytest --cov=app)
fi

if [[ "$what" == "all" || "$what" == "frontend" ]]; then
  cd "$root/frontend/clippper"
  [[ -d node_modules ]] || { step "Installing frontend dependencies"; npm ci; }
  step "Frontend lint";  npm run lint
  step "Frontend tests"; npm run test:coverage
  step "Frontend build"
  VITE_API_URL="${VITE_API_URL:-http://localhost:8000}" \
  VITE_CLERK_PUBLISHABLE_KEY="${VITE_CLERK_PUBLISHABLE_KEY:-pk_test_placeholder}" \
    npm run build
fi

printf '\n\033[1;32mAll checks passed.\033[0m\n'
