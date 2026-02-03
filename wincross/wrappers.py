import shlex
from pathlib import Path
from typing import Any

from .constants import DEFAULT_CONTAINER_ROOT, STATE_DIRNAME
from .util import die, ensure_dir, state_dir, to_container_path


def expand_winexe_template(template: str, cfg: dict, root: Path) -> str:
    build_dir = Path(cfg["build_dir"]).resolve()
    container_build = to_container_path(build_dir, root, DEFAULT_CONTAINER_ROOT)
    container_state = f"{DEFAULT_CONTAINER_ROOT}/{STATE_DIRNAME}"
    config_dir = cfg.get("config_dir") or DEFAULT_CONTAINER_ROOT
    mapping = {
        "build_dir": container_build,
        "project_root": DEFAULT_CONTAINER_ROOT,
        "state_dir": container_state,
        "config_dir": config_dir,
    }
    try:
        return template.format(**mapping)
    except KeyError as exc:
        die(f"unknown placeholder '{exc.args[0]}' in winexe wrapper exe: {template}")


def _winepath_env(cfg: dict) -> str:
    winepath = cfg.get("winepath_prepend", []) or []
    winepath_entries: list[str] = []
    for entry in winepath:
        if not entry:
            continue
        winepath_entries.append(f"z:{entry.replace('/', '\\\\')}")
    return ";".join(winepath_entries)


def render_winexe_wrapper(exe: str, msvc_env: bool) -> str:
    exe_quoted = shlex.quote(exe)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"EXE={exe_quoted}",
        'EXE_DIR=$(dirname "$EXE")',
        'EXE_WIN="z:${EXE_DIR//\\//\\\\}"',
    ]
    if msvc_env:
        lines.append("source /opt/msvc/bin/x64/msvcenv.sh")
    lines += [
        'EXTRA_OVERRIDES="msvcp140=n;msvcp140_1=n;msvcp140_2=n;msvcp140_atomic_wait=n"',
        'if [ -n "${WINEDLLOVERRIDES:-}" ]; then',
        '  export WINEDLLOVERRIDES="${EXTRA_OVERRIDES};${WINEDLLOVERRIDES}"',
        "else",
        '  export WINEDLLOVERRIDES="${EXTRA_OVERRIDES}"',
        "fi",
    ]
    lines += [
        'WINEPATH_PREFIX="${EXE_WIN}"',
        'if [ -n "${WINCROSS_WINEPATH_PREPEND:-}" ]; then',
        '  WINEPATH_PREFIX="${WINEPATH_PREFIX};${WINCROSS_WINEPATH_PREPEND}"',
        "fi",
        'if [ -n "${WINEPATH:-}" ]; then',
        '  export WINEPATH="${WINEPATH_PREFIX};${WINEPATH}"',
        "else",
        '  export WINEPATH="${WINEPATH_PREFIX}"',
        "fi",
    ]
    lines += [
        'MAGIC=$(head -c 2 "$EXE" 2>/dev/null || true)',
        'if [ "$MAGIC" = "MZ" ]; then',
        '  exec /opt/msvc/bin/x64/wine-msvc.sh "$EXE" "$@"',
        "fi",
        'exec "$EXE" "$@"',
    ]
    return "\n".join(lines) + "\n"


def ensure_winexe_wrappers(cfg: dict, root: Path) -> None:
    wrappers = cfg.get("winexe_wrappers", []) or []
    if not wrappers:
        return
    wrapper_dir = state_dir(root) / "bin"
    ensure_dir(wrapper_dir)
    winepath_env = _winepath_env(cfg)
    for wrapper in wrappers:
        name = wrapper["name"]
        exe_template = wrapper["exe"]
        exe = expand_winexe_template(exe_template, cfg, root)
        msvc_env = bool(wrapper.get("msvc_env", False))
        script_path = wrapper_dir / name
        if script_path.exists() and script_path.is_dir():
            die(f"wrapper path is a directory: {script_path}")
        content = render_winexe_wrapper(exe, msvc_env)
        if winepath_env:
            content = content.replace(
                "#!/usr/bin/env bash\n",
                f"#!/usr/bin/env bash\nWINCROSS_WINEPATH_PREPEND={shlex.quote(winepath_env)}\n",
                1,
            )
        if script_path.exists():
            existing = script_path.read_text(encoding="utf-8")
            if existing == content:
                continue
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)


def render_cross_emulator(emulator_env: dict) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'if [ "$#" -lt 1 ]; then',
        "  echo 'usage: wincross-emulator <exe> [args...]' >&2",
        "  exit 2",
        "fi",
        'ORIG_PATH="$PATH"',
        "if [ -f /opt/msvc/bin/x64/msvcenv.sh ]; then",
        "  source /opt/msvc/bin/x64/msvcenv.sh",
        '  PATH="$ORIG_PATH"',
        "fi",
    ]
    for key, value in sorted((emulator_env or {}).items()):
        lines.append(f"export {key}={shlex.quote(value)}")
    lines += [
        'EXE="$1"',
        "shift",
        'EXE_DIR=$(dirname "$EXE")',
        'EXE_WIN="z:${EXE_DIR//\\//\\\\}"',
        'EXTRA_OVERRIDES="msvcp140=n;msvcp140_1=n;msvcp140_2=n;msvcp140_atomic_wait=n"',
        'if [ -n "${WINEDLLOVERRIDES:-}" ]; then',
        '  export WINEDLLOVERRIDES="${EXTRA_OVERRIDES};${WINEDLLOVERRIDES}"',
        "else",
        '  export WINEDLLOVERRIDES="${EXTRA_OVERRIDES}"',
        "fi",
        'WINEPATH_PREFIX="${EXE_WIN}"',
        'if [ -n "${WINCROSS_WINEPATH_PREPEND:-}" ]; then',
        '  WINEPATH_PREFIX="${WINEPATH_PREFIX};${WINCROSS_WINEPATH_PREPEND}"',
        "fi",
        'if [ -n "${WINEPATH:-}" ]; then',
        '  export WINEPATH="${WINEPATH_PREFIX};${WINEPATH}"',
        "else",
        '  export WINEPATH="${WINEPATH_PREFIX}"',
        "fi",
        'exec /opt/msvc/bin/x64/wine-msvc.sh "$EXE" "$@"',
    ]
    return "\n".join(lines) + "\n"


def ensure_cross_emulator(cfg: dict, root: Path) -> None:
    wrapper_dir = state_dir(root) / "bin"
    ensure_dir(wrapper_dir)
    script_path = wrapper_dir / "wincross-emulator"
    emulator_env = cfg.get("emulator_env", {}) or {}
    content = render_cross_emulator(emulator_env)
    winepath_env = _winepath_env(cfg)
    if winepath_env:
        content = content.replace(
            "#!/usr/bin/env bash\n",
            f"#!/usr/bin/env bash\nWINCROSS_WINEPATH_PREPEND={shlex.quote(winepath_env)}\n",
            1,
        )
    if script_path.exists():
        existing = script_path.read_text(encoding="utf-8")
        if existing == content:
            return
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)


def ensure_bin_aliases(cfg: dict, root: Path) -> None:
    aliases = cfg.get("bin_aliases", []) or []
    if not aliases:
        return
    build_dir = Path(cfg["build_dir"]).resolve()
    bin_dir = build_dir / "bin"
    ensure_dir(bin_dir)
    state_host = Path(cfg["state_dir"]).resolve()
    state_container = to_container_path(state_host, root, DEFAULT_CONTAINER_ROOT)
    for name in aliases:
        if not isinstance(name, str) or not name.strip():
            die("bin_aliases entries must be non-empty strings")
        script_path = bin_dir / name
        content = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'exec "{state_container}/bin/{name}" "$@"\n'
        )
        if script_path.exists():
            existing = script_path.read_text(encoding="utf-8")
            if existing == content:
                continue
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)


def normalize_winexe_wrappers(raw: Any, *, context: str) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        die(f"{context} winexe_wrappers must be a list")
    wrappers: list[dict] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            die(f"{context} winexe_wrappers[{idx}] must be a table")
        name = item.get("name")
        exe = item.get("exe")
        if not isinstance(name, str) or not name.strip():
            die(f"{context} winexe_wrappers[{idx}] missing name")
        if Path(name).name != name:
            die(f"{context} winexe_wrappers[{idx}] name must be a basename: {name}")
        if not isinstance(exe, str) or not exe.strip():
            die(f"{context} winexe_wrappers[{idx}] missing exe")
        msvc_env = item.get("msvc_env", False)
        if not isinstance(msvc_env, bool):
            die(f"{context} winexe_wrappers[{idx}] msvc_env must be true/false")
        wrappers.append({"name": name, "exe": exe, "msvc_env": msvc_env})
    return wrappers


def merge_winexe_wrappers(
    project_wrappers: list[dict], build_wrappers: list[dict]
) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for wrapper in list(project_wrappers or []) + list(build_wrappers or []):
        name = wrapper["name"]
        if name not in merged:
            order.append(name)
        merged[name] = dict(wrapper)
    return [merged[name] for name in order]
