import shutil
import sys
from pathlib import Path

from .util import merge_toolchains


def doctor(project_cfg: dict, build_cfg: dict, root: Path) -> None:
    errors: list[str] = []

    if not shutil.which("docker"):
        errors.append("docker not found on PATH")

    project_root = Path(build_cfg.get("project_root", ""))
    if not project_root.exists():
        errors.append(f"project_root missing: {project_root}")
    if project_root.resolve() != root:
        errors.append(
            f"project_root does not match current repo: {project_root} != {root}"
        )

    toolchains = merge_toolchains(
        project_cfg.get("toolchains", {}), build_cfg.get("toolchains", {})
    )
    for name, tool in toolchains.items():
        host_path = tool.get("host_path")
        container_path = tool.get("container_path")
        if not host_path:
            errors.append(f"toolchain '{name}' missing host_path in build config")
            continue
        if not container_path:
            errors.append(
                f"toolchain '{name}' missing container_path (project or build config)"
            )
        if not Path(host_path).exists():
            errors.append(f"toolchain '{name}' path missing: {host_path}")

    vcpkg_project = project_cfg.get("vcpkg", {}) or {}
    vcpkg_build = build_cfg.get("vcpkg", {}) or {}
    vcpkg_enabled = vcpkg_build.get("enabled", vcpkg_project.get("enabled", False))
    if vcpkg_enabled:
        host_root = vcpkg_build.get("host_root")
        host_cache = vcpkg_build.get("host_binary_cache")
        if not host_root:
            errors.append("vcpkg enabled but host_root missing in build config")
        elif not Path(host_root).exists():
            errors.append(f"vcpkg root missing: {host_root}")
        if not host_cache:
            errors.append("vcpkg enabled but host_binary_cache missing in build config")
        elif not Path(host_cache).exists():
            errors.append(f"vcpkg binary cache missing: {host_cache}")

    if errors:
        for err in errors:
            print(f"doctor: {err}", file=sys.stderr)
        raise SystemExit(1)

    print("Doctor: OK")
