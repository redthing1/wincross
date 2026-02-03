import argparse
import shlex
from pathlib import Path
from typing import Any

from .cmake import build_args, cmake_args, test_args
from .config import (
    build_config_path,
    load_build_config,
    load_project_config,
    project_config_path,
    repo_root,
    resolve_effective_config,
    select_profile,
    validate_project_config,
    write_config,
)
from .constants import DEFAULT_IMAGE, PROJECT_CONFIG_FILENAME
from .docker import run_docker, run_shell
from .doctor import doctor
from .util import (
    die,
    ensure_dir,
    is_under_root,
    parse_key_value,
    parse_mount_spec,
    parse_toolchain_spec,
    state_dir,
)
from .vcpkg import ensure_vcpkg
from .wine import ensure_mt_wrapper, ensure_wine_runtime
from .wrappers import ensure_bin_aliases, ensure_cross_emulator, ensure_winexe_wrappers


def _extend_shlex_args(raw_args: list[str] | None) -> list[str]:
    extra: list[str] = []
    for raw in raw_args or []:
        extra.extend(shlex.split(raw))
    return extra


def handle_init(args: argparse.Namespace) -> None:
    root = repo_root(args.root, args.project_config)
    build_cfg_path = build_config_path(root, args.build_config)
    project_cfg_path = project_config_path(root, args.project_config)
    state = state_dir(root)

    project_cfg = load_project_config(project_cfg_path)
    project_cfg = select_profile(project_cfg, args.profile)
    validate_project_config(project_cfg)

    build_dir_value = (
        args.build_dir
        if args.build_dir
        else project_cfg.get("build_dir") or state / "build-windows"
    )
    build_dir = Path(build_dir_value)
    if not build_dir.is_absolute():
        build_dir = (root / build_dir).resolve()

    if not is_under_root(build_dir, root):
        die(f"build_dir must be under project root: {build_dir}")

    toolchains_map: dict[str, dict[str, Any]] = {}
    project_toolchains = project_cfg.get("toolchains", {}) or {}
    for spec in args.toolchain or []:
        tc = parse_toolchain_spec(spec, root)
        project_tc = project_toolchains.get(tc["name"], {})
        if not tc["container_path"]:
            tc["container_path"] = project_tc.get("container_path", "")
        if not tc["container_path"]:
            die(
                f"toolchain '{tc['name']}' missing container_path (set in project config or init spec)"
            )
        if tc["read_only"] is None:
            tc["read_only"] = bool(project_tc.get("read_only", False))
        toolchains_map[tc["name"]] = {
            "host_path": tc["host_path"],
            "container_path": tc["container_path"],
            "read_only": tc["read_only"],
        }

    for name in project_toolchains:
        if name not in toolchains_map:
            die(
                f"toolchain '{name}' requires a host path (use --toolchain {name}=HOST[:CONTAINER[:ro|rw]])"
            )

    mounts = [parse_mount_spec(m, root) for m in (args.mount or [])]

    env = dict(parse_key_value(e) for e in (args.env or []))
    path_prepend = args.path_prepend or []

    vcpkg_cfg: dict[str, Any] = {}
    project_vcpkg = project_cfg.get("vcpkg", {}) or {}
    vcpkg_enabled = bool(args.vcpkg or project_vcpkg.get("enabled", False))

    if vcpkg_enabled:
        vcpkg_root = Path(args.vcpkg_root) if args.vcpkg_root else state / "vcpkg"
        if not vcpkg_root.is_absolute():
            vcpkg_root = (root / vcpkg_root).resolve()
        if not is_under_root(vcpkg_root, root):
            die(f"vcpkg root must be under project root: {vcpkg_root}")
        vcpkg_cache = (
            Path(args.vcpkg_cache) if args.vcpkg_cache else vcpkg_root / "bincache"
        )
        if not vcpkg_cache.is_absolute():
            vcpkg_cache = (root / vcpkg_cache).resolve()
        if not is_under_root(vcpkg_cache, root):
            die(f"vcpkg binary cache must be under project root: {vcpkg_cache}")

        vcpkg_cfg = {
            "enabled": True,
            "host_root": str(vcpkg_root),
            "host_binary_cache": str(vcpkg_cache),
            "triplet": args.vcpkg_triplet
            or project_vcpkg.get("triplet")
            or "x64-windows",
            "packages": args.vcpkg_packages or project_vcpkg.get("packages") or [],
        }
    else:
        vcpkg_cfg = {"enabled": False}

    image = args.image or project_cfg.get("image") or DEFAULT_IMAGE

    extra_defaults = _extend_shlex_args(args.cmake_args)
    cfg = {
        "version": 2,
        "image": image,
        "project_root": str(root),
        "state_dir": str(state),
        "build_dir": str(build_dir),
        "generator": args.generator,
        "build_type": args.build_type,
        "profile": args.profile,
        "toolchains": toolchains_map,
        "mounts": mounts,
        "env": env,
        "path_prepend": path_prepend,
        "vcpkg": vcpkg_cfg,
        "cmake_defaults": (args.cmake or []) + extra_defaults,
    }

    ensure_dir(state)
    ensure_dir(build_dir)
    ensure_dir(state / "sccache")
    ensure_dir(state / "wine")
    ensure_dir(state / "home")
    ensure_dir(state / "logs")
    ensure_dir(state / "bin")
    ensure_dir(state / "xdg-runtime")
    (state / "xdg-runtime").chmod(0o700)

    if vcpkg_cfg.get("enabled", False):
        ensure_dir(Path(vcpkg_cfg["host_root"]))
        ensure_dir(Path(vcpkg_cfg["host_binary_cache"]))

    ensure_mt_wrapper(state / "mt-wrapper.sh")

    write_config(build_cfg_path, cfg, args.force)
    print(f"Wrote build config: {build_cfg_path}")


def handle_configure(args: argparse.Namespace) -> None:
    root = repo_root(args.root, args.project_config)
    project_cfg_path = project_config_path(root, args.project_config)
    project_cfg = load_project_config(project_cfg_path)
    build_cfg = load_build_config(build_config_path(root, args.build_config))
    cfg = resolve_effective_config(project_cfg, build_cfg, root, project_cfg_path)

    ensure_mt_wrapper(state_dir(root) / "mt-wrapper.sh")
    ensure_winexe_wrappers(cfg, root)
    ensure_cross_emulator(cfg, root)
    ensure_bin_aliases(cfg, root)
    ensure_wine_runtime(cfg, root, args.verbose)

    if not args.no_vcpkg:
        ensure_vcpkg(cfg, root, args.verbose)

    extra = (args.cmake or []) + _extend_shlex_args(args.cmake_args)
    run_docker(cfg, root, cmake_args(cfg, root, extra), False, args.verbose)


def handle_build(args: argparse.Namespace) -> None:
    root = repo_root(args.root, args.project_config)
    project_cfg_path = project_config_path(root, args.project_config)
    project_cfg = load_project_config(project_cfg_path)
    build_cfg = load_build_config(build_config_path(root, args.build_config))
    cfg = resolve_effective_config(project_cfg, build_cfg, root, project_cfg_path)
    ensure_winexe_wrappers(cfg, root)
    ensure_cross_emulator(cfg, root)
    ensure_bin_aliases(cfg, root)
    ensure_wine_runtime(cfg, root, args.verbose)
    if not args.no_vcpkg:
        ensure_vcpkg(cfg, root, args.verbose)
    extra = (args.build or []) + _extend_shlex_args(args.build_args)
    run_docker(
        cfg, root, build_args(cfg, root, extra, args.build_dir), False, args.verbose
    )


def handle_test(args: argparse.Namespace) -> None:
    root = repo_root(args.root, args.project_config)
    project_cfg_path = project_config_path(root, args.project_config)
    project_cfg = load_project_config(project_cfg_path)
    build_cfg = load_build_config(build_config_path(root, args.build_config))
    cfg = resolve_effective_config(project_cfg, build_cfg, root, project_cfg_path)
    ensure_winexe_wrappers(cfg, root)
    ensure_cross_emulator(cfg, root)
    ensure_bin_aliases(cfg, root)
    ensure_wine_runtime(cfg, root, args.verbose)
    extra = (args.ctest or []) + _extend_shlex_args(args.ctest_args)
    run_docker(
        cfg, root, test_args(cfg, root, extra, args.test_dir), False, args.verbose
    )


def handle_shell(args: argparse.Namespace) -> None:
    root = repo_root(args.root, args.project_config)
    project_cfg_path = project_config_path(root, args.project_config)
    project_cfg = load_project_config(project_cfg_path)
    build_cfg = load_build_config(build_config_path(root, args.build_config))
    cfg = resolve_effective_config(project_cfg, build_cfg, root, project_cfg_path)
    ensure_winexe_wrappers(cfg, root)
    run_shell(cfg, root, args.verbose)


def handle_doctor(args: argparse.Namespace) -> None:
    root = repo_root(args.root, args.project_config)
    project_cfg_path = project_config_path(root, args.project_config)
    raw_project_cfg = load_project_config(project_cfg_path)
    build_cfg = load_build_config(build_config_path(root, args.build_config))
    profile = build_cfg.get("profile") or raw_project_cfg.get("default_profile")
    project_cfg = select_profile(raw_project_cfg, profile)
    doctor(project_cfg, build_cfg, root)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dockerized Windows builds via MSVC+Wine"
    )
    parser.add_argument(
        "--root", help="Project root (defaults to nearest git/CMake root)"
    )
    parser.add_argument(
        "--build-config",
        dest="build_config",
        help="Path to build config (defaults to .wincross/build_config.json)",
    )
    parser.add_argument("--config", dest="build_config", help=argparse.SUPPRESS)
    parser.add_argument(
        "--project-config",
        dest="project_config",
        help=f"Path to project config (default: {PROJECT_CONFIG_FILENAME})",
    )
    parser.add_argument("--verbose", action="store_true", help="Print commands")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize .wincross configuration")
    p_init.add_argument(
        "--force", action="store_true", help="Overwrite existing config"
    )
    p_init.add_argument("--image", help="Docker image tag")
    p_init.add_argument(
        "--build-dir", help="Build directory (default: .wincross/build-windows)"
    )
    p_init.add_argument("--generator", help="CMake generator")
    p_init.add_argument("--build-type", help="CMake build type")
    p_init.add_argument("--profile", help="Project profile name from project config")
    p_init.add_argument(
        "--toolchain",
        action="append",
        help="Toolchain spec name=host[:container[:ro|rw]]",
    )
    p_init.add_argument(
        "--mount", action="append", help="Extra mount host:container[:ro|rw]"
    )
    p_init.add_argument("--env", action="append", help="Environment variable KEY=VALUE")
    p_init.add_argument("--path-prepend", action="append", help="Container PATH prefix")
    p_init.add_argument("--cmake", action="append", help="Default CMake arg")
    p_init.add_argument(
        "--cmake-args", action="append", help="Default CMake args (single string)"
    )
    p_init.add_argument("--vcpkg", action="store_true", help="Enable vcpkg")
    p_init.add_argument(
        "--vcpkg-root", help="vcpkg root directory (default: .wincross/vcpkg)"
    )
    p_init.add_argument(
        "--vcpkg-cache", help="vcpkg binary cache directory (default: <vcpkg>/bincache)"
    )
    p_init.add_argument("--vcpkg-triplet", help="vcpkg triplet")
    p_init.add_argument(
        "--vcpkg-packages", action="append", help="vcpkg packages to install"
    )
    p_init.set_defaults(func=handle_init)

    p_doctor = sub.add_parser("doctor", help="Validate configuration")
    p_doctor.set_defaults(func=handle_doctor)

    p_configure = sub.add_parser("configure", help="Configure the build with CMake")
    p_configure.add_argument(
        "--no-vcpkg", action="store_true", help="Skip vcpkg bootstrap/install"
    )
    p_configure.add_argument("--cmake", action="append", help="Extra CMake args")
    p_configure.add_argument(
        "--cmake-args", action="append", help="Extra CMake args (single string)"
    )
    p_configure.set_defaults(func=handle_configure)

    p_build = sub.add_parser("build", help="Build the project")
    p_build.add_argument(
        "--build-dir",
        help="Override build directory (host path or /work/project/...)",
    )
    p_build.add_argument(
        "--no-vcpkg", action="store_true", help="Skip vcpkg bootstrap/install"
    )
    p_build.add_argument("--build", action="append", help="Extra build args")
    p_build.add_argument(
        "--build-args", action="append", help="Extra build args (single string)"
    )
    p_build.set_defaults(func=handle_build)

    p_test = sub.add_parser("test", help="Run tests")
    p_test.add_argument(
        "--test-dir",
        help="Override build directory for ctest (host path or /work/project/...)",
    )
    p_test.add_argument("--ctest", action="append", help="Extra ctest args")
    p_test.add_argument(
        "--ctest-args", action="append", help="Extra ctest args (single string)"
    )
    p_test.set_defaults(func=handle_test)

    p_shell = sub.add_parser("shell", help="Open an interactive shell in the container")
    p_shell.set_defaults(func=handle_shell)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
