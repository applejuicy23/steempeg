"""Apply a downloaded update on disk (replaces updater.bat file moves)."""
from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
import tempfile
import zipfile

# Top-level install folders that must survive updates / restores.
# User data: exports, screenshots, marker prefs / clip_markers (under cache/).
_PRESERVE_DIRS = frozenset(
    {
        "logs",
        "cache",
        "_update_extracted",
        "rendered_videos",
        "Screenshots",
    }
)
_CREATE_NO_WINDOW = 0x08000000
_LAUNCHER_NAMES = (
    "Steempeg",
    "Steempeg.sh",
    "Steempeg-linux",
    "Steempeg-steamdeck",
)
def resolve_extract_source(extract_root: str) -> str:
    items = os.listdir(extract_root)
    if len(items) == 1 and os.path.isdir(os.path.join(extract_root, items[0])):
        return os.path.join(extract_root, items[0])
    return extract_root


def find_app_executable(directory: str) -> str:
    """Pick the launcher to exec after install (Windows .exe or Linux shell)."""
    try:
        names = os.listdir(directory)
    except OSError:
        names = []
    lower_map = {n.lower(): n for n in names}
    preferred = (
        "Steempeg-linux",
        "Steempeg-steamdeck",
        "Steempeg.sh",
        "Steempeg",
        "Steempeg.exe",
        "Steempeg-windows.exe",
    )
    for pref in preferred:
        hit = lower_map.get(pref.lower())
        if hit:
            return hit
    for name in names:
        lower = name.lower()
        if name.endswith(".exe") and "ffmpeg" not in lower and "ffprobe" not in lower:
            return name
    return "Steempeg.exe" if sys.platform == "win32" else "Steempeg-linux"


def restore_zip_unix_modes(archive: zipfile.ZipFile, extract_root: str) -> int:
    """Re-apply Unix modes from zip central-directory entries.

    CPython 3.14+ dropped ``chmod`` from ``ZipFile.extract`` / ``extractall``.
    Portable Linux packs need those bits for ``venv/bin/python``, ffmpeg, and
    shell launchers — without them the post-update relaunch gets Permission denied.
    """
    if sys.platform == "win32" or not hasattr(os, "chmod"):
        return 0
    root = os.path.normpath(extract_root)
    root_prefix = root + os.sep
    fixed = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        mode = (info.external_attr >> 16) & 0o7777
        if not mode:
            continue
        # Prefer Unix-marked entries; still honor explicit +x from other creators.
        if info.create_system != 3 and not (mode & 0o111):
            continue
        rel = info.filename.replace("/", os.sep)
        path = os.path.normpath(os.path.join(root, rel))
        if path != root and not path.startswith(root_prefix):
            continue
        if not os.path.isfile(path):
            continue
        try:
            os.chmod(path, mode)
            fixed += 1
        except OSError:
            pass
    if fixed:
        logging.info("UPDATE_INSTALL: restored unix modes on %s extracted files", fixed)
    return fixed


def ensure_portable_executables(root: str) -> None:
    """Belt-and-suspenders +x for portable Linux/Steam Deck layouts."""
    if sys.platform == "win32" or not hasattr(os, "chmod"):
        return

    def _mark(path: str) -> None:
        try:
            if os.path.isfile(path):
                mode = os.stat(path).st_mode
                if not (mode & stat.S_IXUSR):
                    os.chmod(path, mode | 0o755)
        except OSError:
            pass

    for name in _LAUNCHER_NAMES:
        _mark(os.path.join(root, name))
    for name in ("ffmpeg", "ffprobe"):
        _mark(os.path.join(root, "bin", name))

    for rel in ("venv/bin", "bin"):
        base = os.path.join(root, rel)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for filename in files:
                _mark(os.path.join(dirpath, filename))


def _bat_preserve_dir_guards(var: str = "%%D") -> str:
    """Chain of ``if /I not …`` so cmd.exe leaves user-data folders alone."""
    parts = [f'if /I not "{var}"=="{name}"' for name in sorted(_PRESERVE_DIRS)]
    return " ".join(parts)


def _bat_path(path: str) -> str:
    """Escape a path for embedding in a generated .bat file."""
    return os.path.normpath(path).replace("%", "%%")


def _bat_install_relative_path(path: str, exe_dir: str) -> str:
    """Turns a path inside the install folder into a relative, escaped .bat path.

    cmd.exe reads .bat files in the OEM code page, so absolute paths with
    non-ASCII characters (a Cyrillic user name) arrive garbled. The script runs
    with the install folder as its working directory, so relative paths that
    only contain our own ASCII folder names stay intact.
    """
    try:
        rel = os.path.relpath(path, exe_dir)
    except ValueError:
        return _bat_path(path)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return _bat_path(path)
    return _bat_path(rel)


# Inno Setup's uninstaller lives in the install folder; updates must not move it away.
_BAT_UNINSTALLER_GUARD = (
    'if /I not "%%I"=="unins000.exe" '
    'if /I not "%%I"=="unins000.dat" '
    'if /I not "%%I"=="unins000.msg" '
)


def _sh_quote(path: str) -> str:
    return "'" + path.replace("'", "'\"'\"'") + "'"


def _bat_require_install_folder(abort_label: str) -> str:
    """Cmd lines that jump to abort_label unless the working directory is named Steempeg.

    The update moves or deletes every other file in that directory. A portable
    zip extracted into Downloads must not be treated as an install folder.
    A drive root fails the name check as well.
    """
    return (
        'for %%I in ("%CD%") do set "STEEMPEG_FOLDER=%%~nxI"\n'
        f'if /I not "%STEEMPEG_FOLDER%"=="Steempeg" goto {abort_label}\n'
    )


def _sh_require_install_folder(relaunch_name: str) -> str:
    """Bash lines that stop unless the working directory is named Steempeg.

    On refusal the log goes to the temp directory, not into the user's folder,
    and the existing launcher is started again.
    """
    relaunch = (relaunch_name or "").replace('"', "")
    return f"""folder=$(basename "$PWD" | tr '[:upper:]' '[:lower:]')
if [[ "$folder" != "steempeg" ]]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refused: install folder is not named Steempeg ($PWD)" >> "${{TMPDIR:-/tmp}}/steempeg_update_install.log"
  if [[ -n "{relaunch}" && -e "./{relaunch}" ]]; then
    exec "./{relaunch}"
  fi
  exit 1
fi
"""


def write_deferred_install_bat(
    *,
    handler_pid: int,
    exe_dir: str,
    source_dir: str,
    extract_root: str,
    keep_backup: bool,
    from_version: str,
    new_exe_name: str,
    tmp_asset_name: str | None = None,
) -> str:
    """Write a temp .bat that waits for the handler to exit, then swaps files.

    The handler process loads PyInstaller extensions from exe_dir, so in-place
    install must run only after that process has fully terminated.
    """
    backup_folder = f"old_version_v{from_version}" if keep_backup else ""
    tmp_guard = f'if /I not "%%I"=="{tmp_asset_name}.tmp" ' if tmp_asset_name else ""
    bat_path = os.path.join(tempfile.gettempdir(), f"steempeg_install_{handler_pid}.bat")

    dir_guards = _bat_preserve_dir_guards("%%D")
    file_guards = f"{tmp_guard}{_BAT_UNINSTALLER_GUARD}"
    source_rel = _bat_install_relative_path(source_dir, exe_dir)
    extract_rel = _bat_install_relative_path(extract_root, exe_dir)
    if keep_backup:
        remove_block = f"""if exist "{backup_folder}" rd /S /Q "{backup_folder}"
mkdir "{backup_folder}"
for %%I in (*.*) do (
    {file_guards}move "%%I" "{backup_folder}\\" > NUL 2>&1
)
for /D %%D in (*) do (
    {dir_guards} if /I not "%%D"=="{backup_folder}" (
        echo %%D| findstr /I /B /C:"old_version_v" /C:"pre_restore_v" > NUL
        if errorlevel 1 (
            if exist "%%D" move "%%D" "{backup_folder}\\" > NUL 2>&1
        )
    )
)"""
    else:
        remove_block = f"""for %%I in (*.*) do (
    {file_guards}del /F /Q "%%I" > NUL 2>&1
)
for /D %%D in (*) do (
    {dir_guards} (
        echo %%D| findstr /I /B /C:"old_version_v" /C:"pre_restore_v" > NUL
        if errorlevel 1 (
            if exist "%%D" rd /S /Q "%%D" > NUL 2>&1
        )
    )
)"""

    backup_arg = backup_folder if keep_backup else "None"
    tmp_cleanup = (
        f'if exist "{tmp_asset_name}.tmp" del /F /Q "{tmp_asset_name}.tmp" > NUL 2>&1'
        if tmp_asset_name
        else ""
    )
    # The working directory is the install folder (set by spawn_deferred_install);
    # every path below is relative to it.
    bat_content = f"""@echo off
title Steempeg Update

:wait_loop
tasklist /FI "PID eq {handler_pid}" 2>NUL | find "{handler_pid}" >NUL
if errorlevel 1 goto do_install
timeout /t 1 /nobreak >NUL
goto wait_loop

:do_install
{_bat_require_install_folder("abort_folder")}if not exist "{source_rel}\\{new_exe_name}" goto abort
{remove_block}
robocopy "{source_rel}" "." /E /IS /IT /R:5 /W:2 /NFL /NDL /NJH /NJS /NC /NS /NP > NUL
if errorlevel 8 (
    if not exist "logs" mkdir "logs"
    >> "logs\\update_install.log" echo %DATE% %TIME% robocopy failed with code %ERRORLEVEL%
)
if exist "{extract_rel}" rd /S /Q "{extract_rel}"
{tmp_cleanup}
start "" "{new_exe_name}" --updated-from {from_version} --backup-folder {backup_arg}
del "%~f0"
exit /b

:abort_folder
>> "%TEMP%\\steempeg_update_install.log" echo %DATE% %TIME% update aborted: folder is not named Steempeg (%CD%)
if exist "{new_exe_name}" start "" "{new_exe_name}"
del "%~f0"
exit /b

:abort
if not exist "logs" mkdir "logs"
>> "logs\\update_install.log" echo %DATE% %TIME% update aborted: "{source_rel}\\{new_exe_name}" not found in %CD%
if exist "{new_exe_name}" start "" "{new_exe_name}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as handle:
        handle.write(bat_content)
    logging.info("UPDATE_INSTALL: deferred install script %s", bat_path)
    return bat_path


def write_deferred_install_sh(
    *,
    handler_pid: int,
    exe_dir: str,
    source_dir: str,
    extract_root: str,
    keep_backup: bool,
    from_version: str,
    new_exe_name: str,
    tmp_asset_name: str | None = None,
) -> str:
    """Linux/macOS: wait for handler exit, swap files, relaunch shell launcher."""
    backup_folder = f"old_version_v{from_version}" if keep_backup else ""
    backup_arg = backup_folder if keep_backup else "None"
    sh_path = os.path.join(tempfile.gettempdir(), f"steempeg_install_{handler_pid}.sh")
    preserve = set(_PRESERVE_DIRS)
    if keep_backup and backup_folder:
        preserve.add(backup_folder)
    preserve_list = " ".join(f"'{p}'" for p in sorted(preserve))
    tmp_name = f"{tmp_asset_name}.tmp" if tmp_asset_name else ""

    body = f"""#!/usr/bin/env bash
set -euo pipefail
cd {_sh_quote(exe_dir)}
while kill -0 {int(handler_pid)} 2>/dev/null; do sleep 0.4; done
sleep 0.4
{_sh_require_install_folder(new_exe_name)}
PRESERVE=({preserve_list})
should_keep() {{
  local n="$1"
  local p
  for p in "${{PRESERVE[@]}}"; do
    [[ "$n" == "$p" ]] && return 0
  done
  [[ -n "{tmp_name}" && "$n" == "{tmp_name}" ]] && return 0
  # Flat sibling backups — never nest / wipe prior old_version_* trees.
  [[ "$n" == old_version_v* || "$n" == pre_restore_v* ]] && return 0
  return 1
}}

"""
    if keep_backup and backup_folder:
        body += f"""
rm -rf {_sh_quote(os.path.join(exe_dir, backup_folder))}
mkdir -p {_sh_quote(os.path.join(exe_dir, backup_folder))}
for item in * .[!.]* ..?*; do
  [[ -e "$item" ]] || continue
  should_keep "$item" && continue
  mv -- "$item" {_sh_quote(os.path.join(exe_dir, backup_folder))}/
done
"""
    else:
        body += """
for item in * .[!.]* ..?*; do
  [[ -e "$item" ]] || continue
  should_keep "$item" && continue
  rm -rf -- "$item"
done
"""

    body += f"""
cp -a {_sh_quote(source_dir)}/. .
# CPython 3.14+ zip extract drops +x; force portable launch bits.
chmod +x {_sh_quote(os.path.join(exe_dir, new_exe_name))} 2>/dev/null || true
chmod +x Steempeg.sh Steempeg-linux Steempeg Steempeg-steamdeck 2>/dev/null || true
chmod +x bin/ffmpeg bin/ffprobe 2>/dev/null || true
if [[ -d venv/bin ]]; then chmod -R a+x venv/bin 2>/dev/null || true; fi
if [[ -d bin ]]; then
  find bin -type f \\( -name 'ffmpeg' -o -name 'ffprobe' -o -name '*.so*' \\) -exec chmod a+x {{}} + 2>/dev/null || true
fi
rm -rf {_sh_quote(extract_root)}
"""
    if tmp_name:
        body += f"rm -f {_sh_quote(os.path.join(exe_dir, tmp_name))}\n"

    body += f"""
rm -f {_sh_quote(sh_path)}
exec {_sh_quote(os.path.join(exe_dir, new_exe_name))} --updated-from {from_version} --backup-folder {backup_arg}
"""
    with open(sh_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
    os.chmod(sh_path, os.stat(sh_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    logging.info("UPDATE_INSTALL: deferred install script %s", sh_path)
    return sh_path


def spawn_deferred_install(bat_path: str, exe_dir: str) -> None:
    subprocess.Popen(
        [bat_path],
        shell=True,
        cwd=exe_dir,
        creationflags=_CREATE_NO_WINDOW,
    )


def spawn_deferred_install_unix(sh_path: str, exe_dir: str) -> None:
    subprocess.Popen(
        ["/bin/bash", sh_path],
        cwd=exe_dir,
        start_new_session=True,
        close_fds=True,
    )
