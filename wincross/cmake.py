from pathlib import Path

from .constants import DEFAULT_CONTAINER_ROOT
from .util import to_container_path


def cmake_args(cfg: dict, root: Path, extra: list[str]) -> list[str]:
    args = ["cmake"]
    args += ["-S", DEFAULT_CONTAINER_ROOT]

    build_dir = Path(cfg["build_dir"]).resolve()
    container_build = to_container_path(build_dir, root, DEFAULT_CONTAINER_ROOT)
    args += ["-B", container_build]

    defaults = cfg.get("cmake_defaults", [])
    combined = defaults + extra

    if cfg.get("generator"):
        if "-G" not in combined:
            args += ["-G", cfg["generator"]]

    if cfg.get("build_type"):
        if not any(
            a.startswith("-DCMAKE_BUILD_TYPE=") or a.startswith("-DCMAKE_BUILD_TYPE:")
            for a in combined
        ):
            args.append(f"-DCMAKE_BUILD_TYPE={cfg['build_type']}")

    args += defaults
    args += extra
    return args


def build_args(cfg: dict, root: Path, extra: list[str]) -> list[str]:
    build_dir = Path(cfg["build_dir"]).resolve()
    container_build = to_container_path(build_dir, root, DEFAULT_CONTAINER_ROOT)
    args = ["cmake", "--build", container_build]
    if not any(a in ("--parallel", "-j") or a.startswith("-j") for a in extra):
        args.append("--parallel")
    args += extra
    return args


def test_args(cfg: dict, root: Path, extra: list[str]) -> list[str]:
    build_dir = Path(cfg["build_dir"]).resolve()
    container_build = to_container_path(build_dir, root, DEFAULT_CONTAINER_ROOT)
    args = ["ctest", "--test-dir", container_build]
    if "--output-on-failure" not in extra:
        args.append("--output-on-failure")
    args += extra
    return args
