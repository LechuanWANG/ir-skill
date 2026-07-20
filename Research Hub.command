#!/bin/zsh

set -u

# Finder does not inherit the shell PATH, including the usual Homebrew locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
WEB_ROOT="$PROJECT_ROOT/web"
ADDRESS="http://127.0.0.1:8765"

# The data layer is project-scoped; Finder may open .command files from another cwd.
export IR_SKILL_PROJECT_DIR="$PROJECT_ROOT"
cd "$PROJECT_ROOT"

hub_is_ready() {
  /usr/bin/curl --silent --fail --max-time 1 --output /dev/null "$ADDRESS/"
}

if hub_is_ready; then
  echo "Research Hub is already running. Opening $ADDRESS"
  /usr/bin/open "$ADDRESS"
  exit 0
fi

if /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Port 8765 is already in use by another application."
  echo "Stop that application and run this shortcut again."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3 and run this shortcut again."
  exit 1
fi

if [ ! -f "$WEB_ROOT/dist/index.html" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "The UI has not been built and npm was not found. Install Node.js and run this shortcut again."
    exit 1
  fi

  if [ ! -d "$WEB_ROOT/node_modules" ]; then
    echo "Installing Research Hub frontend dependencies..."
    if ! (cd "$WEB_ROOT" && npm ci); then
      echo "Frontend dependency installation failed."
      exit 1
    fi
  fi

  echo "Building the Research Hub frontend..."
  if ! (cd "$WEB_ROOT" && npm run build); then
    echo "Frontend build failed."
    exit 1
  fi
fi

echo "Starting Research Hub at $ADDRESS"
echo "Keep this Terminal window open while using the UI. Press Control+C here to stop it."
exec python3 "$PROJECT_ROOT/scripts/research_hub_server.py" --host 127.0.0.1 --port 8765 --open
