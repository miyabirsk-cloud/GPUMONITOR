#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-"$HOME/.local/share"}"
APP_DIR="$DATA_HOME/gpu-monitor"
APP_PYTHON="$APP_DIR/venv/bin/python"
APP_BIN="$HOME/.local/bin"
APP_MENU="$DATA_HOME/applications"

if ! command -v python3 >/dev/null 2>&1; then
    printf 'GPU Monitor requires Python 3.10 or newer. Install Python and retry.\n' >&2
    exit 1
fi

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
    printf 'GPU Monitor requires Python 3.10 or newer.\n' >&2
    exit 1
}

mkdir -p "$APP_DIR" "$APP_BIN" "$APP_MENU"
install -m 644 "$SCRIPT_DIR/gpu_monitor.py" "$APP_DIR/gpu_monitor.py"

if [[ ! -x "$APP_PYTHON" ]]; then
    python3 -m venv --system-site-packages "$APP_DIR/venv"
fi

if ! "$APP_PYTHON" -c 'import PySide6' >/dev/null 2>&1; then
    "$APP_PYTHON" -m pip install 'PySide6>=6.8'
fi

python3 - "$APP_DIR" "$APP_MENU" <<'PY'
from pathlib import Path
import shlex
import sys

app_dir, menu_dir = map(Path, sys.argv[1:])
launcher = app_dir / "launch.sh"
launcher.write_text(
    "#!/bin/sh\nexec "
    + shlex.quote(str(app_dir / "venv/bin/python"))
    + " "
    + shlex.quote(str(app_dir / "gpu_monitor.py"))
    + ' "$@"\n',
    encoding="utf-8",
)
launcher.chmod(0o755)

def desktop_arg(value: Path) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'

entry = menu_dir / "gpu-monitor.desktop"
entry.write_text(
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=GPU Monitor\n"
    "Comment=Live AMD GPU usage, temperature, fan and power graphs\n"
    f"Exec={desktop_arg(launcher)}\n"
    "Icon=utilities-system-monitor\n"
    "Terminal=false\n"
    "Categories=System;Monitor;\n"
    "StartupNotify=true\n",
    encoding="utf-8",
)
entry.chmod(0o755)
PY

COMMAND="$APP_BIN/gpu-monitor"
if [[ (! -e "$COMMAND" && ! -L "$COMMAND") || \
      (-L "$COMMAND" && "$(readlink -f -- "$COMMAND")" == "$APP_DIR/launch.sh") ]]; then
    ln -sfn "$APP_DIR/launch.sh" "$COMMAND"
else
    printf 'Not replacing existing command: %s\n' "$COMMAND" >&2
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$APP_MENU/gpu-monitor.desktop"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_MENU"
fi

if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
    if [[ -n "$DESKTOP_DIR" && -d "$DESKTOP_DIR" ]]; then
        install -m 755 "$APP_MENU/gpu-monitor.desktop" "$DESKTOP_DIR/GPU Monitor.desktop"
    fi
fi

printf 'GPU Monitor installed. Launch it from your app menu or run:\n  %s\n' \
    "$APP_DIR/launch.sh"
