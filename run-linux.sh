#!/usr/bin/env bash
# Dev launcher for Steempeg on Bazzite / Steam Deck / Linux.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .venv-linux ]]; then
  python3 -m venv .venv-linux
  # shellcheck disable=SC1091
  source .venv-linux/bin/activate
  pip install -U pip
  pip install -e .
else
  # shellcheck disable=SC1091
  source .venv-linux/bin/activate
fi

# Homebrew libmpv (Bazzite ships mpv CLI but often not libmpv.so).
# Note: brew Mesa EGL cannot talk to NVIDIA — Steempeg then uses vo=xv/x11
# instead of vo=gpu (see app.py). Override with STEEMPEG_VO=gpu if needed.
BREW_LIB="/home/linuxbrew/.linuxbrew/lib"
if [[ -d "$BREW_LIB" ]]; then
  export LD_LIBRARY_PATH="${BREW_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# mpv is picky about decimal separators in non-C locales.
export LC_NUMERIC="${LC_NUMERIC:-C}"

# Bundled ffmpeg with DASH demux (distro builds often lack it).
# Re-download only when missing/tiny, or STEEMPEG_REFRESH_FFMPEG=1.
ensure_dash_ffmpeg() {
  local ff="$ROOT/bin/ffmpeg"
  local fp="$ROOT/bin/ffprobe"
  local min_bytes=$((50 * 1024 * 1024))

  if [[ "${STEEMPEG_REFRESH_FFMPEG:-0}" != "1" ]] \
    && [[ -x "$ff" && -x "$fp" ]] \
    && [[ "$(stat -c%s "$ff" 2>/dev/null || echo 0)" -ge "$min_bytes" ]]; then
    return 0
  fi

  echo "Fetching ffmpeg with DASH demux into bin/ (one-time) ..."
  mkdir -p "$ROOT/bin" /tmp/steempeg-ffmpeg
  local url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz"
  local archive="/tmp/steempeg-ffmpeg/ffmpeg-btbn.tar.xz"
  # Resume if a previous run was interrupted.
  curl -L --fail --retry 3 --retry-delay 2 -C - -o "$archive" "$url"
  tar -xJf "$archive" -C /tmp/steempeg-ffmpeg
  local src
  src="$(echo /tmp/steempeg-ffmpeg/ffmpeg-n8.1-*-linux64-gpl-8.1)"
  cp -f "$src/bin/ffmpeg" "$src/bin/ffprobe" "$ROOT/bin/"
  chmod +x "$ROOT/bin/ffmpeg" "$ROOT/bin/ffprobe"
  echo "ffmpeg ready: $("$ff" -version 2>&1 | head -1)"
}
ensure_dash_ffmpeg

# libmpv wid embedding needs X11 (XWayland under Wayland sessions).
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

# Optional QEMU-safe mode: STEEMPEG_SOFT_VIDEO=1 ./run-linux.sh
exec python -m steempeg "$@"
