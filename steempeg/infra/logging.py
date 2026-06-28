"""Application-wide logging: setup, pruning, and the global exception hook."""
import logging
import os
import traceback
from datetime import datetime


def global_exception_handler(exc_type, exc_value, exc_traceback):
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"CRITICAL FATAL CRASH:\n{error_msg}")
    try:
        logging.critical(f"UNCAUGHT FATAL ERROR:\n{error_msg}")
    except Exception:  # noqa: BLE001 — last-ditch handler; never mask the crash
        pass


def session_timestamp():
    """Shared stamp for steempeg + mpv log files in the same run."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def setup_logging(logs_dir, version_str, session_ts=None):
    """Configure file logging for a run and return the path of the created log file."""
    if session_ts is None:
        session_ts = session_timestamp()
    log_filename = os.path.join(logs_dir, f"steempeg_{session_ts}.log")
    logging.basicConfig(
        filename=log_filename,
        level=logging.DEBUG,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        encoding="utf-8",
        force=True,
    )
    logging.info("=" * 40)
    logging.info(f"STEEMPEG {version_str} RUNNING")
    logging.info(f"Session log: {log_filename}")
    logging.info("=" * 40)
    return log_filename


def mpv_log_path(logs_dir, session_ts=None):
    if session_ts is None:
        session_ts = session_timestamp()
    return os.path.join(logs_dir, f"mpv_engine_{session_ts}.log")


def _dir_stats(path):
    """Return (file_count, total_bytes) for files directly under path."""
    if not os.path.isdir(path):
        return 0, 0
    count = 0
    total = 0
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isfile(full):
            count += 1
            try:
                total += os.path.getsize(full)
            except OSError:
                pass
    return count, total


def format_bytes(num_bytes):
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 ** 3):.2f} GB"
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 ** 2):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


def prune_old_logs(logs_dir, keep_paths=(), max_files=40):
    """Delete oldest log files when the folder grows past max_files."""
    if not os.path.isdir(logs_dir):
        return 0
    keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths if p}
    candidates = []
    for name in os.listdir(logs_dir):
        if not (name.startswith("steempeg_") or name.startswith("mpv_engine_")):
            continue
        if not name.endswith(".log"):
            continue
        full = os.path.join(logs_dir, name)
        if not os.path.isfile(full):
            continue
        norm = os.path.normcase(os.path.abspath(full))
        if norm in keep:
            continue
        try:
            candidates.append((os.path.getmtime(full), full))
        except OSError:
            pass
    if len(candidates) <= max_files:
        return 0
    candidates.sort(key=lambda item: item[0])
    to_delete = len(candidates) - max_files
    removed = 0
    for _, path in candidates[:to_delete]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    if removed:
        logging.info("Pruned %d old log file(s) from %s", removed, logs_dir)
    return removed


def clear_log_files(logs_dir, keep_paths=()):
    """Remove all steempeg_/mpv_engine_ logs except paths in keep_paths."""
    if not os.path.isdir(logs_dir):
        return 0, 0
    keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths if p}
    removed = 0
    freed = 0
    for name in os.listdir(logs_dir):
        if not (name.startswith("steempeg_") or name.startswith("mpv_engine_")):
            continue
        if not name.endswith(".log"):
            continue
        full = os.path.join(logs_dir, name)
        if not os.path.isfile(full):
            continue
        if os.path.normcase(os.path.abspath(full)) in keep:
            continue
        try:
            freed += os.path.getsize(full)
            os.remove(full)
            removed += 1
        except OSError:
            pass
    return removed, freed


def clear_directory_contents(path):
    """Delete every file and subdirectory under path. Returns (removed_count, freed_bytes)."""
    if not os.path.isdir(path):
        return 0, 0
    removed = 0
    freed = 0
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.isfile(full) or os.path.islink(full):
                freed += os.path.getsize(full)
                os.remove(full)
                removed += 1
            elif os.path.isdir(full):
                import shutil
                for root, _dirs, files in os.walk(full):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        try:
                            freed += os.path.getsize(fpath)
                        except OSError:
                            pass
                shutil.rmtree(full)
                removed += 1
        except OSError:
            pass
    return removed, freed


def logs_folder_stats(logs_dir):
    return _dir_stats(logs_dir)


def cache_folder_stats(cache_dir):
    return _dir_stats(cache_dir)
