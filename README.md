![Steempeg](assets/logo.png)

# Steempeg

**A fast, hardware-accelerated renderer for Steam Game Recording clips.**  
Recover broken recordings, trim with precision, and export in one click — no Python, no command line.

![Latest release](https://img.shields.io/github/v/release/applejuicy23/steempeg?label=version&color=8b7cc8)![Windows](https://img.shields.io/badge/Windows-2d2d2d?style=flat-square&logo=windows&logoColor=white)![Linux](https://img.shields.io/badge/Linux-2d2d2d?style=flat-square&logo=linux&logoColor=white)![Steam Deck](https://img.shields.io/badge/Steam%20Deck-1b2838?style=flat-square&logo=steam&logoColor=white)![GPL-3.0](https://img.shields.io/github/license/applejuicy23/steempeg?style=flat-square&color=3d8b40) [](https://github.com/applejuicy23/steempeg/stargazers)![GitHub stars](https://img.shields.io/github/stars/applejuicy23/steempeg?style=social)[ ](https://github.com/applejuicy23/steempeg/stargazers)![Total downloads](https://img.shields.io/github/downloads/applejuicy23/steempeg/total?label=downloads&color=555555&style=flat-square)[

![Now on Windows, Linux, and Steam Deck](https://img.shields.io/badge/Now%20on-Windows%20·%20Linux%20·%20Steam%20Deck-8b7cc8?style=for-the-badge)

[Features](#-features) · [Screenshots](#-screenshots) · [Getting Started](#-getting-started) · [Website](https://applejuicy23.github.io/steempeg/) · [Docs](https://applejuicy23.github.io/steempeg/docs/) · [Changelog](#-changelog) · [Credits](#-credits)

---



## ✨ Features



### Overview


|                   |                                                                                    |
| ----------------- | ---------------------------------------------------------------------------------- |
| **Clips library** | Card browser, smart filters (game, date, duration, health), multi-select           |
| **Player**        | Trim mode, timeline markers, sniper thumbs, theatre & immersive fullscreen         |
| **Render engine** | NVENC / CPU, H.264–AV1, VP9, lots of quality presets with honest bitrate caps      |
| **Render queue**  | Card or list layout, batch export, history, survives restarts                      |
| **Steam clips**   | Finds your clip folders automatically, repairs broken block-spliced recordings     |
| **Screenshots**   | Steam screenshots tab alongside clips — browse and open from the library           |
| **Export**        | MP4 / MKV / MOV / WebM, Share · Edit · Web presets, audio-only / mute, stream copy |
| **Shells**        | Desktop layout or Portable theatre (pick once at startup)                          |
| **Platforms**     | Windows zip, Linux portable pack, Steam Deck channel (`*_steamdeck.zip`)           |




### Library & health

- Multi-folder Steam clip roots, refresh, and smart sort (name, date, duration, health).
- Clip health pills (good / warn / dead / cured) with filters that only show chips when they apply.
- Rendered Videos tab with its own filters, zoom reset on select, and purple timeline bar from real export duration.



### Player & timeline

- Trim in/out with per-clip memory, marker editing, screenshots, speed & volume chrome.
- Custom markers: drag on the timeline, duplicate, and Marker Settings (name / icon).
- Timeline sniper thumbs with warm neighbors; 3-part playhead needle + translucent hover ghost.
- Zoom overview strip with a `*` mark that tracks where the scroller sits in the full clip.
- Theatre mode and immersive fullscreen without the old maximized-window Aero flash on exit.



### Render & quality

- Plenty of quality presets (source height through 4K and beyond). Unusable taller-than-source options stay hidden; bitrate stays honest.
- Queue cards with progress, history dialog, and Settings for render priority / pause-preview while encoding.
- Target file size and Share / Edit / Web presets alongside classic bitrate modes.



### Shells, settings & updates

- **Desktop** or **Portable** shell: Portable stays in theatre with Choose a Clip / Render sheets.
- Themes: **TrueDark** (stock), **TrueDark OLED**, and classic **Default**.
- Settings dialog: updates on startup, notifications, hints reset, logs/cache, performance prefs.
- Title-bar About `(i)`, Settings, and Update Available chip; Update Center uses per-platform channels so Windows / Linux / Deck never steal each other’s zips.

---



## 📸 Screenshots

*Clips manager with filters, cards & render queue*

![Steempeg — filters, cards and render queue](docs/readme/steempeg40_1.png)

*Markers, queue & batch export*

![Steempeg — markers and queue](docs/readme/steempeg40_2.png)

*Clip cards & source info*

![Steempeg — clip cards library](docs/readme/steempeg40_3.png)

*Theatre / Portable — immersive playback*

![Steempeg — theatre mode](docs/readme/steempeg40_4.png)

---



## 🚀 Getting Started

No installer. Extract and run. Pick the zip that matches your platform from **[Releases](https://github.com/applejuicy23/steempeg/releases/latest)**.


| Platform       | Download                      | Launch                           |
| -------------- | ----------------------------- | -------------------------------- |
| **Windows**    | `Steempeg_vXX.zip` (untagged) | `Steempeg.exe`                   |
| **Linux**      | `Steempeg_vXX_linux.zip`      | `Steempeg-linux` / `Steempeg.sh` |
| **Steam Deck** | `Steempeg_vXX_steamdeck.zip`  | same as Linux (`Steempeg-linux`) |




### Windows

1. Download `Steempeg_vXX.zip` from Releases.
2. Extract to any folder.
3. Run `Steempeg.exe`.
4. Point the app at your Steam clips folder (or let it auto-detect), pick a clip, set quality, hit **Start**.



### Linux (desktop)

1. Download `Steempeg_vXX_linux.zip`.
2. Extract somewhere writable (e.g. `~/Apps/Steempeg`).
3. Make the launcher executable if needed:
  ```bash
   chmod +x Steempeg-linux Steempeg.sh
  ```
4. Double-click `Steempeg.desktop`, or run:
  ```bash
   ./Steempeg-linux
  ```
5. Prefer **X11 / xcb** if Wayland glitches (the launcher sets `QT_QPA_PLATFORM=xcb` by default).
6. Point Steempeg at your Steam Game Recording clips folder and export as usual.

The Linux build is a **portable pack** (bundled `venv` + ffmpeg/libmpv) — large zip, but it avoids the PyInstaller / Mesa freezes on NVIDIA + Bazzite-class desktops.

### Steam Deck / SteamOS

1. Switch to **Desktop Mode**.
2. Download `Steempeg_vXX_steamdeck.zip` (Deck update channel) — or the Linux zip if you only need a one-off run.
3. Extract, `chmod +x Steempeg-linux`, launch via `Steempeg.desktop` or `./Steempeg-linux`.
4. Steam clips usually live under something like
  `~/.local/share/Steam/userdata/<id>/gamerecordings/clips` — auto-discover should find them; otherwise Choose Folder.

In-app updates on Deck follow the **steamdeck** channel only (`*_steamdeck.zip`).

### Requirements

- **Windows 10 / 11** (64-bit), or **64-bit Linux** / **SteamOS** (Desktop Mode)
- **NVIDIA GPU** — optional, for NVENC hardware encoding (also probed on Linux when available)
- **Steam Game Recording** clips (`clip_`* folders with `.mpd` manifests)

**Alternative: download with GitHub CLI**

If you have [GitHub CLI](https://cli.github.com/) installed:

```bash
# Windows — untagged zip (not *_linux / *_steamdeck)
gh release download -R applejuicy23/steempeg --pattern "Steempeg_v*.zip" --dir .
# Then keep Steempeg_vXX.zip and discard any *_linux / *_steamdeck if present.

# Linux
gh release download -R applejuicy23/steempeg --pattern "*_linux.zip" --dir .

# Steam Deck
gh release download -R applejuicy23/steempeg --pattern "*_steamdeck.zip" --dir .
```

Then extract and run the launcher for your platform.



---



## 📋 Changelog

Release notes for every version live on **[GitHub Releases](https://github.com/applejuicy23/steempeg/releases)** — that's the canonical place for what's new, fixed, and changed.

---



## 🛠️ Built With

Steempeg stands on the shoulders of giants:


| Project                                        | Role                              |
| ---------------------------------------------- | --------------------------------- |
| **[FFmpeg](https://github.com/ffmpeg/ffmpeg)** | Video encoding, decoding & muxing |
| **[PyAV](https://github.com/pyav-org/pyav)**   | Python bindings for libav         |
| **[MPV](https://github.com/mpv-player/mpv)**   | In-app video playback             |
| **[PySide6](https://www.qt.io/qt-for-python)** | Desktop UI framework              |


---



## 🤝 Contributing & Issues

Found a bug or have an idea? Open an **[Issue](https://github.com/applejuicy23/steempeg/issues)** — feedback is welcome.

This is primarily a solo project; PRs are appreciated but may take time to review.

---



## ⚠️ Disclaimer

*Steempeg is an unofficial, community-created tool. Not affiliated with, associated with, authorized, or endorsed by Valve Corporation or Steam.*

---

Made with care by [Emily](https://github.com/applejuicy23) 🎀 · [Steam](https://steamcommunity.com/id/applejuicy23/)