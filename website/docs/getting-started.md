# Getting Started

Extract the zip for your platform and run, or use the Windows installer. Pick
the build from
**[Releases](https://github.com/applejuicy23/steempeg/releases/latest)**.

| Platform | Download | Launch |
|---|---|---|
| **Windows (installer)** | `Steempeg_vXX_setup.exe` | Start menu / desktop shortcut |
| **Windows (portable)** | `Steempeg_vXX.zip` (no platform suffix) | `Steempeg.exe` |
| **Linux** | `Steempeg_vXX_linux.zip` | `Steempeg-linux` / `Steempeg.sh` |
| **Steam Deck** | `Steempeg_vXX_steamdeck.zip` | same as Linux |

---

## Windows

1. Get Steempeg one of two ways:
    - **Installer:** run **`Steempeg_vXX_setup.exe`**. It installs for your
      user only into `%LocalAppData%\Programs\Steempeg`, no admin needed.
      Options: a desktop shortcut and **Start Steempeg with Windows** (hidden
      in the tray, catches new Steam clips). Uninstall from Windows Settings →
      Apps.
    - **Portable:** extract **`Steempeg_vXX.zip`** to any folder and run
      **`Steempeg.exe`**.
2. At first launch, pick **Desktop** or **Portable** shell (you can keep that choice later).
3. Point Steempeg at your Steam clips folder (or let it auto-detect), open a clip, set quality, hit **Start**.

Steam Game Recording clips usually live under your Steam userdata `gamerecordings/clips` tree.

---

## Linux (desktop)

1. Download **`Steempeg_vXX_linux.zip`**.
2. Extract somewhere writable (for example `~/Apps/Steempeg`).
3. Make the launcher executable if needed:

   ```bash
   chmod +x Steempeg-linux Steempeg.sh
   ```

4. Double-click **`Steempeg.desktop`**, or run `./Steempeg-linux`.
5. Prefer **X11 / xcb** if Wayland glitches (the launcher sets `QT_QPA_PLATFORM=xcb` by default).
6. Point Steempeg at your Steam Game Recording clips folder and export as usual.

The Linux build is a **portable pack** (bundled tools) — large zip, but it avoids a pile of system dependency pain.

---

## Steam Deck / SteamOS

1. Switch to **Desktop Mode**.
2. Download **`Steempeg_vXX_steamdeck.zip`** (Deck update channel).
3. Extract, `chmod +x Steempeg-linux`, launch via **`Steempeg.desktop`** or `./Steempeg-linux`.
4. Clips often live under  
   `~/.local/share/Steam/userdata/<id>/gamerecordings/clips` — auto-discover should find them; otherwise use Choose Folder.

In-app updates on Deck follow the **steamdeck** channel only (`*_steamdeck.zip`).

---

## First export (any platform)

1. Open a clip from the library (or **Choose a Clip** in Portable).
2. Set in/out on the timeline if you want a trim.
3. Pick quality / codec in Video or Export settings.
4. Use **Start** (or add to the **Render Queue** and start the queue).
5. Find the file under your export destination — **Rendered Videos** in the library lists finished exports.

---

## Requirements

- **Windows 10 / 11** (64-bit), or **64-bit Linux** / **SteamOS** (Desktop Mode)
- **NVIDIA GPU** — optional, for NVENC (also probed on Linux when available)
- **Steam Game Recording** clips (`clip_*` folders with `.mpd` manifests)

---

## Next

- [Docs home](index.md) — more guides as they appear  
- [GitHub Releases](https://github.com/applejuicy23/steempeg/releases/latest) — downloads  
- [Product site](https://applejuicy23.github.io/steempeg/) — overview
