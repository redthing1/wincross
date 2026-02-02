from pathlib import Path
import shutil

from .docker import run_docker
from .util import ensure_dir


def ensure_vcpkg(cfg: dict, root: Path, verbose: bool) -> None:
    vcpkg = cfg.get("vcpkg", {})
    if not vcpkg.get("enabled", False):
        return
    script = (
        "set -e\n"
        "if command -v clang >/dev/null 2>&1; then\n"
        "  if [ -z \"${CC:-}\" ]; then\n"
        "    export CC=clang\n"
        "  fi\n"
        "  if [ -z \"${CXX:-}\" ]; then\n"
        "    export CXX=clang++\n"
        "  fi\n"
        "fi\n"
        'if [ ! -d "$VCPKG_ROOT/.git" ]; then\n'
        '  if [ -d "$VCPKG_ROOT" ]; then\n'
        "    keep_cache=0\n"
        '    if [ -d "$VCPKG_ROOT/bincache" ]; then\n'
        "      keep_cache=1\n"
        "    fi\n"
        "    non_cache=$(ls -A \"$VCPKG_ROOT\" | grep -v '^bincache$' || true)\n"
        '    if [ -n "$non_cache" ]; then\n'
        "      echo 'vcpkg root exists but is not a git repo' >&2\n"
        "      exit 1\n"
        "    fi\n"
        '    if [ "$keep_cache" -eq 1 ]; then\n'
        '      mv "$VCPKG_ROOT/bincache" /tmp/wincross-vcpkg-bincache\n'
        "    fi\n"
        '    rmdir "$VCPKG_ROOT"\n'
        "  fi\n"
        '  git clone https://github.com/microsoft/vcpkg "$VCPKG_ROOT"\n'
        "  if [ -d /tmp/wincross-vcpkg-bincache ]; then\n"
        '    mv /tmp/wincross-vcpkg-bincache "$VCPKG_ROOT/bincache"\n'
        "  fi\n"
        "fi\n"
        'if [ ! -x "$VCPKG_ROOT/vcpkg" ]; then\n'
        '  "$VCPKG_ROOT/bootstrap-vcpkg.sh"\n'
        "fi\n"
        'if [ -n "$VCPKG_DEFAULT_BINARY_CACHE" ]; then\n'
        '  mkdir -p "$VCPKG_DEFAULT_BINARY_CACHE"\n'
        "fi\n"
    )
    packages = vcpkg.get("packages", [])
    if packages:
        pkgs = " ".join(f"{p}:{vcpkg.get('triplet', 'x64-windows')}" for p in packages)
        script += f'"$VCPKG_ROOT/vcpkg" install {pkgs}\n'
    run_docker(cfg, root, ["bash", "-lc", script], False, verbose)
    if vcpkg.get("fixup_z3_dll", False):
        fix_vcpkg_z3_dll(vcpkg)


def fix_vcpkg_z3_dll(vcpkg: dict) -> None:
    triplet = vcpkg.get("triplet")
    host_root = vcpkg.get("host_root")
    if not triplet or not host_root:
        return
    src = Path(host_root) / "installed" / triplet / "bin" / "libz3.dll"
    dst = Path(host_root) / "installed" / triplet / "tools" / "z3" / "libz3.dll"
    if not src.exists() or dst.exists():
        return
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
