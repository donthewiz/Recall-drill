#!/bin/bash
# SessionStart hook: make sure the test tools are installed. Cloud sessions only.
#
# Each add-on gets its own Python 3.13 venv (they must stay apart: Math Path's tests check
# that no system SymPy is installed, while Recall Drill's dev pins install it). The venvs
# live in ~/venvs so the cloud environment's setup script can build them once and the
# snapshot keeps them; each add-on folder gets a .venv link to its venv (gitignored).
# `uv pip install -r` is a quick no-op when everything is already installed.
# Prints one line (it becomes session context); details go to the log file.

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0
log=/tmp/recall-drill-session-setup.log
: > "$log"
status=()

setup_venv() {
  local name=$1
  local venv="$HOME/venvs/$name"
  if [ ! -x "$venv/bin/python" ]; then
    uv venv --python 3.13 "$venv" >> "$log" 2>&1 || python3.13 -m venv "$venv" >> "$log" 2>&1
  fi
  if uv pip install --python "$venv/bin/python" -r "$name/requirements-dev.txt" >> "$log" 2>&1; then
    [ -e "$name/.venv" ] || ln -s "$venv" "$name/.venv"
    status+=("$name venv ok")
  else
    status+=("$name venv FAILED")
  fi
}

setup_venv anki-addon
setup_venv mathpath-addon

hashes=node_modules/.session_setup.sha256
if sha256sum --check --status "$hashes" 2>/dev/null; then
  status+=("node_modules ok")
else
  rm -f "$hashes"
  if npm ci >> "$log" 2>&1; then
    sha256sum package.json package-lock.json > "$hashes" || rm -f "$hashes"
    status+=("node_modules ok")
  else
    status+=("npm ci FAILED")
  fi
fi

line="Session setup: ${status[*]}"
line=${line//ok /ok, }
if [[ "$line" == *FAILED* ]]; then
  line="$line (log: $log)"
fi
echo "$line"
exit 0
