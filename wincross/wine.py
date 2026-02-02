from pathlib import Path

from .docker import run_docker


def ensure_mt_wrapper(path: Path) -> None:
    if path.exists():
        return
    path.write_text(
        "#!/usr/bin/env bash\n"
        "# Ignore mt.exe /notify_update failures under Wine.\n"
        "MT=/opt/msvc/bin/x64/mt\n"
        'if [[ " $* " == *" /notify_update "* ]]; then\n'
        '  "$MT" "$@" || exit 0\n'
        "  exit 0\n"
        "fi\n"
        'exec "$MT" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def ensure_wine_runtime(cfg: dict, root: Path, verbose: bool) -> None:
    script = (
        "set -e\n"
        'if [ -z "$WINEPREFIX" ]; then\n'
        "  echo 'WINEPREFIX is not set' >&2\n"
        "  exit 1\n"
        "fi\n"
        "BIN_DIR=$(find /opt/msvc/VC/Tools/MSVC -path '*/bin/Hostx64/x64' -type d | sort | tail -n 1)\n"
        'if [ -z "$BIN_DIR" ]; then\n'
        "  echo 'MSVC bin directory not found' >&2\n"
        "  exit 1\n"
        "fi\n"
        'SYS32="$WINEPREFIX/drive_c/windows/system32"\n'
        'mkdir -p "$SYS32"\n'
        "for dll in vcruntime140.dll vcruntime140_1.dll vcruntime140_threads.dll \\\n"
        "  msvcp140.dll msvcp140_1.dll msvcp140_2.dll msvcp140_atomic_wait.dll \\\n"
        "  concrt140.dll; do\n"
        '  if [ -f "$BIN_DIR/$dll" ]; then\n'
        '    cp -f "$BIN_DIR/$dll" "$SYS32/$dll"\n'
        "  fi\n"
        "done\n"
    )
    run_docker(cfg, root, ["bash", "-lc", script], False, verbose)
