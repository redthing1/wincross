import os
import subprocess
from pathlib import Path

from .constants import DEFAULT_CONTAINER_ROOT, STATE_DIRNAME
from .util import dedupe_preserve_order, die, to_container_path


def docker_cmd_base(cfg: dict, root: Path, interactive: bool) -> list[str]:
    cmd = ["docker", "run", "--rm"]
    if interactive:
        cmd.append("-it")
    cmd += ["-u", f"{os.getuid()}:{os.getgid()}"]

    project_root = Path(cfg["project_root"]).resolve()
    if project_root != root:
        die(
            f"config project_root does not match current root: {project_root} != {root}"
        )

    cmd += ["-v", f"{project_root}:{DEFAULT_CONTAINER_ROOT}"]

    for name, tool in (cfg.get("toolchains", {}) or {}).items():
        if not tool.get("host_path") or not tool.get("container_path"):
            die(f"toolchain '{name}' is missing host_path or container_path")
        mode = "ro" if tool.get("read_only", False) else "rw"
        cmd += ["-v", f"{tool['host_path']}:{tool['container_path']}:{mode}"]

    for mount in cfg.get("mounts", []):
        mode = "ro" if mount.get("read_only", False) else "rw"
        cmd += ["-v", f"{mount['host_path']}:{mount['container_path']}:{mode}"]

    state_host = Path(cfg.get("state_dir", "")).resolve()
    container_state = to_container_path(state_host, root, DEFAULT_CONTAINER_ROOT)
    container_home = f"{container_state}/home"
    container_wine = f"{container_state}/wine"
    container_sccache = f"{container_state}/sccache"
    container_mt = f"{container_state}/mt-wrapper.sh"
    container_xdg = f"{container_state}/xdg-runtime"

    xdg_host = state_host / "xdg-runtime"
    xdg_host.mkdir(parents=True, exist_ok=True)

    env = {
        "HOME": container_home,
        "XDG_RUNTIME_DIR": container_xdg,
        "WINEPREFIX": container_wine,
        "WINEDEBUG": "-all",
        "SCCACHE_DIR": container_sccache,
        "CMAKE_MT": container_mt,
        "WINCROSS_STATE_DIR": container_state,
        "WINCROSS_EMULATOR": f"{container_state}/bin/wincross-emulator",
    }

    path_prepend = list(cfg.get("path_prepend", []))
    path_prepend += ["/opt/msvc/bin/x64", "/opt/msvc/bin"]
    for tool in (cfg.get("toolchains", {}) or {}).values():
        for entry in tool.get("path_prepend", []) or []:
            path_prepend.append(entry)
    path_prepend = dedupe_preserve_order(path_prepend)
    base_path = "/usr/local/bin:/usr/bin:/bin"
    env["PATH"] = ":".join(path_prepend + [base_path])

    if cfg.get("vcpkg", {}).get("enabled", False):
        vcpkg = cfg["vcpkg"]
        env.update(
            {
                "VCPKG_ROOT": vcpkg["container_root"],
                "VCPKG_TARGET_TRIPLET": vcpkg.get("triplet", "x64-windows"),
                "VCPKG_DEFAULT_BINARY_CACHE": vcpkg["container_binary_cache"],
                "VCPKG_BINARY_SOURCES": f"clear;files,{vcpkg['container_binary_cache']},readwrite",
            }
        )
        overlay_triplets = vcpkg.get("overlay_triplets", [])
        if overlay_triplets:
            env["VCPKG_OVERLAY_TRIPLETS"] = ";".join(overlay_triplets)

    for key, value in cfg.get("env", {}).items():
        env[key] = value

    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]

    cmd += ["-w", DEFAULT_CONTAINER_ROOT]
    cmd.append(cfg["image"])
    return cmd


def run_docker(
    cfg: dict, root: Path, command: list[str], interactive: bool, verbose: bool
) -> None:
    cmd = docker_cmd_base(cfg, root, interactive)
    cmd += command
    if verbose:
        print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def run_shell(cfg: dict, root: Path, verbose: bool) -> None:
    run_docker(cfg, root, ["bash", "--noprofile", "--norc"], True, verbose)
