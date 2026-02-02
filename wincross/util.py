import sys
from pathlib import Path
from typing import Any

from .constants import STATE_DIRNAME


def die(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def state_dir(root: Path) -> Path:
    return root / STATE_DIRNAME


def is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def to_container_path(host_path: Path, root: Path, container_root: str) -> str:
    if not is_under_root(host_path, root):
        die(f"path must be under project root: {host_path}")
    rel = host_path.relative_to(root).as_posix()
    if rel == ".":
        return container_root
    return f"{container_root}/{rel}"


def parse_key_value(text: str) -> tuple[str, str]:
    if "=" not in text:
        die(f"expected KEY=VALUE, got: {text}")
    key, value = text.split("=", 1)
    key = key.strip()
    if not key:
        die(f"invalid KEY in: {text}")
    return key, value


def parse_mount_spec(text: str, root: Path) -> dict:
    parts = text.split(":")
    if len(parts) < 2:
        die(f"invalid mount spec: {text} (expected host:container[:ro|rw])")
    host = Path(parts[0])
    if not host.is_absolute():
        host = (root / host).resolve()
    container = parts[1]
    mode = parts[2] if len(parts) > 2 else "rw"
    if mode not in ("ro", "rw"):
        die(f"invalid mount mode in {text}: {mode}")
    if not host.exists():
        die(f"mount host path not found: {host}")
    return {
        "host_path": str(host),
        "container_path": container,
        "read_only": mode == "ro",
    }


def parse_toolchain_spec(text: str, root: Path) -> dict:
    if "=" not in text:
        die(
            f"invalid toolchain spec: {text} "
            "(expected name=host[:container[:ro|rw]])"
        )
    name, rest = text.split("=", 1)
    name = name.strip()
    if not name:
        die(f"invalid toolchain name in: {text}")
    parts = rest.split(":")
    host = Path(parts[0])
    if not host.is_absolute():
        host = (root / host).resolve()
    container = parts[1] if len(parts) > 1 and parts[1] else ""
    mode = parts[2] if len(parts) > 2 else None
    if mode is not None and mode not in ("ro", "rw"):
        die(f"invalid toolchain mode in {text}: {mode}")
    if not host.exists():
        die(f"toolchain host path not found: {host}")
    return {
        "name": name,
        "host_path": str(host),
        "container_path": container,
        "read_only": True if mode == "ro" else False if mode == "rw" else None,
    }


def merge_env(base: dict, override: dict) -> dict:
    result = dict(base or {})
    result.update(override or {})
    return result


def merge_lists(base: list[str] | None, override: list[str] | None) -> list[str]:
    return list(base or []) + list(override or [])


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def merge_toolchains(project_tc: dict, build_tc: dict) -> dict:
    merged: dict[str, dict] = {}
    for name, data in (project_tc or {}).items():
        merged[name] = dict(data)
    for name, data in (build_tc or {}).items():
        if name in merged:
            merged[name].update(data)
        else:
            merged[name] = dict(data)
    return merged


def get_bool(value: Any, *, context: str) -> bool:
    if isinstance(value, bool):
        return value
    die(f"{context} must be true/false")
    return False
