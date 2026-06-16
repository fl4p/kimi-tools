#!/usr/bin/env bash
# One-shot setup of the kimi-tools SWE-bench benchmark on an x86-64 Linux server.
# Idempotent. Requires: docker (daemon reachable), python3, git, curl.
#   FIREWORKS_API_KEY=fw_... bash ab/server/setup.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${VENV:-$HOME/swebench-venv}"

echo "[1/5] preflight"
[ "$(uname -m)" = x86_64 ] || echo "  WARN: $(uname -m) — SWE-bench images are x86_64 (expect qemu emulation)."
command -v docker  >/dev/null || { echo "  ERROR: docker missing"; exit 1; }
docker info >/dev/null 2>&1   || { echo "  ERROR: docker daemon unreachable (rootless? set DOCKER_HOST / add to docker group)"; exit 1; }
command -v python3 >/dev/null || { echo "  ERROR: python3 missing"; exit 1; }
echo "  docker root: $(docker info 2>/dev/null | awk -F': ' '/Docker Root Dir/{print $2}')"
echo "  free on /  : $(df -h --output=avail / | tail -1 | tr -d ' ')"

echo "[2/5] python venv + swebench -> $VENV"
# Stock Ubuntu often lacks python3-venv's ensurepip and there's no sudo here, so
# create the venv without pip and bootstrap it with get-pip.py (no apt needed).
rm -rf "$VENV"
python3 -m venv --without-pip "$VENV"
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python"
fi
"$VENV/bin/pip" -q install --upgrade pip
"$VENV/bin/pip" -q install swebench

echo "[3/5] opencode"
if ! command -v opencode >/dev/null 2>&1 && [ ! -x "$HOME/.opencode/bin/opencode" ]; then
  curl -fsSL https://opencode.ai/install | bash
fi
export PATH="$HOME/.opencode/bin:$PATH"
command -v opencode >/dev/null || { echo "  ERROR: opencode not on PATH (add ~/.opencode/bin)"; exit 1; }
echo "  opencode: $(command -v opencode)  $(opencode --version 2>/dev/null || true)"

echo "[4/5] Fireworks auth for opencode"
: "${FIREWORKS_API_KEY:?set FIREWORKS_API_KEY in env (NEVER commit it)}"
AUTH="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/auth.json"
mkdir -p "$(dirname "$AUTH")"
FIREWORKS_API_KEY="$FIREWORKS_API_KEY" python3 - "$AUTH" <<'PY'
import json, os, sys
p = sys.argv[1]
d = {}
if os.path.exists(p):
    try: d = json.load(open(p))
    except Exception: d = {}
d["fireworks-ai"] = {"type": "api", "key": os.environ["FIREWORKS_API_KEY"]}
json.dump(d, open(p, "w")); os.chmod(p, 0o600)
print("  wrote", p, "(chmod 600)")
PY

echo "[5/5] verify Kimi models visible to opencode"
opencode models 2>/dev/null | grep -i kimi || echo "  WARN: kimi models not listed — check key/provider."
echo
echo "OK. Next:"
echo "  export PATH=\$HOME/.opencode/bin:\$PATH"
echo "  VENV=$VENV bash $HERE/run_all.sh        # (run inside tmux)"
