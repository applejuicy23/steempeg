"""Build Steempeg release zips for Windows and/or Linux.

PyInstaller can only freeze for the OS it runs on:
  - Windows zip  → run this on Windows (or ``--platform windows``)
  - Linux zip    → run this on Linux / WSL / SteamOS (or ``--platform linux``)
  - Both from Windows → ``--platform all`` builds Windows locally, then
    invokes the same script inside WSL for Linux.

Usage:
  python newver_compilator.py
  python newver_compilator.py --platform windows
  python newver_compilator.py --platform linux
  python newver_compilator.py --platform all

Engines expected under bin/:
  Windows:  bin/ffmpeg.exe, bin/ffprobe.exe, bin/mpv-2.dll
            (or bin/windows/…)
  Linux:    bin/linux/ffmpeg, bin/linux/ffprobe
            libmpv is harvested automatically on Linux/WSL into
            bin/linux/mpv/ (libmpv.so.2 + relocatable deps) so the zip
            double-clicks on Bazzite/SteamOS without system mpv-libs.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile

VERSION = "39.5"

# PyInstaller --add-data uses OS-specific path separators.
_DATA_SEP = ";" if sys.platform == "win32" else ":"

# Shared libs the host OS must provide (GPU / display / audio / libc).
_SYSTEM_SO_PREFIXES = (
    "linux-vdso",
    "ld-linux",
    "libc.so",
    "libm.so",
    "libdl.so",
    "librt.so",
    "libpthread.so",
    "libresolv.so",
    "libnss_",
    "libstdc++.so",
    "libgcc_s.so",
    "libGL.so",
    "libGLdispatch",
    "libGLX",
    "libOpenGL",
    "libEGL.so",
    "libGLES",
    "libvulkan",
    "libdrm.so",
    "libgbm.so",
    "libX11",
    "libXext",
    "libX",
    "libxcb",
    "libwayland",
    "libxkbcommon",
    "libpulse",
    "libasound",
    "libpipewire",
    "libjack",
    "libsystemd",
    "libdbus",
    "libselinux",
    "libmount",
    "libblkid",
    "libudev",
)


def _repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _platform_tag(target: str) -> str:
    return "windows" if target == "windows" else "linux"


def _dist_name(target: str) -> str:
    return f"Steempeg-{_platform_tag(target)}"


def _zip_name(target: str) -> str:
    return f"Steempeg_v{VERSION}_{_platform_tag(target)}"


def _is_system_so(name: str) -> bool:
    base = os.path.basename(name)
    return any(base.startswith(p) for p in _SYSTEM_SO_PREFIXES)


def _find_system_libmpv() -> str | None:
    candidates = [
        "/usr/lib/x86_64-linux-gnu/libmpv.so.2",
        "/usr/lib64/libmpv.so.2",
        "/usr/lib/libmpv.so.2",
        "/lib/x86_64-linux-gnu/libmpv.so.2",
        "/lib64/libmpv.so.2",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.realpath(path)
    try:
        out = subprocess.check_output(
            ["ldconfig", "-p"], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        if "libmpv.so" not in line or "=>" not in line:
            continue
        path = line.split("=>", 1)[1].strip()
        if os.path.isfile(path):
            return os.path.realpath(path)
    return None


def _ldd_paths(lib_path: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["ldd", lib_path], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    paths: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        m = re.search(r"=>\s+(\S+)\s+\(", line)
        if m:
            p = m.group(1)
            if p.startswith("/") and os.path.isfile(p):
                paths.append(os.path.realpath(p))
            continue
        m = re.match(r"(/\S+)\s+\(", line)
        if m and os.path.isfile(m.group(1)):
            paths.append(os.path.realpath(m.group(1)))
    return paths


def harvest_libmpv_bundle(dest_dir: str) -> int:
    """Copy libmpv + non-system deps into dest_dir. Returns file count."""
    root_lib = _find_system_libmpv()
    if not root_lib:
        print(
            "⚠️  libmpv not found on this machine — "
            "install libmpv1/libmpv-dev (apt) or mpv-libs (rpm) before Linux build."
        )
        return 0

    os.makedirs(dest_dir, exist_ok=True)
    pending = [root_lib]
    seen: set[str] = set()
    copied = 0

    while pending:
        src = pending.pop()
        if src in seen:
            continue
        seen.add(src)
        name = os.path.basename(src)
        if _is_system_so(name) and "libmpv" not in name:
            continue
        dst = os.path.join(dest_dir, name)
        try:
            shutil.copy2(src, dst)
            mode = os.stat(dst).st_mode
            os.chmod(dst, mode | 0o555)
            copied += 1
        except OSError as exc:
            print(f"⚠️  skip {src}: {exc}")
            continue
        for dep in _ldd_paths(src):
            dep_name = os.path.basename(dep)
            if _is_system_so(dep_name):
                continue
            if dep not in seen:
                pending.append(dep)

    # Stable names python-mpv / bootstrap look for.
    real = os.path.join(dest_dir, os.path.basename(root_lib))
    for alias in ("libmpv.so.2", "libmpv.so"):
        link = os.path.join(dest_dir, alias)
        if os.path.lexists(link):
            continue
        try:
            os.symlink(os.path.basename(real), link)
        except OSError:
            try:
                shutil.copy2(real, link)
            except OSError:
                pass

    # Prefer $ORIGIN so dlopen finds sibling deps without LD_LIBRARY_PATH.
    patchelf = shutil.which("patchelf")
    if patchelf:
        for name in os.listdir(dest_dir):
            path = os.path.join(dest_dir, name)
            if not os.path.isfile(path) or ".so" not in name:
                continue
            try:
                subprocess.run(
                    [patchelf, "--set-rpath", "$ORIGIN", path],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass
    else:
        print("ℹ️  patchelf not found — relying on RTLD_GLOBAL preload at runtime")

    print(f"✅ Harvested {copied} libs → {dest_dir} (from {root_lib})")
    return copied


def _engine_sources(target: str) -> list[tuple[str, str]]:
    """(src_path, dest_basename) for engines to copy into dist/.../bin/."""
    root = _repo_root()
    if target == "windows":
        candidates = [
            ("bin/windows/ffmpeg.exe", "ffmpeg.exe"),
            ("bin/windows/ffprobe.exe", "ffprobe.exe"),
            ("bin/windows/mpv-2.dll", "mpv-2.dll"),
            ("bin/ffmpeg.exe", "ffmpeg.exe"),
            ("bin/ffprobe.exe", "ffprobe.exe"),
            ("bin/mpv-2.dll", "mpv-2.dll"),
        ]
    else:
        candidates = [
            ("bin/linux/ffmpeg", "ffmpeg"),
            ("bin/linux/ffprobe", "ffprobe"),
            ("bin/linux/libmpv.so.2", "libmpv.so.2"),
            ("bin/linux/libmpv.so", "libmpv.so"),
            ("bin/ffmpeg", "ffmpeg"),
            ("bin/ffprobe", "ffprobe"),
        ]

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for rel, dest in candidates:
        if dest in seen:
            continue
        src = os.path.join(root, rel.replace("/", os.sep))
        if os.path.isfile(src):
            seen.add(dest)
            out.append((src, dest))
    return out


def _copy_mpv_bundle(bin_dst: str) -> int:
    """Copy harvested bin/linux/mpv/* into dist/.../bin/ (flat)."""
    src_dir = os.path.join(_repo_root(), "bin", "linux", "mpv")
    if not os.path.isdir(src_dir):
        return 0
    n = 0
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src) and not os.path.islink(src):
            continue
        dst = os.path.join(bin_dst, name)
        if os.path.islink(src):
            if os.path.lexists(dst):
                os.remove(dst)
            try:
                os.symlink(os.readlink(src), dst)
            except OSError:
                shutil.copy2(src, dst)
        else:
            shutil.copy2(src, dst)
            try:
                mode = os.stat(dst).st_mode
                os.chmod(dst, mode | 0o555)
            except OSError:
                pass
        n += 1
    if n:
        print(f"✅ libmpv bundle: {n} files → bin/")
    return n


def _write_desktop_launcher(out_dir: str, exe_name: str) -> None:
    """KDE/GNOME: double-click Steempeg.desktop next to the binary."""
    icon = os.path.join(out_dir, "_internal", "assets", "logo.png")
    if not os.path.isfile(icon):
        icon = "logo"
    # %k = path to the .desktop file → run binary from same folder.
    body = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Steempeg\n"
        "Comment=Steam Game Recording clips\n"
        f"Exec=env LC_NUMERIC=C bash -c 'cd \"$(dirname \"%k\")\" && exec \"./{exe_name}\"'\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Player;\n"
        "StartupNotify=true\n"
    )
    path = os.path.join(out_dir, "Steempeg.desktop")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    print("✅ Steempeg.desktop")


def _zip_onedir_unix_exec(zip_base: str, dist_parent: str, folder_name: str) -> str:
    """Zip dist/folder with ELF + .desktop marked executable (Unix attrs).

    Windows Explorer / shutil.make_archive drop +x; Dolphin then refuses
    double-click without a chmod dance.
    """
    zip_path = zip_base if zip_base.endswith(".zip") else zip_base + ".zip"
    root = os.path.join(dist_parent, folder_name)
    if os.path.isfile(zip_path):
        os.remove(zip_path)

    def _unix_attr(path: str) -> int:
        st = os.stat(path, follow_symlinks=False)
        mode = stat.S_IMODE(st.st_mode)
        base = os.path.basename(path)
        # Main binary, desktop launcher, ffmpeg tools
        if (
            base == folder_name
            or base.endswith(".desktop")
            or base in ("ffmpeg", "ffprobe")
            or (mode & 0o111)
        ):
            mode |= 0o755
        else:
            mode |= 0o644
            mode &= ~0o111
        return (0o100000 | mode) << 16

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                full = os.path.join(dirpath, name)
                arc = os.path.relpath(full, dist_parent).replace("\\", "/")
                if os.path.islink(full):
                    # Store symlink target as a regular file copy for portability.
                    target = os.path.realpath(full)
                    if os.path.isfile(target):
                        zi = zipfile.ZipInfo(arc)
                        zi.external_attr = _unix_attr(target)
                        with open(target, "rb") as fh:
                            zf.writestr(zi, fh.read())
                    continue
                zi = zipfile.ZipInfo.from_file(full, arc)
                zi.external_attr = _unix_attr(full)
                with open(full, "rb") as fh:
                    zf.writestr(zi, fh.read())
    return zip_path


def _build_add_data() -> str:
    from steempeg.infra.bundled_assets import BUNDLED_ASSET_FILES

    assets = list(BUNDLED_ASSET_FILES)
    missing = [a for a in assets if not os.path.exists(os.path.join("assets", a))]
    if missing:
        print(f"⚠️  В папке assets/ не хватает: {missing}")

    parts = []
    for name in assets:
        src = os.path.join("assets", name)
        if os.path.exists(src):
            parts.append(f'--add-data "{src}{_DATA_SEP}assets"')
    return " ".join(parts)


def build_native(target: str) -> str:
    """Run PyInstaller for the current OS. Returns path to the zip."""
    host = "windows" if sys.platform == "win32" else "linux"
    if target != host:
        raise SystemExit(
            f"Cannot build target={target!r} on host={host!r}. "
            f"Run this script on {target}, or use --platform all from Windows (WSL)."
        )

    dist_folder = _dist_name(target)
    print(f"1. PyInstaller Steempeg V{VERSION} ({target}) → dist/{dist_folder}/ …")

    if target == "linux":
        mpv_dir = os.path.join(_repo_root(), "bin", "linux", "mpv")
        harvest_libmpv_bundle(mpv_dir)

    add_data = _build_add_data()
    # Clean previous collect for this target so windows/linux don't collide.
    out_dir = os.path.join("dist", dist_folder)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)

    cmd = (
        f'"{sys.executable}" -m PyInstaller -y --noconsole --onedir '
        f'--name "{dist_folder}" '
        f'--distpath dist --workpath build/{dist_folder} '
        "--icon=assets/logo.ico --paths . --hidden-import=av "
        "--hidden-import=steempeg.infra.libmpv_bootstrap "
        f"{add_data} "
        "steempeg/app.py"
    )
    result = subprocess.run(cmd, shell=True, cwd=_repo_root())
    if result.returncode != 0:
        print("❌ PyInstaller упал — сборка прервана (движки/zip не трогаем).")
        sys.exit(1)

    print(f"2. dist/{dist_folder}/bin/ …")
    bin_dst = os.path.join(out_dir, "bin")
    os.makedirs(bin_dst, exist_ok=True)

    engines = _engine_sources(target)
    if not engines and target == "windows":
        print(
            "⚠️  Движки не найдены в bin/ — zip соберётся, "
            "на машине нужны system ffmpeg/ffprobe."
        )
    for src, dest in engines:
        shutil.copy2(src, os.path.join(bin_dst, dest))
        if target == "linux":
            try:
                mode = os.stat(os.path.join(bin_dst, dest)).st_mode
                os.chmod(os.path.join(bin_dst, dest), mode | 0o111)
            except OSError:
                pass
        print(f"✅ {dest} -> bin/")

    if target == "linux":
        n = _copy_mpv_bundle(bin_dst)
        if n == 0:
            print(
                "⚠️  Нет bundled libmpv — на целевой машине нужен system libmpv.so.2. "
                "На WSL: sudo apt install libmpv1 libmpv-dev"
            )
        exe_path = os.path.join(out_dir, dist_folder)
        if os.path.isfile(exe_path):
            try:
                os.chmod(exe_path, os.stat(exe_path).st_mode | 0o755)
            except OSError:
                pass
        _write_desktop_launcher(out_dir, dist_folder)

    print("3. ZIP…")
    zip_base = _zip_name(target)
    if target == "linux":
        archive = _zip_onedir_unix_exec(zip_base, "dist", dist_folder)
    else:
        archive = shutil.make_archive(zip_base, "zip", "dist", dist_folder)
    print(f"🎉 ГОТОВО! {os.path.basename(archive)}")
    return archive


def build_linux_via_wsl() -> str:
    """From Windows, run the Linux build inside the default WSL distro."""
    if sys.platform != "win32":
        raise SystemExit("WSL helper is only for Windows hosts.")

    root = _repo_root()
    drive, rest = os.path.splitdrive(root)
    wsl_path = "/mnt/" + drive.rstrip(":\\/").lower() + rest.replace("\\", "/")

    print("—— Linux build via WSL ——")
    print(f"   path: {wsl_path}")
    print("   (ставит pip/PyInstaller в .venv-linux при необходимости)")

    # Ensure apt pip + venv, then build with a dedicated venv so we don't
    # fight the system python (Ubuntu often has no ensurepip / no pip).
    inner = f"""
set -e
cd '{wsl_path}'
if ! command -v python3 >/dev/null; then
  echo 'python3 missing in WSL'
  exit 1
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo 'Installing python3-pip (sudo)…'
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-pip python3-venv python3-dev
fi
if [ ! -d .venv-linux ]; then
  python3 -m venv .venv-linux
fi
. .venv-linux/bin/activate
pip install -q -U pip wheel
pip install -q pyinstaller 'PySide6' av psutil requests
# libmpv + headers so we can harvest .so into the zip (Bazzite has no libmpv.so)
sudo apt-get install -y -qq libmpv1 libmpv-dev ffmpeg patchelf 2>/dev/null || true
pip install -q python-mpv || echo '⚠️  python-mpv skipped — install libmpv and retry'
python newver_compilator.py --platform linux
"""
    result = subprocess.run(["wsl", "-e", "bash", "-lc", inner], cwd=root)
    if result.returncode != 0:
        print("❌ Linux build in WSL failed.")
        print("   Проверь: wsl работает, есть sudo/пароль для apt.")
        sys.exit(result.returncode or 1)
    zip_path = os.path.join(root, f"{_zip_name('linux')}.zip")
    if not os.path.isfile(zip_path):
        print(f"⚠️  Expected zip missing: {zip_path}")
    else:
        print(f"🎉 Linux zip: {os.path.basename(zip_path)}")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Steempeg Windows/Linux zips")
    parser.add_argument(
        "--platform",
        choices=("windows", "linux", "all", "host"),
        default="host",
        help="windows | linux | all (Win+WSL) | host (default: this OS only)",
    )
    args = parser.parse_args()

    os.chdir(_repo_root())
    # Ensure imports like steempeg.* resolve when launched as a script.
    if _repo_root() not in sys.path:
        sys.path.insert(0, _repo_root())

    host = "windows" if sys.platform == "win32" else "linux"
    target = host if args.platform == "host" else args.platform

    if target == "all":
        print(f"=== Building BOTH (host={host}) ===")
        build_native("windows" if host == "windows" else "linux")
        if host == "windows":
            build_linux_via_wsl()
        else:
            print(
                "На Linux --platform all собирает только linux. "
                "Windows-zip собери на Windows-машине."
            )
        return

    if target == "linux" and host == "windows":
        build_linux_via_wsl()
        return
    if target == "windows" and host == "linux":
        raise SystemExit(
            "Cannot build Windows zip on Linux. Run newver_compilator.py on Windows."
        )

    build_native(target)


if __name__ == "__main__":
    main()
