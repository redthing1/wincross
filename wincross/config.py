import json
import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python < 3.11
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None

from .constants import (
    BUILD_CONFIG_FILENAME,
    DEFAULT_BUILD_TYPE,
    DEFAULT_CONTAINER_ROOT,
    DEFAULT_GENERATOR,
    DEFAULT_IMAGE,
    PROJECT_CONFIG_FILENAME,
    STATE_DIRNAME,
)
from .util import (
    die,
    merge_env,
    merge_lists,
    merge_toolchains,
    state_dir,
    to_container_path,
)
from .wrappers import normalize_winexe_wrappers, merge_winexe_wrappers


ROOT_MARKERS = (".git", "CMakeLists.txt", "pyproject.toml")


def _find_root(start: Path) -> Path | None:
    for parent in (start, *start.parents):
        for marker in ROOT_MARKERS:
            if (parent / marker).exists():
                return parent
    return None


def repo_root(explicit_root: str | None, project_config: str | None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.getenv("WINCROSS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    candidate_cfg = project_config or os.getenv("WINCROSS_PROJECT_CONFIG")
    if candidate_cfg:
        start = Path(candidate_cfg)
        if not start.is_absolute():
            start = (Path.cwd() / start).resolve()
        if start.is_file():
            start = start.parent
        found = _find_root(start)
        if found:
            return found
    found = _find_root(Path.cwd().resolve())
    if found:
        return found
    die("unable to locate project root (use --root or set WINCROSS_ROOT)")


def build_config_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return state_dir(root) / BUILD_CONFIG_FILENAME


def project_config_path(root: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env_cfg = os.getenv("WINCROSS_PROJECT_CONFIG")
    if env_cfg:
        return Path(env_cfg).resolve()
    return root / PROJECT_CONFIG_FILENAME


def load_build_config(path: Path) -> dict:
    if not path.exists():
        die(f"missing config: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"invalid config json: {exc}")


def load_project_config(path: Path) -> dict:
    if not path.exists():
        return {}
    if tomllib is None:
        die("TOML support requires Python 3.11+ or the 'tomli' module")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # tomllib raises ValueError on parse failures
        die(f"invalid project config toml: {exc}")


def write_config(path: Path, data: dict, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        die(f"config already exists: {path} (use --force to overwrite)")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_project_config(cfg: dict) -> dict:
    data = dict(cfg or {})
    cmake = data.get("cmake")
    if isinstance(cmake, dict):
        if "defaults" in cmake and "cmake_defaults" not in data:
            data["cmake_defaults"] = cmake["defaults"]
        if "generator" in cmake and "generator" not in data:
            data["generator"] = cmake["generator"]
        if "build_type" in cmake and "build_type" not in data:
            data["build_type"] = cmake["build_type"]
        if "build_dir" in cmake and "build_dir" not in data:
            data["build_dir"] = cmake["build_dir"]
    wincross = data.get("wincross")
    if isinstance(wincross, dict):
        if "winexe_wrappers" in wincross and "winexe_wrappers" not in data:
            data["winexe_wrappers"] = wincross["winexe_wrappers"]
        if "winepath_prepend" in wincross and "winepath_prepend" not in data:
            data["winepath_prepend"] = wincross["winepath_prepend"]
        if "bin_aliases" in wincross and "bin_aliases" not in data:
            data["bin_aliases"] = wincross["bin_aliases"]
        if "emulator_env" in wincross and "emulator_env" not in data:
            data["emulator_env"] = wincross["emulator_env"]
    path_cfg = data.get("path")
    if isinstance(path_cfg, dict):
        if "prepend" in path_cfg and "path_prepend" not in data:
            data["path_prepend"] = path_cfg["prepend"]
    return data


def select_profile(project_cfg: dict, profile: str | None) -> dict:
    base = normalize_project_config(project_cfg or {})
    profiles = base.pop("profiles", {}) or {}
    if not profile:
        return base
    override = profiles.get(profile, {})
    if not isinstance(override, dict):
        die(f"invalid profile '{profile}' in project config")
    override = normalize_project_config(override)
    merged = dict(base)
    for key, value in override.items():
        if key in ("cmake_defaults", "path_prepend"):
            merged[key] = merge_lists(merged.get(key, []), value)
        elif key == "winexe_wrappers":
            merged[key] = merge_lists(merged.get(key, []), value)
        elif key == "env":
            merged[key] = merge_env(merged.get(key, {}), value)
        elif key == "toolchains":
            merged[key] = merge_toolchains(merged.get(key, {}), value)
        elif key == "vcpkg" and isinstance(value, dict):
            merged[key] = {**(merged.get(key, {}) or {}), **value}
        else:
            merged[key] = value
    return merged


def validate_project_config(cfg: dict) -> None:
    toolchains = cfg.get("toolchains", {}) or {}
    if not isinstance(toolchains, dict):
        die("project config toolchains must be a table")
    for name, tc in toolchains.items():
        if "host_path" in tc:
            die(f"project config toolchain '{name}' must not set host_path")
    normalize_winexe_wrappers(cfg.get("winexe_wrappers"), context="project config")
    winepath = cfg.get("winepath_prepend", [])
    if winepath is not None and not isinstance(winepath, list):
        die("project config winepath_prepend must be a list")
    for entry in winepath or []:
        if not isinstance(entry, str) or not entry:
            die("project config winepath_prepend entries must be non-empty strings")
    aliases = cfg.get("bin_aliases", [])
    if aliases is not None and not isinstance(aliases, list):
        die("project config bin_aliases must be a list")
    for entry in aliases or []:
        if not isinstance(entry, str) or not entry:
            die("project config bin_aliases entries must be non-empty strings")
    emulator_env = cfg.get("emulator_env", {})
    if emulator_env is not None and not isinstance(emulator_env, dict):
        die("project config emulator_env must be a table")
    for key, value in (emulator_env or {}).items():
        if not isinstance(key, str) or not key:
            die("project config emulator_env keys must be non-empty strings")
        if not isinstance(value, str) or value == "":
            die(f"project config emulator_env '{key}' must be a non-empty string")
    vcpkg = cfg.get("vcpkg", {}) or {}
    for key in (
        "host_root",
        "host_binary_cache",
        "container_root",
        "container_binary_cache",
    ):
        if key in vcpkg:
            die(f"project config must not set vcpkg {key}")
    if "fixup_z3_dll" in vcpkg and not isinstance(vcpkg["fixup_z3_dll"], bool):
        die("project config vcpkg.fixup_z3_dll must be true/false")


def _expand_template(value: str, mapping: dict, context: str) -> str:
    try:
        return value.format(**mapping)
    except KeyError as exc:
        die(f"unknown placeholder '{exc.args[0]}' in {context}: {value}")


def _expand_list(values: list[str] | None, mapping: dict, context: str) -> list[str]:
    if not values:
        return []
    expanded: list[str] = []
    for value in values:
        if not isinstance(value, str) or value == "":
            die(f"{context} entries must be non-empty strings")
        expanded.append(_expand_template(value, mapping, context))
    return expanded


def _expand_dict_values(values: dict | None, mapping: dict, context: str) -> dict:
    if not values:
        return {}
    expanded: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(value, str) or value == "":
            die(f"{context} values must be non-empty strings")
        expanded[key] = _expand_template(value, mapping, context)
    return expanded


def _expand_effective_config(cfg: dict, mapping: dict) -> None:
    cfg["path_prepend"] = _expand_list(
        cfg.get("path_prepend"), mapping, "path_prepend"
    )
    cfg["cmake_defaults"] = _expand_list(
        cfg.get("cmake_defaults"), mapping, "cmake_defaults"
    )
    cfg["winepath_prepend"] = _expand_list(
        cfg.get("winepath_prepend"), mapping, "winepath_prepend"
    )
    cfg["env"] = _expand_dict_values(cfg.get("env"), mapping, "env")
    cfg["emulator_env"] = _expand_dict_values(
        cfg.get("emulator_env"), mapping, "emulator_env"
    )
    vcpkg = cfg.get("vcpkg", {}) or {}
    if "overlay_triplets" in vcpkg:
        vcpkg["overlay_triplets"] = _expand_list(
            vcpkg.get("overlay_triplets"), mapping, "vcpkg.overlay_triplets"
        )
    cfg["vcpkg"] = vcpkg


def resolve_effective_config(
    project_cfg: dict, build_cfg: dict, root: Path, project_cfg_path: Path
) -> dict:
    profile = build_cfg.get("profile") or project_cfg.get("default_profile")
    project_cfg = select_profile(project_cfg, profile)
    validate_project_config(project_cfg)

    toolchains = merge_toolchains(
        project_cfg.get("toolchains", {}), build_cfg.get("toolchains", {})
    )

    cmake_defaults = merge_lists(
        project_cfg.get("cmake_defaults", []), build_cfg.get("cmake_defaults", [])
    )
    path_prepend = merge_lists(
        project_cfg.get("path_prepend", []), build_cfg.get("path_prepend", [])
    )
    env = merge_env(project_cfg.get("env", {}), build_cfg.get("env", {}))
    emulator_env = merge_env(
        project_cfg.get("emulator_env", {}), build_cfg.get("emulator_env", {})
    )
    winepath_prepend = merge_lists(
        project_cfg.get("winepath_prepend", []), build_cfg.get("winepath_prepend", [])
    )
    bin_aliases = merge_lists(
        project_cfg.get("bin_aliases", []), build_cfg.get("bin_aliases", [])
    )
    winexe_project = normalize_winexe_wrappers(
        project_cfg.get("winexe_wrappers"), context="project config"
    )
    winexe_build = normalize_winexe_wrappers(
        build_cfg.get("winexe_wrappers"), context="build config"
    )
    winexe_wrappers = merge_winexe_wrappers(winexe_project, winexe_build)

    if winexe_wrappers:
        wrapper_dir = f"{DEFAULT_CONTAINER_ROOT}/{STATE_DIRNAME}/bin"
        if wrapper_dir in path_prepend:
            path_prepend = [wrapper_dir] + [p for p in path_prepend if p != wrapper_dir]
        else:
            path_prepend = [wrapper_dir] + path_prepend

    vcpkg_project = project_cfg.get("vcpkg", {}) or {}
    vcpkg_build = build_cfg.get("vcpkg", {}) or {}
    vcpkg_enabled = vcpkg_build.get("enabled", vcpkg_project.get("enabled", False))

    build_dir = build_cfg.get("build_dir") or project_cfg.get("build_dir")
    if not build_dir:
        build_dir = str(state_dir(root) / "build-windows")
    build_dir_path = Path(build_dir)
    if not build_dir_path.is_absolute():
        build_dir_path = (root / build_dir_path).resolve()

    image = build_cfg.get("image") or project_cfg.get("image") or DEFAULT_IMAGE

    generator = (
        build_cfg.get("generator") or project_cfg.get("generator") or DEFAULT_GENERATOR
    )
    build_type = (
        build_cfg.get("build_type")
        or project_cfg.get("build_type")
        or DEFAULT_BUILD_TYPE
    )

    vcpkg_cfg = {
        "enabled": bool(vcpkg_enabled),
        "triplet": vcpkg_build.get("triplet")
        or vcpkg_project.get("triplet")
        or "x64-windows",
        "packages": vcpkg_build.get("packages") or vcpkg_project.get("packages") or [],
        "overlay_triplets": vcpkg_build.get("overlay_triplets")
        or vcpkg_project.get("overlay_triplets")
        or [],
        "fixup_z3_dll": vcpkg_build.get(
            "fixup_z3_dll", vcpkg_project.get("fixup_z3_dll", False)
        ),
    }

    if vcpkg_cfg["enabled"]:
        host_root = vcpkg_build.get("host_root")
        host_cache = vcpkg_build.get("host_binary_cache")
        if not host_root or not host_cache:
            die(
                "vcpkg enabled but host_root or host_binary_cache is missing in build config"
            )
        vcpkg_cfg["host_root"] = host_root
        vcpkg_cfg["host_binary_cache"] = host_cache
        vcpkg_cfg["container_root"] = to_container_path(
            Path(host_root), root, DEFAULT_CONTAINER_ROOT
        )
        vcpkg_cfg["container_binary_cache"] = to_container_path(
            Path(host_cache), root, DEFAULT_CONTAINER_ROOT
        )

    config_dir = to_container_path(
        project_cfg_path.parent.resolve(), root, DEFAULT_CONTAINER_ROOT
    )

    effective = {
        "version": build_cfg.get("version", 1),
        "image": image,
        "project_root": build_cfg.get("project_root", str(root)),
        "state_dir": build_cfg.get("state_dir", str(state_dir(root))),
        "build_dir": str(build_dir_path),
        "generator": generator,
        "build_type": build_type,
        "config_dir": config_dir,
        "toolchains": toolchains,
        "mounts": build_cfg.get("mounts", []),
        "env": env,
        "emulator_env": emulator_env,
        "path_prepend": path_prepend,
        "vcpkg": vcpkg_cfg,
        "cmake_defaults": cmake_defaults,
        "winexe_wrappers": winexe_wrappers,
        "winepath_prepend": winepath_prepend,
        "bin_aliases": bin_aliases,
    }
    mapping = {
        "project_root": DEFAULT_CONTAINER_ROOT,
        "state_dir": to_container_path(Path(effective["state_dir"]), root, DEFAULT_CONTAINER_ROOT),
        "build_dir": to_container_path(build_dir_path, root, DEFAULT_CONTAINER_ROOT),
        "config_dir": config_dir,
    }
    _expand_effective_config(effective, mapping)
    return effective
