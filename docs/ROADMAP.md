# Steempeg Roadmap

**Internal kitchen doc** — our shared memory so nothing gets lost until v56 when Emily says «а я это предлагала!!!». Not public. README stays minimal; paste a short teaser there only near a release if needed.

**Version note:** **v41.1** closed. **v42** kitchen mostly parked/shipped piecemeal. **No public v43** — Emily (8 Aug 2026): skip the number, fold the spike + new kitchen into **v44**. In-tree Screenshots / ClipCard experiments stay; they ship under the **v44** banner. README stays minimal.

**v45 framing (14 Aug 2026):** treat **v45** as a **large intermediate** update — same *scale* of ambition as the old **v30 / v40** majors (player prefs + queue defer + Screenshots + Update Center shell + library chrome), not a tiny patch train. Ship when the remaining short list below is done; **stop stuffing** after that.

**v45 shipped (mid-Aug 2026).** Next is **v45.1** — a **bugfix patch** for accumulated regressions (Update Center, Portable Add / queue cards, bundled freeze icons). **DEV MODE diagnostics** stay kitchen-only / later — not the patch headline.

**From 16 Aug 00:00 (Emily 15 Aug eve):** park Animations pack energy; develop **Preset manager UX v2** and prepare the **v45 release**. Filters persist + Settings/queue/player polish land in the late-15-Aug commit batch.

**16 Aug (Preset v2 slice):** neo **Presets** tab — Update / Rename / Duplicate / ★ favourites + chips, search, “What's inside” detail strip, clearer Delete selection. See **§ Custom export presets → Preset manager UX v2**.

---

## ✅ Shipped — v41.1 «desktop splitters + Update Center»

| # | Item | Notes |
|---|------|--------|
| 1 | **Desktop splitters — five states + verge kiss** | ✅ Nested shell: `main_splitter` = Clips \| `right_h_splitter` (player + queue). Left drag is manual in `ui/splitter_rules.py` (queue frozen on press; Qt `moveSplitter` skipped). Collapsed panes pin at `PANE_FREED=1`; reopen snaps to floor, never creeps. **Kiss travel only at the verge of closing:** when a neighbour is already at its own floor it has no slack to lend, so the player column stays shut and shutting that neighbour travels the joint (both handles move; far pane takes the room). Mid-window kisses stay separable by **either** handle — do **not** latch global «kiss ownership». Gotchas: `setMinimumWidth(0)` is a no-op; use real handle widget width (~10px), not `handleWidth()` (6). Emily's five-state write-up is the source of truth. |
| 2 | **Update Center: backup confirm close kills whole panel + stuck cursor** | ✅ **Windows.** Closing the backup confirm via red traffic-light closed the **entire** Update Center and left the cursor stuck in hover. Cause: `_on_install_clicked` emitted install then **always `accept()`**. Fixed: dropped `accept()` on emit; `_clear_update_chrome_hover` after the confirm |
| 3 | **[Linux] Update Center micro-window flash** | ✅ Same family as the Windows ghost HWND. Fixed with an off-screen warm show (`WA_DontShowOnScreen`) then map at final geometry — `dialog_chrome.py` |
| 4 | **Player timeline strip — taller** | Deferred to **v42**. Emily compared **v16 vs v41** screenshots — strip may have regressed or feels thinner than old builds / Steam. Re-check `track_height` in `timeline.py` (today **12px**) |

---

## ✅ Shipped — v37 «Update Center + detached updater»

- **Update Center** — pick any installable release (upgrade/downgrade), milestones, patch groups, version colors, release notes
- **Install policy** — v16+ stable install; v12.1–15 risky; v12.0 blocked; v0–11 manual
- **Before updating** — Steempeg chrome confirm: Update · **Update & keep backup** (accent) · Cancel (red)
- **Detached `--update-handler`** — download → extract → deferred `.bat` install (fixes PyInstaller DLL lock / WinError 5) → launch with `--updated-from`
- **Updater progress window** — Steempeg chrome, ⚙️ heading, minimize, **close = cancel during download only**
- **GitHub API rate limit** — countdown dialog + auto-reopen Update Center when limit resets
- **CI** — `compileall` + import smoke (`QT_QPA_PLATFORM=offscreen`)
- **UI polish** — `FONT_APP` / Segoe UI panel titles, ⚠️ downgrade notices, purple ack box, ✂️ trim in queue, History+Clear toolbar spacing, Render History in-content title
- **Status bar marquee** — single-segment indeterminate bar for `busy` tasks (Checking for updates…): one strip loops start → end → start

**Test note:** after releasing **v38dev**, downgrade **38dev → v37** via Update Center to validate the full update path on a real zip. **Backup restore UI** — verify in v38 (create backup on v37 → upgrade to 38dev → restore).

**Backup / restore policy:** in-app **Update & keep backup** + **Restore local backup** exist from **v37+** only (`old_version_v*` next to exe). Older installs have no in-app restore — revert manually (re-extract zip or copy folders by hand). Downgrade **to** v16–36 still works if a zip exists on GitHub; backup folder from a v37 session is only restorable from **v37+** UI.

### v38+ idea — «thinking → download» bar transition *(not v37)*

Fancy status-bar animation for update check / connect / download handoff:

1. **Thinking phase** — full-width neural «thinking» shimmer while GitHub fetch / API connect runs (`Checking for updates…`).
2. **Handoff** — on success («found it, downloading»): shimmer **splits** — one half fades out off-screen, the other **merges** into the real determinate progress fill.
3. **Download** — normal % bar to 100% (today’s render/download shimmer on filled portion).

Also considered for v38 but deferred: center **breathing pulse** busy bar (tried in dev, rejected — keep marquee for unknown duration).

---

## 🎯 v38 — «Dialog finish + queue completion UX» *(next)*

**Why v38:** v37 updater is functionally done; v38 is where we **доредизайним и дорепилим** — every remaining stock dialog + queue “what just rendered?” flow. Good release to exercise **downgrade from 38dev → 37** while polishing UI.

### P0 — Zero `QMessageBox` (SteempegDialog / shared confirms)

Replace system boxes with Steempeg chrome (title bar, `FONT_APP`, primary/danger buttons). Priority order:

| # | Dialog | Where | Notes |
|---|--------|-------|--------|
| 1 | **Update successful** | `updater_mixin.show_update_success` | First thing users see after v37→v38 jump |
| 2 | **Update failed** | `update_handler` | Install/download errors |
| 3 | **Updater / restore errors** | `updater_mixin` | Open Update Center, restore backup |
| 4 | **Clear render queue** | `render_controller` | Confirm before wipe |
| 5 | **Clear render history** | `render_queue_history` | Confirm “Clear all” |
| 6 | **Delete clip** | `library/controller` | Warning + Delete / Cancel |
| 7 | **Delete rendered file** | `rendered_library` | Same pattern |
| 8 | **Render complete (single)** | `render_controller.on_render_finished` | Open folder · Open video · **Open Rendered videos** (with preview) |
| 9 | **Render cancelled** | `render_controller` | Styled ack |
| 10 | **Dead clips / remove folder / clear logs / clear cache** | `library/controller`, `lifecycle` | Confirm + result toasts |
| 11 | **Preview offer** | `player/controller` | Optional preview after action |
| 12 | **Fatal / interface error** | `app.py` startup | Last resort — still chrome, not Win32 box |

**Already chrome (v37):** Update Center, Before updating, Steempeg Updater, GitHub rate limit, Render History shell.

**Partial chrome (migrate in v38):** About (`lifecycle`), FFmpeg error (`render_controller`), bug report (`report_dialog.py`).

**Shared helper:** thin `SteempegConfirmDialog` / `SteempegMessageDialog` so we don’t copy button styles 20×.

### P1 — Render queue: auto-clear completed

| # | Item | Notes |
|---|------|--------|
| 1 | **Checkbox** | e.g. “Remove completed jobs automatically” — persisted in settings / queue prefs |
| 2 | **On job done** | When status → `Completed`, remove card if checkbox on |
| 3 | **Batch all-done** | When **every** job in queue is completed (or queue empty after auto-remove), clear remaining completed state / optional full queue wipe |

### P2 — After render: actions (single export)

When **one** clip finishes (not batch):

- **Open folder**
- **Open video** (default player)
- **Open Rendered videos** — switch to Rendered tab/shelf and **focus + preview** that file

Replace today’s generic `QMessageBox` with Open folder / Play / OK.

### P3 — Batch finished window (render queue)

When **queue batch** finishes — dedicated **SteempegDialog**, not a one-line status:

- Title: e.g. “Batch render complete”
- **Scrollable list** of everything rendered in this run (game, preset, path, ✂️ trim if any, status)
- Per row or footer actions: Open folder · Open file · jump to Rendered videos
- Link/button: **Open Render History** (existing dialog)
- Optional: same auto-clear checkbox behavior applies here

**Not the same as P2:** single render = compact action sheet; batch = full summary list in one window.

### P4 — Small v38 polish (if time)

- **Thinking → download bar transition** — see v37 shipped § «thinking → download» idea above
- Report dialog → `SteempegDialog`
- Restore backup via handler (drop `restore.bat` parity)
- `selection_marker_text` / install button copy consistency

### P5 — Custom timeline marker images *(v38 if time, else v39)*

**Goal:** User-chosen marker art on the timeline, not only Steam’s default `markers.svg` sprites.

**Today (v37):**
- `MarkerIconStore` loads per-game `markers.svg` from Steam cache, Steempeg cache, or CDN (`steam_markers.py`).
- Legacy **bundled CS2 PNGs** (`kill.png`, `smoke.png`, digit sprites, etc.) still exist in `timeline.py` but the live path prefers Steam SVG icons.
- User-placed markers use `pointuser.png` only.

**Planned:**
| # | Item | Notes |
|---|------|--------|
| 1 | **Per-game marker packs** | Folder or zip per `app_id`: map Steam icon ids (`cs2_death`, `cs2_kill`, …) → custom PNG/SVG files |
| 2 | **Settings UI** | Player or Settings: pick marker theme per game, import folder, preview strip, reset to Steam default |
| 3 | **Bundled CS2 pack toggle** | **→ v41 kitchen list** — tumbler: Steam CDN ↔ Steempeg CS2 hand-drawn PNGs |
| 4 | **Fallback chain** | Custom pack → Steam cache/CDN → generic dot / `point.png` |
| 5 | **User marker icon** | Let users pick the image for manually added markers (not only `pointuser.png`) |

**Code touchpoints:** `steam_markers.py` (`MarkerIconStore`), `timeline.py` (`icon_paths`, `marker_store.get_icon`), settings JSON under `cache/markers/` or `settings.json`.

**Related (old one-liner):** was listed as “Custom timeline markers toggle” in v36 P4 deferred — this section supersedes it.

**Later UX (v46, not this P5):** Marker Settings **On clip** list icons + CS2 type-vs-instance count — Emily 17 Aug («тут чет не срастается»); **build** green-lit Emily 20 Aug. See **§ Marker Settings / On clip (v46)**. Optional **v20-style markers on the strip** (overlay, not a forced default) — **§ Markers on the strip (v46)** (**build** 20 Aug).

### P6 — Launch splash / “Steempeg is starting” *(v38+ / polish track)*

**Goal:** Lightweight launcher window while the app cold-starts (before the main shell is ready), same Steempeg chrome as updater dialogs.

**Why:** PyInstaller + Qt + mpv init can take a few seconds on slow disks; today the user sees nothing until the main window appears.

**Sketch:**
| # | Item | Notes |
|---|------|--------|
| 1 | **Splash window** | Small frameless `SteempegDialog` or minimal card: logo, “Starting Steempeg…”, optional version subtitle |
| 2 | **Progress hint** | Busy marquee or soft shimmer (reuse `AnimatedRenderBar` `busy` state) while imports / settings / library scan run |
| 3 | **Handoff** | Close splash when main window is shown (or first frame painted); no second taskbar entry if possible |
| 4 | **Skip path** | Fast launches (&lt;300 ms) skip splash entirely so power users never flash an extra window |
| 5 | **Updater parity** | Visual family matches **Steempeg Updater** / Update Center (logo, purple accent, Segoe UI title) |

**Not:** a second heavy bootstrap exe unless we need it for DLL lock reasons; prefer in-process splash from early `app.py` before `MainWindow` construct.

**Code touchpoints:** `app.py` startup, optional `steempeg/ui/launch_splash.py`, `design_tokens` panel styles.

### Not v38

- Auto-rollback if deferred install fails mid-robocopy (still: **Update & keep backup**)
- Linux / How To guide (~v40)
- DASH-native editor app (long-term — see **Steempeg Family** §)
- **Portable / Steam Deck shell** — own track (**§ Portable / Steam Deck shell** below). Do **not** keep pouring energy into crushing the desktop three-splitter layout for Decks.

---

## 🎮 Portable / Steam Deck shell — «theatre-only» *(v41+ product track)*

**Decision (21 Jul 2026, refined same evening):** one app, **two shells**. Deck is a **portable console** (Gaming + Desktop modes on SteamOS). In Desktop mode there **is** a cursor — good. Design for cursor + optional gamepad scroll after focus; don’t assume keyboard.

| Face | What it is |
|------|------------|
| **1. Desktop** | Current Steempeg — Clips \| Player \| Queue, splitters, export dock |
| **2. Steam Deck / Portable** | **Exclusively theatre mode** — one player surface, **no side docks, no horizontal splitters** |

**Launch gate (v1):** on startup ask once (then remember):

1. **Desktop version** — today’s UI  
2. **Steam Deck version** — theatre-only shell below  

Persist choice in `settings.json` (allow change later in settings).

**Why not denser desktop:** compact density squishes chrome and player circles; right splitter in compact is cursed. **Do not fix compact-for-Deck** — new shell instead.

### Screen map (theatre)

```
┌─ title: Steempeg vXX  [Check] [About]  ● ● ● ─┐
├─ [logo] [game / “Select a clip…”] [Choose a clip] … ─┤
├─ header chips: health | Add to Queue → In queue (N)+⚙ | … ─┤
│                                                         │
│                    MPV theatre surface                  │
│                                                         │
├─ timeline + transport (FULL-SIZE circles — no density squash) ─┤
│  … Trim …     [ Render / Start queue ]  [ Render settings ]   │
└─────────────────────────────────────────────────────────┘
```

Emily mocks: empty state + **Choose a clip** near title/meta; **Render** on the player chrome; with a clip loaded, header **Preview / In queue** zone becomes **Add to Queue** flow.

### P0 — Launch + theatre chrome

| # | Item | Notes |
|---|------|--------|
| 1 | **Startup chooser** | Dialog: Desktop · Steam Deck — then enter that shell |
| 2 | **Theatre only** | No Clips/Queue splitters; player fills the window |
| 3 | **Title-bar Check + About (+ Settings)** | About `(i)` + Settings shipped; **v41:** dedicated **Check for updates** button in the title bar |
| 4 | **No player-circle density squash** | Desktop compact may still shrink transport circles — **Steam Deck shell must keep full round play / ±15s / 1x** (explicit exception) |
| 5 | **Cursor + gamepad** | SteamOS Desktop has cursor. After focusing a sheet, D-pad / scroll can move selection left-right (grid) or up-down. Multi-select needs a modifier (e.g. hold shoulder / Steam chord). **Research never spiked** — library/queue mapping kitchen **§ Steam Deck controls (v47)**; player face buttons / no stick-as-mouse → **§ Steam Deck player controls (v48)** |

### P1 — Choose a clip (portable Clips Manager)

| # | Item | Notes |
|---|------|--------|
| 1 | **Button** | Near logo + game name / empty “Select a clip…” — label **Choose a clip** (or **Add a Clip** when picking for queue) |
| 2 | **Sheet = minimized Clips Manager** | Overlay, not a dock |
| 3 | **GRID ONLY** | No Grid/List toggle — more room; list mode out of scope for Deck shell |
| 4 | **Tabs** | **Clips** · **Rendered videos** — same idea as desktop library modes; Rendered = browse finished exports and open in Steempeg |
| 5 | **Sort + filter** | Basic only (game, date, …) |
| 6 | **Select → preview** | Single tap/click loads theatre |
| 7 | **Multi-select** | For queue add / delete — gamepad: focus + scroll; multi-mark via hold/modifier (TBD). Cursor: click / ctrl-equivalent if available |
| 8 | **Queue index badges** | Queued clips show **1, 2, 3…** on the grid card so you see order in the manager |

### P2 — Render button (single / “just render”)

| # | Item | Notes |
|---|------|--------|
| 1 | **Render** | Starts render for current clip with saved/default settings (or opens confirm) |
| 2 | **During / after** | Progress UX; on finish — **completion window** (same family as today’s batch/single done dialog): open folder · open file · open in Steempeg |
| 3 | **Open in Steempeg** | Land on player / or Choose-a-clip → **Rendered** tab focused on that file |

### P3 — Render settings sheet

| # | Item | Notes |
|---|------|--------|
| 1 | **Render settings** button | Opens sheet with **same tabs** as desktop Export (Source / Video / Audio / Export) |
| 2 | **Save** | Persist parameters only → back to clips/theatre |
| 3 | **Save & Start Render** | Persist + start this clip now (user doesn’t care about browsing more) |
| 4 | When queue is active | Same sheet, but primary becomes **Save** · **Save & Start Queue (N)** — mirror desktop Start Queue wording |
| 5 | **Selection summary strip** *(above Source / Video / Audio / Export)* | Relays the **selected / focused queue job** in richer form than a queue card: thumb + title + meta, and especially **estimated output size after render** + **free disk space** on the export drive. Same strip idea can later land on desktop Render too. Implementation TBD (probe export path + rough size from bitrate×duration / preset). |

### P4 — Queue (header where Preview / In queue lives today)

| # | Item | Notes |
|---|------|--------|
| 1 | **Default CTA** | Always **Add to Queue** when nothing queued / idle |
| 2 | **After first add** | Show **In queue (N)** + **⚙ queue settings** (list jobs, remove, reorder later) |
| 3 | **Add more** | Open **Choose a clip** / **Add a Clip** → select one or many → **Add to Queue**; grid shows queue numbers |
| 4 | **Main Render control** | Becomes **Render Queue** / **Start queue (N)** like desktop when queue has jobs |
| 5 | **Settings from queue context** | Same Save · Save & Start Queue (N) |

### P5 — Shared brain

| Keep shared | Deck / Portable only |
|-------------|----------------------|
| Library scan, health, trim, markers, FFmpeg, `RenderJob` | Theatre layout, sheets, startup chooser |
| Desktop export tabs / queue list widgets (embedded) | GRID-only manager, no splitter chrome |
| Completion dialogs / later OS toasts | Full-size transport circles (no compact density) |

### Explicit non-goals

- Fixing desktop **compact splitter** / squashed circles **for Deck**
- Second GitHub product
- Dropping desktop three-pane for big monitors
- Keyboard-only multi-select as the only path

### Code touchpoints *(when we start)*

- Startup chooser + `ui_shell: desktop | steam_deck` (names TBD)
- `steempeg/ui/portable/` — theatre host, clip sheet, render settings sheet, queue sheet
- Density: **skip** transport-circle compact path when shell is Deck
- Reuse: export tabs, completion dialog, library grid data, queue model

**Band:** startup chooser + empty theatre spike **v41**; Choose-a-clip GRID + Render/Settings **v42**; queue Add/In queue/Start Queue **v43**. Gamepad / Deck-button mapping did **not** land in v44 — kitchen moved to **§ Steam Deck controls (v47)** (v46 already fat).

---

## 🔔 OS notifications — render done while minimized *(any shell)*

**Shipped (v42):** When render finishes or fails and Steempeg is **minimized / in background** — native notification + **system** alert sound (no bundled SFX):

| Platform | Path |
|----------|------|
| **Windows** | Action Center via `QSystemTrayIcon.showMessage` + `winsound` alias (`SystemExclamation` / `SystemNotification`) |
| **Linux** | Tray toast or `notify-send`; sound via `canberra-gtk-play` / freedesktop `paplay` |
| **SteamOS / Deck** | Same Linux path |

| # | Item | Notes |
|---|------|--------|
| 1 | **Triggers** | ✅ Single done · batch all-done («ВИДОСИКИ ОТРЕНДЕРЕЛИСЬ») · failure (single + mid-batch) |
| 2 | **Copy** | Game / filename / short FFmpeg line |
| 3 | **If already focused** | Prefer in-app dialog; skip OS toast; errors still play system beep |
| 4 | **Setting** | ✅ «Notify when render finishes or fails» — default on (`notify_on_render_complete`) |

**Code:** `steempeg/infra/os_notify.py`, `steempeg/infra/system_sound.py`, `render_controller` completion / error paths.

**Later kitchen (not shipped):** **§ Express / quick render from new-clip notification** — toast when a *new clip* appears («Want to render this clip?») → lightweight Portable-like window with that clip preloaded. Different trigger than render-done; see Ideas backlog.

---

## ✅ Shipped — v35

- **Export containers** — MP4, MKV, MOV, WebM + correct extensions
- **Video codecs** — H.264, H.265, AV1, VP9 (+ Original stream copy)
- **Audio** — AAC, MP3, Opus, FLAC, WAV; Copy only in Original mode
- **Named presets** — Share / Edit / Web
- **Smart export UI** — invalid container+codec pairs greyed out
- **Honest bitrate** — measured from disk, presets capped to source (`22 Mbps (Original)`)
- **Original mode** — frozen settings, real Mbps shown
- **Render queue** — compact preset line on cards
- **Export tab** — layout width, path elision, copy button, settings insets
- **Timeline** — Steam CDN sprite markers when cache missing; hover sniper on Rendered tab fixed
- **Render progress** — animated bar + shimmer
- **Library UX** — closable tabs, multi-select, filter restore
- **Rendered videos panel** — grid/list, filters, sidecar meta, debounced preview (landed in 34.x, polished in 35)

---

## 🎯 v36 — «Steempeg design system + polish» *(shipped / continued in v37)*

**Start here — nothing else before this:** custom app shell like **VS Code** (or any reference app), but in **our** style — not per-window one-offs.

### P0 — Custom chrome (do first)

| # | Item | Notes |
|---|------|--------|
| 1 | **Frameless main window** | Custom title bar: Steempeg font + colors (not system Segoe) |
| 2 | **Traffic-light controls** | Red / yellow / green circles — close, minimize, maximize (replace ─ □ ✕) |
| 3 | **Unified dialogs** | Batch finished, FFmpeg errors, About, report, confirms — `SteempegSheet` style, zero stock `QMessageBox` / native title bars |
| 4 | **Design tokens** | Shared palette, radii, spacing, buttons — library, player, export, queue, settings, popups |
| 5 | **Draggable title bar** | Maximize/restore still works on Windows |

### P1 — Bugs & small fixes

| # | Item | Notes |
|---|------|--------|
| 1 | **Trim panel after tab switch** | Start trim in Clips Manager → switch to Rendered videos → trim UI (Cancel / scissors) still visible under player. Hide on rendered switch *or* make context-aware (trim MP4 later is valid — decide per tab). |
| 2 | **Duplicate-clips status spam** | `Ignored N duplicates across folders` in Ready status fires **every launch**. Show only when a **new folder is added** that contains duplicates — not on routine rescans. (`library/controller.py` ~1318) |

### P2 — UI polish (same release, after chrome)

| # | Item | Notes |
|---|------|--------|
| 1 | **Clip health icons** | Redesign Healthy / Issues / Dead — circles are boring |
| 2 | **Render History actions** | Today «Open file» opens **folder** only. Need **two buttons**: Open folder + Open file. Hide Open file if output was deleted. |
| 3 | **Queue toolbar icons** | **History** → history icon (no text). **Clear** → trash icon + keep «Clear» label |
| 4 | **Original preset warning** | Remove square box around triangle icon — icon only. Hover = risk tooltip. Button **«ОСВЕДОМЛЕН»** dismisses warning forever (persist in settings). |
| 5 | **Batch finished → History** | After queue finishes («6 videos done») — add way to **open Render History** immediately: what rendered, where saved, open/delete from there |
| 6 | **Render Queue empty state** | «Right-click a clip → Add to queue» feels sovdep. Either **empty** or restyle hint to match new chrome |

### P3 — Last in v36 (or slip to v37 if chrome eats the release)

| # | Item | Notes |
|---|------|--------|
| 1 | **Player control bar on resize** | Buttons left/right drift into center when window shrinks — broken since v16/v25/v36 attempts. Idea: **invisible edge blocks**; when buttons collide with center, **blur + horizontal scroll** inside blocks. Hard — do last. |
| 2 | **Splitter video stuck** | → **later / v45+:** [MPVWrapper hard fix](#mpvwrapper-hard-fix-later--v45--opus-max-effort). Drag splitters → MPV surface floats / orphan mini-player. Since ~**v20**. |

### P4 — Hidden / deferred (recorded, not v36 promise)

| Item | Notes |
|------|--------|
| **Custom timeline marker images** | Superseded by **v38 § P5** — per-game custom marker packs, settings UI, CS2 preset toggle. |
| **Trim rendered MP4** | Might be valid later on Rendered tab; tied to trim-panel bug above. |

### Still on the v36 list (from earlier planning)

- [ ] **Queue depth** — edit container / codec / preset **per job** from queue panel (see **§ Custom export presets + queue rules *(v41)***)
- [x] **8K / Goddess + Divine 4K** — `quality_presets.py` (4320p+; bitrates + area scale)

---

## 🎯 v37 — Update Center (upgrade + downgrade) *(shipped — see ✅ Shipped — v37)*

Legacy planning notes below kept for context. Implementation lives in `update_center.py`, `update_handler.py`, `release_catalog.py`, etc.

**Examples**
- On **v22** → can jump to **v26**, **v30**, **v36.1** (whatever has a `.zip` on GitHub).
- On **v36.1** → can downgrade to **v16** (not to v8).

### Version eras (install policy)

| Era | Versions | In-app picker | Notes |
|-----|----------|---------------|--------|
| **Alpha** | 0–8 | ❌ hidden / grey «manual only» | `smpeg8.py` — dialog + opens browser; no zip install. Artifact era. |
| **Browser-only** | 9–11 | ⚠️ «Open GitHub» only | `smpeg9.py` — WOW dialog, `webbrowser.open(releases)`. No in-app zip pipeline. |
| **Early installer** | 12–15 | ⚠️ optional with scary warning | `smpeg12.1.py` — first zip + `updater.bat`; still flaky. |
| **Reliable** | **≥16** | ✅ full install | `smpeg16.py` — same model as today (`UpdateDownloadThread` + bat). **MIN_INSTALL = 16**. |
| **Current** | 36.x | ✅ | `releases/latest` today; picker uses **all releases** API. |

Reference artifacts: `C:\Projects\Steempegold\smpeg8.py`, `smpeg9.py`, `smpeg12.1.py`, `smpeg16.py`.

### UI sketch

- Header: **You are on v{X}** (from `APP_VERSION_STR`).
- List or combo: all GitHub releases **newest first**, each row = tag + title + badge:
  - `current` · `newer` · `older` · `recommended min (16+)` · `browser-era` · `unavailable`
- Release notes snippet (body markdown/plain) for selected row.
- Buttons: **Install selected** · **Open on GitHub** · **Restore local backup** (if `old_version_v*` folder exists next to exe).
- Pre-flight checkbox on downgrade: «I understand settings / queue / rendered sidecars may not match this version».

### Rules engine

1. **Fetch** `GET /repos/applejuicy23/steempeg/releases` (paginated), not only `/latest`.
2. **Installable** = release has asset `*.zip` **and** parsed version **≥ 16.0**.
3. **Alpha (≤8)** — never offer Install; optional footnote «pre-updater builds».
4. **9–15** — show in list but Install disabled unless user enables «expert» toggle (or always disabled — decide at implementation).
5. **Any jump** across major refactors → extra warning (heuristic: v29 refactor, v30 queue, v35 rendered, v36 chrome).
6. Reuse existing pipeline: `start_downloading_update` → unzip → backup choice → `updater.bat` (same as `updater_mixin.py` today).
7. **Restore backup** — if `old_version_v36/` exists, one-click «revert to backed-up tree» (same bat logic, reverse direction).

### Code touchpoints

- New: `steempeg/ui/update_center.py` (dialog) + `steempeg/services/release_catalog.py` (GitHub parse + policy).
- Refactor: `UpdaterMixin.check_for_updates` → opens Update Center instead of QMessageBox.
- Keep: `UpdateDownloadThread`, `show_update_success`, `--updated-from` / `--backup-folder` args in `app.py`.

### Not v37

- Compact / Steam Deck layout → superseded by **§ Portable / Steam Deck shell** (theatre-first; not denser desktop).
- Footer lane fade (archived in `steempeg/.footer_lane_experiment_*`).

---

## 🔜 After v36

| Item | Target |
|------|--------|
| **Update Center** | See **v37 — Update Center** above (picker, downgrade, era rules) |
| **Timeline & preview** | Smoother scrubbing, frame feedback |
| **Editor building blocks** | Small steps in Steempeg (trim, markers); full NLE → **Steempeg Family** § |

---

## 📖 ~v40 → v50–60 — User Guide site *(docs, not code)*

**Decision (Emily 9 Sep 2026):** GitHub README stays **simple** (download + quick path: open → pick clip → trim → render). Full product story lives on a **real site**, not a fat README.

**Site shape (Emily 9 Sep eve):**  
- **Main site — красивый** — landing / витрина: brand, download, screenshots, «за 2 минуты», vibe. Not a wall of manuals.  
- **Docs (вкладки / `/docs`)** — матчасть программы: Quick + Deep bible (maps below). Same product home, separate surface from the pretty landing.  
Domain TBD (`steempeg.com` + `/docs`, or `docs.steempeg.com`) — prefer not `git.…`. Host: GitHub Pages (public or private Pro repo) + optional custom domain.

Two tracks in Docs: **Quick** (рядовой юзер) and **Deep** (fat product bible — converter-level). Needed before / alongside **Steempeg PRO**.

**Pace (Emily 9 Sep eve):** do **not** dump the whole bible in one release. Start writing **~v50–51** with the **simplest / fastest user-facing** pages; thicken Deep through **v50–60** so nobody dies of volume. Outline + map live here; pages ship incrementally. Landing polish can land in the same band as early Docs.

### Delivery

| Layer | Home | Content |
|-------|------|---------|
| README | GitHub | Install + 4-step Quick; link to **site** (landing + Docs) |
| **Landing** | Main site `/` | Красивая витрина — brand, download, screens, short pitch |
| **Docs Quick** | Site `/docs` (or docs subdomain) | Fast path, screenshots, no theory |
| **Docs Deep** | Same Docs area | Every major surface + nuances (maps below) |
| Kitchen | `docs/ROADMAP.md` | Never public Guide |

### v50 docs / site slice *(Emily 11 Sep 2026 — concrete first cut)*

Not the full Wave A bible — just enough so GitHub + site exist:

| # | Item | Notes |
|---|------|--------|
| 1 | **Site shell on GitHub** | Empty / near-empty Pages (or sibling docs repo) — landing shell so the product has a home URL. Pretty later; **exist first**. |
| 2 | **Getting Started + Basics** | Mini novice guide → GitHub README *and* site Docs. Same energy as Wave **A1–A2** (open → clip → trim → render; folders/roots). Keep short. |
| 3 | **README product face rethink** | Optional polish of the main GitHub README capability story (tables + lists mix). Emily TBD — may leave if current copy is fine. |

**Pace:** shell + Getting Started in **v50**; thicken Wave A through **v50–51**; Deep later.

### Wave A — v50–51 first *(рядовой юзер — must know)*

| # | Chapter | Cover |
|---|---------|--------|
| A1 | **Quick start** | Download → open → pick clip → trim → queue/Start → where file lands |
| A2 | **Folders / clip roots** | Root = folder **containing** clips, not one clip folder. Search **inside** roots (`recordings` → nested). Wrong pick → empty or one video |
| A3 | **Render panel — 2 modes** | **Basic** = library-selected clip. **Queue** = next queue job (not library selection) |
| A4 | **Render queue UX** | Top→bottom; per-job settings/TRIM/path; stop / leave / clear; **colors** (yellow=next, purple=selected, green=ok, red=fail); **error ~10s** → stop/continue / auto-continue |
| A5 | **Trim (user-facing)** | In/out, what export respects, per-clip memory |
| A6 | **Presets at a glance** | **Original** = remux/concat (no re-encode). Other quality presets = **re-encode**. Share/Edit/Web in plain language |
| A7 | **Health pills (short)** | Healthy / warn / dead / cured — what user sees + «Repair / Resurrect» buttons without full tech |

### Wave B — Deep product surfaces *(v51–55-ish)*

| # | Chapter | Cover |
|---|---------|--------|
| B1 | **Clips Manager / ClipCard** | Card chrome, selection, density, health on cards |
| B2 | **Clip health (full)** | How validation works; warn vs dead vs cured |
| B3 | **Repair & resurrect** | How unhealthy are fixed; how dead are resurrected; user steps |
| B4 | **Rendered Videos** | Own shelf + **own validator + repairer** |
| B5 | **Screenshots space** | How screenshots load / display |
| B6 | **Performance modes** | **Skip** — what/where saves; **Quick** — what it scans / skips; **Progressive** — progressive load tech |
| B7 | **Player nuances** | Theatre / fullscreen / speed / volume / preview quality (does not affect export) |
| B8 | **Audio** | Mute / audio-only / stream paths users hit in export + playback quirks |
| B9 | **Render settings panel** | Every user-facing control in Basic vs Queue context |
| B10 | **Player previews / PyAV sniper** | Disk batch thumbs vs on-demand PyAV; RAM init-bytes cache; tip sensor (Dev opt-in) |
| B11 | **Check for updates** | GitHub parse / channels; version→version transfer; backups / restore |

### Wave C — Steempeg-unique tech bible *(v55–60, thick)*

| # | Chapter | Cover | Why special |
|---|---------|--------|-------------|
| C1 | **Clip identity from Steam** | How app resolves **game**, **game name**, **record date/time**, **duration** from clip trees | Day-one library magic |
| C2 | **Game icon parser** | How icons are found / matched to clips | Known Steam-ish pattern; still document |
| C3 | **Steam timeline markers parser** | Steempeg walks Steam files to find **where markers live** and loads them onto the timeline — **Emily + agent invented this; nowhere else** | Unique IP — flag as house tech |
| C4 | **DASH playback guts** | How player / ffmpeg / mpv reads **video chunks + audio chunks**; how **`session.mpd` is repaired/restored** for correct play; how **Issue clips** are opened so they play without pain | Core differentiator |
| C5 | **Original vs re-encode** | Original = **склейка / remux**; other ladders = **re-encode** (NVENC/CPU…) — deep why/when | Ties to presets + power limits |
| C6 | **Settings encyclopedia** | Optional thin pass — every toggle; can skip obscure ones | Later / thin |

### Explicit later / can skip first pass

Dev Tools, Portable/Deck-only deep quirks (unless Deck channel grows), full encoder theory, every filter chip, PRO unlock surface (own chapter when PRO ships).

### Writing order (aligned to waves)

1. **Site shell** — красивый landing + Docs nav/tabs + TOC  
2. **Wave A** (Quick + folders + queue + trim + Original vs re-encode short + health short)  
3. **Wave B** surfaces users already click  
4. **Wave C** parsers + DASH/mpd + Issue playback — last, fattest  

**Agent note:** Deep Wave C requires reading real code paths (markers / health / mpd repair / library meta) — don’t invent; document from source when writing those pages.

**Cross-link:** **§ Steempeg PRO (~v50)** · **§ ООООптимизация** · README stays minimal · release notes ≠ Docs · landing ≠ Deep bible.

---

## 📖 ~v40 *(other)*

- **Linux / SteamOS port** *(started)* — clip layout is the same as Windows (`userdata/<id>/gamerecordings/clips` + DASH `.m4s`/`session.mpd`). Done so far: Linux Steam root discovery (Deck/Flatpak paths), portable ffmpeg resolve, process kill, open file/log. Still open: Wayland mpv embed, Linux updater, packaging (`libmpv` + ffmpeg), Win32 chrome no-op already.

### Animations pack *(→ v44–v45; early slice now)*

We already have the animated progress / busy marquee (`AnimatedRenderBar`). Next layer is **interaction motion**, not more decorative noise.

| # | Item | Notes |
|---|------|--------|
| 0 | **Player transport press** | ✅ Early slice — play / ±skip via `press_feedback.py` |
| 1 | **Button press (прожатие)** | App-wide: short press-in, spring back. Shared helper for primary actions |
| 2 | **Hover settle** | Optional soft lift/brighten that matches press |
| 3 | **Tokenize** | Press duration / scale / easing in `design_tokens` |
| 4 | **Accessibility** | Respect reduced-motion / keep disabled states static |

**Later (v50+):** broader **appear/disappear fades** for liveliness (ClipCard, player header plaques, …) — not the press/hover pack above. See **§ UI fade / liveliness pack (v50+)**.

### Player header chrome *(v39–v40)*

Top strip near **Preview** badge / **Healthy** (clip health) controls.

| # | Item | Notes |
|---|------|--------|
| 1 | **Close button redesign** | ✅ v38dev — `cancel.png` tinted red, chip border matches Healthy/Preview; status group separated from actions by divider |
| 2 | **Gear next to close** | ✅ v38dev — ⚙️ emoji chip beside close in the actions group |
| 3 | **Playback quality menu** | ✅ v38dev — gear menu: Source / 1080p / 720p / 480p / 360p (mpv downscale only). Subtitle: *Does not affect export* |
| 4 | **Persist** | ✅ v38dev — `preview_quality` in settings.json; default = Source |
| 5 | **Magnifying glass (idea)** | Optional future control in the actions group: **Fit / Fill** toggle for the MPV surface, or quick “inspect frame” zoom. Revisit after gear + quality ship — might be redundant with fullscreen / window resize |

**Layout sketch:** `[Healthy] [Preview]  |  [⚙] [✕]` — status chips left of divider, actions right.

**Code touchpoints:** `library_tab.py` (close chip), player header / `btn_clip_health` / `label_playback_badge` layout in `app.py`, mpv quality flags in player controller.

### ООООптимизация *(v39–v40+, research + ship)*

**Goal:** make Steempeg feel fast where users lose patience: **library scan after Choose Folder** (today can sit 15–30s) and **render throughput**. Document real power limits so we do not overpromise.

#### A. Library / Choose Folder speed

| # | Idea | Notes |
|---|------|--------|
| 1 | **Profile the scan** | Time `scan_clips`, health checks, thumbnail discovery, UI grid insert. Find who eats the 15–30s |
| 2 | **Incremental UI** | Show first N clips immediately; fill the rest in background (skeleton / progressive load) |
| 3 | **Cache more aggressively** | Persist scan index + health + meta per folder; only rescans changed dirs (mtime / clip count) |
| 4 | **Defer expensive work** | Health / salvage probes / thumbnails on demand or after visible rows land |
| 5 | **Background thread** | Never block UI thread for folder walk; keep status busy marquee honest |

**Code touchpoints:** `library/controller.py` (`scan_clips`), clip health (`core/dash/health.py`), thumbnails.

#### B. Render speed and power limits

| Question | Today / answer |
|----------|----------------|
| **How do we speed up a render?** | NVENC when available (GPU encode). **Original** / stream-copy when no re-encode needed. Lower resolution / bitrate. Trim instead of full clip. Avoid CPU-only paths (libx264 / libsvtav1) on long 1440p clips |
| **Hard power limits?** | One FFmpeg job at a time per queue slot (batch is sequential). NVENC: usually **1–2 encode sessions** per GPU (driver / card dependent). CPU encode scales with cores but heats/therms. Disk: many tiny DASH chunks = I/O bound on HDD |
| **Steempeg bottlenecks** | DASH remux/re-encode (not GPU decode of preview), single active `RenderThread`, no multi-GPU scheduling yet |

| # | Ship candidates | Notes |
|---|-----------------|--------|
| 1 | **Encoder speed ladder UI** | See § Encoder speed presets below |
| 2 | **Smarter defaults** | Prefer NVENC + sensible speed preset by codec |
| 3 | **Optional 2-job NVENC** | Research only if Kartoffeln remain idle mid-batch |
| 4 | **I/O tips in How To** | SSD vs HDD Steam library; local extract folder |

### Encoder speed presets *(ultrafast … ultraslow)* *(v39–v40)*

**Yes, still relevant** for Steempeg when we **re-encode** (not for Original / `-c:v copy`).

| Family | What the ladder is | How it works |
|--------|--------------------|--------------|
| **CPU H.264/H.265** (`libx264` / `libx265`) | Classic: `ultrafast` → `superfast` → `veryfast` → `faster` → `fast` → `medium` → `slow` → `slower` → `veryslow` → `ultraslow` (x265 naming similar) | Faster = less CPU work per frame → **quicker encode, larger file / lower quality** at same CRF/bitrate. Slower = more search/tools → **better compression, longer wait** |
| **NVENC** (`h264_nvenc` / `hevc_nvenc` / `av1_nvenc`) | Presets `p1`…`p7` (fast → quality). Not called ultrafast; same tradeoff family | GPU encode; p1–p3 speed, p5–p7 quality. Steempeg today already pins some extras (e.g. `av1_nvenc` `-preset p4`, SVT-AV1 `-preset 6`) in `video_encoder_extra_args` — **not exposed as a user dropdown** |
| **AV1 CPU** (`libsvtav1`) | Numeric presets (lower number = slower/better) | Same speed vs quality curve |

**UI sketch:** Export settings → **Encode speed**: Fast / Balanced / High quality (map under the hood to x264 `veryfast`/`medium`/`slow` or NVENC `p2`/`p4`/`p6`). Default Balanced. Gray out or hide when codec is Copy / Original.

**Not the same as:** Share / Edit / Web named quality presets, or resolution presets (1080p / 1440p). Those pick **what** to encode; speed ladder picks **how hard** the encoder works.

---

## 🎬 Steempeg Family — mini-Vegas editor *(v50+ track, separate product)*

**Decision (July 2026):** the real editor is **not** a giant feature inside `steempeg`. Steempeg stays the **clip manager + preview + export** tool. The **mini-Vegas** lives as its **own app** in the same **product family** — like [mpv-org](https://github.com/mpv-org) ships `mpv`, `mpv.net`, `libmpv`, etc. as related repos, **not** one monorepo monster.

**Org model:** GitHub **Organization** (e.g. `steempeg-org`) with **one repo per job**. Steempeg repo does not absorb the editor codebase.

### Polyglot — right language per layer *(fast where it matters)*

| Layer | Language | Why |
|-------|----------|-----|
| **Editor shell / rich UI** | **Electron** (or similar web-tech desktop shell) | Timeline UX, panels, drag-drop, theming, rapid UI iteration — Vegas-like density without fighting Qt for every pixel |
| **Clip discovery & Steam glue** | **Python sidecar** | Reuse Steempeg brain: scan Game Recording folders, MPD repair, markers, Steam paths, health — same logic as today, exposed over IPC |
| **Playback & decode hot path** | **C++** | Frame-accurate scrub, fragment-native DASH read, prefetch, low-latency preview — mpv/libav territory |
| **Export / mux engine** | **C++** (+ FFmpeg) | Stream-copy segments, re-encode only at cut boundaries, batch export — must not block the UI thread |
| **Steempeg (this repo)** | **Python + PySide6** | Library, queue, one-click export, updater — ship fast, iterate daily |

**Rule:** pick the language that wins on **that** subsystem’s bottleneck — not “one stack to rule them all”.

### Product split

| App | Role | Opens |
|-----|------|--------|
| **Steempeg** *(this repo)* | Find clips → preview → trim → queue → export | “Send to Editor” later |
| **Steempeg Editor** *(future repo)* | Multi-track timeline, mute regions, replace audio, markers as edits | Clips via Python sidecar or `.steempeg` project file |
| **Shared libs** *(future repos)* | DASH manifest model, IPC schema, maybe `libsteempeg-dash` | Consumed by both apps |

Steempeg **does not** need to embed the editor. Handoff = path + sidecar meta (today’s rendered sidecars / trim JSON are early seeds).

### Editor feature north star *(mini-Vegas, not Premiere)*

- [ ] Fragment-native timeline — playhead = `(chunk index, offset)`; **zero-wait import** from `.mpd`
- [ ] Smart export — stream-copy untouched `.m4s`; re-encode **only** cut boundaries
- [ ] **Chunk-trim save** — trim in/out → **new DASH clip** (copied/sliced chunks + MPD), not a rendered file — early montage seed; see **§ Chunk-trim save**
- [ ] **Mute regions** on timeline (volume envelopes / simple mutes first)
- [ ] **Replace audio** track (game audio off, voice/music in)
- [ ] Multi-clip edits — concatenate fragment lists across sessions
- [ ] Segment cache — prefetch upcoming `.m4s` for long matches

**Cousins:** OBS fragmented MP4 (one file), NVR HLS on disk, browser recorders (cloud only). **Nobody** ships fragment-native desktop edit for Steam Game Recording today — that’s the moat.

### Likely repo map *(names TBD)*

```
steempeg-org/
├── steempeg              ← this repo (manager + export)
├── steempeg-editor       ← Electron shell + project UI
├── steempeg-sidecar      ← Python: clip scan, Steam paths, MPD repair (IPC server)
├── steempeg-engine       ← C++: decode, timeline, export graph
└── steempeg-protocol     ← shared IPC / project file schema (JSON or protobuf)
```

**Integration sketch:** Editor launches → talks to **sidecar** for “what clips exist on disk?” → **engine** for preview/export → Electron draws timeline. Steempeg can spawn sidecar once and reuse, or Editor bundles its own copy.

### What stays in Steempeg until then

- Timeline trim + markers + screenshots (preview-grade, not NLE-grade)
- Render queue & honest export
- “Open in Editor” stub / deep link when Editor exists
- DASH repair & salvage — **shared** with sidecar, not duplicated in C++

### Not this track

- Stuffing a full NLE into PySide6 inside `steempeg/` — rejected
- Monorepo with Electron + Python + C++ in one tree — rejected (release cadence & CI hell)
- Replacing Steempeg UI with Electron — Steempeg keeps Qt; Editor is the Electron app

**Band:** research + sidecar IPC in **v45+**; Editor MVP (**open clip → cut → export**) in **v50+**; mute/replace-audio wave in **v52+**.

---

## 🎬 DASH-native editing — technical backbone *(same band as Family above)*

Steam Game Recording is one of few **desktop** recorders that writes `.mpd` + `.m4s` on disk. Premiere / Vegas / Resolve won't open it. Steempeg today: MPD repair, MPV preview, init+chunk hover decode; **export still muxes monolith via FFmpeg**.

**DASH ≠ extra quality** — same encoded bytes split into ~3s chunks. Wins: crash resilience (last fragment dies), web-native playback in Steam CEF, instant open (manifest = timeline).

**Fragment-native engine (shared Steempeg preview + future Editor):**

- [ ] Virtual timeline — playhead = `(chunk index, offset)`
- [ ] Zero-wait import — read `.mpd`, no remux to scrub
- [ ] Smart export — stream-copy untouched segments; re-encode only cut boundaries
- [ ] Segment cache — prefetch upcoming `.m4s` for long matches
- [ ] Multi-clip edits — concatenate fragment lists across sessions

*(Supersedes the old standalone “v40–v50 DASH-native editor” section — now under **Steempeg Family**.)*

### Chunk-trim save — cut → new DASH clip *(v50–60, early montage seed)*

**Idea (Emily 10 Sep 2026):** same gesture as today’s **trim**, but the result is **not** a rendered MP4/MKV — it’s a **new clip folder of chunks** cut from the existing `.m4s` tree (plus a fresh / sliced `session.mpd` / `session_fixed.mpd`).

**Why it feels possible:** Steam already stores the timeline as numbered video/audio chunks + init; the MPD (especially repaired `session_fixed.mpd`) already knows start numbers, durations, and which files exist. A trim in/out maps to a contiguous (or near-contiguous) chunk range — copy/hardlink those `.m4s`, keep matching `init-stream*`, write a minimal MPD for the slice. Partial edge chunks may need a tiny remux/re-encode at boundaries only; interior chunks stay byte-identical.

**Product angle:** first real **montage starter** inside Steempeg (or the early Editor handoff) — keep working in fragment space, export to monolith later when you want Share/Edit/Web. Fast, disk-cheap vs full re-encode; still Steam-shaped so health/repair/preview paths can reuse today’s brain.

**Open questions (research when we build):**
- Exact in/out mid-chunk — stream-copy whole chunks vs boundary re-encode
- Audio stream alignment (`chunk-stream1-*`) vs video
- Where the new clip lives (sibling under recordings / Steempeg export root / “Clips from trim”)
- Library discovery + health for synthetic clips

**Band:** **v50–60**. Cross-link: **§ Steempeg Family** · smart export · trim memory · MPD repair.

---

## 💭 Ideas — v39.4+ backlog *(July 2026)*

### Single-instance guard

**Goal:** Only one `Steempeg.exe` process at a time by default.

| # | Item | Notes |
|---|------|--------|
| 1 | **Detect running instance** | Named mutex / lockfile / local socket on startup — if another Steempeg is alive, don’t silently spawn a second full app |
| 2 | **SteempegDialog** | «Steempeg is already running.» + **Bring to front** (focus existing window) · **Launch anyway** (danger / expert) · **Cancel** |
| 3 | **Launch anyway** | Escape hatch for stuck zombie process or dev — not the default button |
| 4 | **Second instance handoff** | Optional later: pass CLI arg / file path to the first instance instead of opening empty shell twice |

**Code touchpoints:** `app.py` early startup (before heavy Qt init if possible), `SteempegDialog` confirm helper.

### Global Settings button ✅ *(shipped — Settings v1)*

**Placement:** library footer after **Check for updates** → **Settings** → `SettingsDialog` (`steempeg/ui/settings_dialog.py`).

**Settings v1 (shipped):**

| Block | Control | Notes |
|-------|---------|--------|
| **Updates** | Check for updates on startup | Gates silent title-bar badge probe |
| **Shell** | Desktop / Portable | Persists `ui_shell`; applies next launch. ✅ «remember shell» / Ask on startup — landed in **40.1** |
| **Notifications** | Notify when render finishes | Key ready; OS toast still § OS notifications |
| **Hints** | Reset all «Don't show again» | Clears dismiss flags + refreshes empty-queue panels |
| **Logs / support** | Open logs folder · Clear cache… | Shortcuts into existing lifecycle helpers |
| **Performance** | Priority while rendering · Pause preview while rendering | Win priority class / nice; pause mpv for FFmpeg headroom |

**Not in Settings v1:** rounded icons, desktop «Render like portable», full Export/preview prefs (stay in Export / player gear), always-on High priority.

**Code:** `settings_dialog.py`, footer `btn_settings` in `app.py`, keys in `settings.json`.

**Title bar today:** About `(i)` + Settings (`settings2.png`) next to version. Silent **Update Available** chip when a newer release is found.

**v41 — title-bar Check for updates:** dedicated control in the top bar (next to About / Settings). Manual check opens Update Center; keep the silent badge chip. **Portable-first** (Desktop still has footer Updates).

### 🎯 v41 — final scope *(locked 27 Jul 2026)*

**Theme:** close the Portable/desktop kitchen band, then land **custom export presets** as the last major feature before v42.

Now shipping **40.3**. v41 is the next major — not a version bump yet, this is the **locked plan**.

#### Must ship (P0)

| # | Item | Notes |
|---|------|--------|
| 1 | **Title-bar Check for updates** | Next to About `(i)` / Settings. Portable-first; silent **Update Available** chip stays |
| 2 | **Custom marker images + CS2 pack toggle** | Steam CDN sprites ↔ **Steempeg CS2** hand-drawn PNGs (`assets/`). Settings tumbler for CS2 `app_id`. On clip list icons / CS2 count itch → **§ Marker Settings / On clip (v46)**. Optional strip overlay → **§ Markers on the strip (v46)** |
| 3 | **Scrollbar chrome (V + H)** | Always-visible dark-purple thumb; track like the soft lane under the timeline scrubber. Vertical app-wide + horizontal on neo/render panel — one language |
| 4 | **Custom export presets + queue rules** | **Closer of v41.** Named presets (save Export UI), apply to one/many jobs, per-job edit without changing the global panel. Rules/auto-apply if time in the same band. Write-up: **§ Custom export presets + queue rules** |

#### Should ship (P1 — same release if time, else 41.x)

| # | Item | Notes |
|---|------|--------|
| 5 | **Picture / image preview** | Still frames / marker art / release-note images — hover or strip; UX TBD |
| 6 | **Render settings tab icons** | → **v44 optional / v45** as **Neo tab icons** — Emily provides glyphs; **titles only inside neo/render settings**, not global chrome |
| 7 | **Settings visual wave (content only)** | Rounded game icons, log-level toggles (app / FFmpeg / MPV), other visual toggles. **Tabbed Settings layout → v42** (не всё в одном скролле) |

#### Explicitly not v41

| Item | Goes to |
|------|---------|
| Animations pack (прожатие / hover) | **v42** |
| Settings — separate tabs | **v42** |
| Dead-clip bundled donor pack | **v42** — fallback + first pack in-tree; expand coverage |
| Portable Choose-a-clip GRID / Render sheets | **v42** (Portable band) |
| Send clip to Steam friend | Icebox / kitchen toy — **not** a v41 promise |
| App localization (i18n) | Later — UI stays English |
| Remember Desktop / Portable | ✅ already **40.1** |

**Portable leftovers** from the theatre shell track can still land as 41.0 / 41.x patches without blocking the P0 table above.

### v42 — Emily kitchen list *(July 2026)*

| # | Item | Notes |
|---|------|--------|
| 1 | **Animations pack** | Full press/hover tokens → **v44–v45**. **Now:** press on player transport only (`press_feedback.py`) |
| 2 | **Settings — separate tabs** | ✅ Shipped (Main/Advanced rule) |
| 3 | **Dead-clip salvage: bundled donor pack** | ✅ Fallback chain + first pack harvested. Per-game `assets/donors/<app_id>/`. Expand coverage as new titles appear. § below |
| 4 | **Error sounds + center notification** | ✅ System OS sounds (no bundled SFX) + notification-center toast when minimized. Setting wired. § OS notifications |
| 5 | **Queue done — «ВИДОСИКИ ОТРЕНДЕРЕЛИСЬ»** | ✅ OS toast title on batch success while minimized. In-app batch dialog copy can stay as-is |
| 6 | **Clips Manager toolbar order** | Move **View** (Grid/List) to the **start** of the toolbar row; then **Choose folder** · **Refresh** · **\* N clips** count. Today View sits after sort/filter — reorder for scanability on narrow windows / Portable sheet |
| 7 | **Player timeline strip — taller** | ⏸ Parked — old height restored; no redesign mock yet |
| 8 | **Per-pane density** | ⏸ Rolled back (7 Aug) — pane×shell curve crushed desktop chrome. Needs a real design pass later, not a drive-by |
| 9 | **Update Center chevrons** | Replace flat `>` / down-arrow expand markers with proper chevron assets (consistent weight with the rest of the chrome) |
| 10 | **Cured icon redraw** | ✅ Already redrawn (Emily) — drop from active kitchen |
| 11 | **Fullscreen ESC hint polish** | ✅ Pill + Refresh font |
| 12 | **Timeline ruler +1px** | ✅ Shipped (ticks 5/11, font 9pt) |
| 13 | **Taller seek strip** | ⏸ Parked — old height restored; no strong redesign idea yet. Don't poke without a mock |

**Portable Choose-a-clip:** ✅ GRID-only already (no List toggle in portable). Desktop List → **Settings toy** (may land late **v45** or with **v47** densify prototype) → **full kill ~v50** (parasite UI; Emily hopes List gone by then).

**Animations pack:** full press/hover token wave → **v44–v45**. **Now:** press feedback on **player transport buttons only** (play / ±skip).

### Fullscreen ESC hint + timeline ruler polish *(→ v42 / 42.x)*

**Kitchen (3 Aug 2026):** Emily — polish while fullscreen / scrubbing.

| # | Item | Notes |
|---|------|--------|
| 1 | **ESC hint** | ✅ Pill (`border-radius: 18px`) + Segoe UI bold @ `footer_font` (Refresh face) |
| 2 | **Timeline ruler** | ✅ +1 px (ticks 5/11, font 9pt) |

**Не:** 42.2 fix-only dump — kitchen polish when touching player chrome.

### Per-pane density *(→ v42)*

**Decision (28 Jul 2026):** compute `UiDensity` from **each pane's own width**, not from the window's.

**The mismatch.** `on_main_window_resized` does `dense = density_for_width(self.ui.width())` and applies that one density everywhere. But the chrome it sizes lives inside panes whose widths are set by splitters, independently of the window. On a 2560 monitor `t = 1.0` → full COMFORT (`settings_content_w=646`, `neo_sidebar_w=220`), and then the user drags the center pane down to 500px while its chrome still demands 866. That is where the clipped icons and broken fonts come from — the pane is narrow, the density thinks it is wide.

**Measured floors (offscreen probe, 28 Jul 2026, window 1920):**

| Pane | `minimumWidth` | real `minimumSizeHint` | driven by |
|------|---------------|------------------------|-----------|
| `left_panel` | 596 | 840 | explicit min wins |
| `right_panel` (player column) | 0 | **659** | `bottom_v_wrap` 637 → `tab_video`/`tab_export`/`tab_audio` 666, `settingsContentWrap` 646, `SourcePathsBox`/`summaryCard` minW 562; `top_v_wrap` 624 → `TimelineCanvas` minW 583 |
| `render_queue_panel` | 0 | **483** | `queueToolbar` 449, `queueEmptyPanel` 430 |
| `main_splitter` | — | **1758** | sum of the above |

**Why this matters beyond cosmetics.** The shell needs **1758px** but the window minimum is **1280** — over-constrained by ~480px, so below ~1760 Qt pushes panes under their minimums and every splitter rule degrades. With pane-driven density the center floor drops to roughly 480 (COMPACT `340 + 118`) and the queue to roughly 300, putting total need near **1150** — under 1280. The compressed-mode problem dissolves instead of being worked around, and the floor-scaling fallback in `splitter_rules.py` (`_effective_player_floor`) can go away.

| # | Piece | Notes |
|---|--------|--------|
| 1 | **Density per pane** | `density_for_width(pane.width())` for the library, the player column and the queue separately; keep `chrome_equal` gating per pane so resizes still do not thrash styles |
| 2 | **Recompute on splitter drag** | Not only on window resize — pane width now changes without the window changing |
| 3 | **Reflow, don't only shrink** | Source Info stat grid is always 3 columns (`210*3+16` comfort, `108*3+16` compact). Go 3 → 2 → 1 with the **`FlowLayout` already written for the filters panel** |
| 4 | **Drop hard mins** | `SourcePathsBox` / `summaryCard` 562, `TimelineCanvas` 583 — these block reflow outright |
| 5 | **Stop shrinking text past legibility** | `dash_font=10`, `neo_nav_font=10` are already too small on a Deck at arm's length. Below a threshold **remove or relocate** content instead: neo sidebar → icon-only rail rather than 220 → 118 with 10px labels |
| 6 | **Fix double PPI** | `shell_layout_scale` already folds `ppi_f` into `t`, then `density_for_width` multiplies every pixel by `chrome_ppi_scale` **again**. On a 27″ 1080p screen that used to compound ≈ 0.61 (`0.78²`) and crush fonts. **Softened floor (16 Aug 2026, test build for Evolution):** `_PPI_SCALE_MIN` **0.78 → 0.90** so ~82 PPI (ASUS TUF VG279QM 27″ FHD) no longer clamps tiny vs Windows taskbar; Emily’s ~110 PPI 1440p ref stays ~1.0. Double-apply still worth killing later; floor raise is the quick readable fix. |

**Code touchpoints:** `ui_density.py` (`density_for_width`), `app.py` (`on_main_window_resized`, `_apply_ui_density`), `screen_metrics.py` (`chrome_ppi_scale`), `layout_defaults.py`, `widgets/flow_layout`.

### Future — app localization (i18n)

**Not planned for v41.** UI stays English for now. When we revisit (Russian, Spanish, …): Qt Linguist (`.ts` / `.qm`), wrap user-facing strings with `tr()`, ship language packs or per-locale builds. Marker prefs already keep `FRIENDLY_LABEL_RU` as a stub for future locale tables. No runtime language switcher until then.

### Export quality ladder — Divine / Goddess ✅

| Height | Label |
|--------|--------|
| 2160 (4K) | `2160p (Divine Quality)` |
| 4320 (8K) | `4320p (Goddess Quality)` |
| Any taller (12K / 16K / …) | `{Np} (Goddess Quality)` — injected from source height |

Generator: `steempeg/render/quality_presets.py`. Bitrate above 4320p scales from the 8K Ultra/High/Medium/Low table by pixel area.

### Update Center refresh *(v39.4–v40)*

**Pain today:** Release notes feel rough — images don’t load reliably (priority/fetch still broken), body text «подгружается» awkwardly, version list rows clip or misalign copy. Milestone **ℹ** icons feel stale.

| # | Item | Notes |
|---|------|--------|
| 1 | **Images first** | Fix release-notes image loader: priority queue, cache to disk, placeholder → fade-in; don’t block text on slow GitHub CDN |
| 2 | **Text load UX** | Skeleton or staged render for markdown body; no layout jump when notes arrive; sanitize without killing formatting |
| 3 | **Version list polish** | Row height, elision, badge alignment, selected-row contrast — list should not «корябить» on long titles |
| 4 | **Milestone icons** | Refresh **ℹ** / era icons in `release_catalog.py` — update existing milestones, add anchors for v37–v39 if missing |
| 5 | **Regression pass** | Rate-limit dialog + downgrade ack + notes scroll still work after loader rewrite |

**Code touchpoints:** `update_center.py` (`_render_release_notes`, image loader), `release_catalog.py` (`VERSION_MILESTONES`, teaser parsing).

---

## 💭 Ideas backlog (older — still valid, unprioritized)

See sections below for v32–v35 history, codec primer, icebox, research notes. Move items into version sections when we pick them up.

### Library & clips

| Idea | Notes |
|------|--------|
| **Steam on other drives** | Auto-scan `SteamLibrary` on D:, E:, … |
| **Steam `video\` roots** | Some setups use `gamerecordings\video` |

### Player & layout

| Idea | Notes |
|------|--------|
| **Hide the big bottom panel** | Superseded by **§ Portable / Steam Deck shell** (theatre + RENDER sheet) |
| **EXPORT on player bar** | Superseded by Portable **RENDER** button → full export sheet |
| **Buffering indicator** | Outside MPV surface only |
| **SteempegSheet / unified modal** | Frosted elevated sheet — also the host for Portable overlays |
| **Button press animations** | See **§ Animations pack → v42** |
| **Larger timeline hover preview** | **~v43+** (не 42.x hotfix). См. § ниже |
| **Marker trim offset** | **~v43+** Settings (не 42.x hotfix). См. § ниже |
| **Player footer text marquee** | Полоска у volume / speed — если текст не влезает, плавный скролл L↔R. См. § ниже |
| **Render panel bg + TrueDark themes** | Фон neo/render settings → как player `#2d2d2d`; позже TrueDark / OLED. **→ v46** (Emily 14 Aug). См. § ниже |
| **Fullscreen ESC hint polish** | **→ v42 / 42.x** — круглее + шрифт как Refresh. См. § Fullscreen ESC hint |
| **Timeline ruler +1px** | **→ v42 / 42.x** — ticks + цифры +1px. См. § Fullscreen ESC hint |

### Render presets & automation

| Idea | Notes |
|------|--------|
| **User presets — auto-apply** | Rules by health, game, folder, size → default export — see **§ Custom export presets + queue rules *(v41)*** |
| **Encoder speed ladder** | ultrafast…ultraslow / NVENC p1–p7 — see **~v40 § Encoder speed presets** |
| **Professional Mode (converter)** | Later / v45+ kitchen — HandBrake-style deep knobs; **free unlock** via **§ Steempeg PRO (~v50)**. См. § ниже |
| **Express render from new-clip notify** | Later / v45+ kitchen — notification → Portable-like window, clip preloaded, quick render. См. § ниже |
| **Library scan speed** | Progressive load + cache — see **~v40 § ООООптимизация** |
| **Render soak / fuzz harness** | **→ v45.1 DEV MODE** (was ~v43+). См. **§ v45.1** + § ниже |

### Professional Mode — converter deep knobs *(later / v45+ kitchen — давно давно)*

**Idea (Emily, long-standing):** optional **Pro Mode** for the converter — HandBrake-style surface with lots of obscure encode knobs that most people never need, but «кто-то» sometimes does. **Default Export stays simple**; Pro Mode unlocks the deep controls.

**Not the same as:** Settings Main/Advanced (app prefs), named Share/Edit/Web or user presets (recipes — the HandBrake *preset* pattern in § Custom export presets), or the encoder speed ladder (one Fast/Balanced/HQ dropdown). Pro Mode is the **gate** for the long tail of FFmpeg / codec knobs — not everyday path depth.

**Likely tenants when we open it:** icebox archivist codecs (FFV1, ProRes — see Codec primer), CRF/x264-tune-style toggles, filter graphs, two-pass, etc. — only if someone actually needs them; don’t invent knobs for sport.

**Unlock vehicle:** **§ Steempeg PRO (~v50)** — free Pro Mode unlock for people who want more than «just the render button». Same idea; PRO is the product-facing name / band.

**Band:** **later / v45+ kitchen** — не must-ship в 45. «Давно давно» idea, not «ship in 45 now». Ship-shaped around **~v50** as Steempeg PRO (still not a near-term must).

### Steempeg PRO *(v50 seeds → full unlock later — free Professional Mode)*

**Idea (Emily, 12 Aug 2026):** develop **Steempeg PRO** around **~v50** — a **free** unlock of **Professional Mode** (converter deep knobs / HandBrake-style surface) for people who want more than «just the render button». Ties directly to the parked **§ Professional Mode — converter deep knobs** note.

| # | Piece | Notes |
|---|--------|--------|
| 1 | **Default stays simple** | Everyday path = one-click / simple Export + presets. No Pro tax on normal users |
| 2 | **Free Pro unlock** | PRO = unlock the deep-knobs surface — **not** a paid tier / license wall (kitchen intent: free) |
| 3 | **Same knobs as Pro Mode** | Archivist codecs, CRF/tunes, filters, two-pass, etc. — only when someone actually needs them |

**v50 slice (Emily 6 Sep 2026):** only **small beginnings** — wire a **DEV Mode** toggle to enable PRO for **hidden eyes** (internal / QA). Not a public ship of the full converter surface; seeds + gate only.

**Splash / brand chrome (Emily 6 Sep evening · draft 11 Sep):**

| Piece | Notes |
|--------|--------|
| **PRO badge** | Simple **red rounded rectangle**, bold **PRO** — after the word **Steempeg** (not replacing the app logo). Widget: `ui/widgets/pro_badge.py` |
| **Title row** | `[app logo] Steempeg [PRO] vXX` — chip hidden unless seed on |
| **Splash wash** | Free: charcoal → soft **violet**. **PRO:** charcoal → **red**; bar + % + spinner tint red |
| **Gate** | Settings → Advanced → **Steempeg PRO (preview)** · env ``STEEMPEG_PRO=1`` · `steempeg_pro` in settings.json |
| **Not yet** | Full converter unlock · whole-app red theme · PRO slide-in motion |

**Status:** **draft in tree** (11 Sep) — Emily reviews look; polish in 50.x.

**Not the same as:** **§ Steempeg Family** mini-Vegas (separate editor product). PRO stays **inside this app** as converter depth, not a second NLE.

**Band:** **v50** = DEV seeds; full unlock + splash PRO chrome kitchen continues **v50+**. Cross-link: **§ Professional Mode** · **§ Startup / loading window** · **§ v50 ship band**.

### Render soak / fuzz harness *(→ v45.1 DEV MODE — was ~v43+)*

**Was:** script / headless CLI soak for render+queue regressions (whitelist combos: trim, bitrate, preset, fps, codec, queue chaos; ffprobe + target-size drift).

**Now:** Emily (14 Aug 2026) wants this as a real **app feature under DEV MODE**, not only an external one-off — and paired with **library filter/sort diagnostics**. Full kitchen: **§ v45.1 — DEV MODE diagnostics**. Does **not** block current **v45** Defer Queue work.

### Larger timeline hover preview *(~v43+)*

**Зачем:** на 2K scrub/hover preview крошечный рядом с timeline + markers chrome — плохо читается.

**Что:** увеличить hover preview для читаемости. **Свой** визуальный язык (не клонировать Steam killfeed cards). Опционально позже — convenience «trim from preview».

**Не:** 42.x hotfix dump — feature backlog.

**Style redesign (21 Aug 2026):** Emily restyles the floating thumb + timestamp — kitchen **§ Timeline hover preview style**. **v47 polish shipped** (font · size bump · thin themed border · trim scissors). Deeper redesign → **v50 maybe** (Emily 6 Sep).

### Marker trim offset *(v43 Settings — add)*

**Зачем:** маркеры бывают early/late; иногда удобнее начинать trim с небольшим lead-in до маркера.

**Что:** Settings — нейтральные имена, без «Steam-like» брендинга. Напр. **«Marker trim offset»** / **«Trim from marker: Exact | With lead-in»** (lead-in 1s / 2s). Default = **Exact** (текущее поведение).

**Band:** **v43** (вместе с date/TZ). Not the same as **§ Marker Settings / On clip (v46)** (dialog list icons / CS2 type-vs-instance count) or **§ Markers on the strip (v46)** (optional overlay placement).

### Date / time display + timezone *(v43 Settings — must)*

**Идея (5 Aug 2026):** в Settings — формат даты и времени (+ часовой пояс):

| Режим | Пример |
|-------|--------|
| **Locale / US-ish** | `12/03/01` · 12h AM/PM (как сейчас в Queue) |
| **EU day-first** | `29.12.2001` · 24h |
| **Server / ISO-ish** | `2000/12/22` · 24h |

**Где влияет:** Queue cards, library grid meta, filters Date/Time, Render History, status chips — один formatter.

**Band:** **v43 must** (Emily 5 Aug 2026). Portable Deck kitchen done → можно брать.

### MPVWrapper hard fix *(later / v45+ — Opus Max Effort)*

**Pain:** `MPVWrapper` / video surface embedding — chronically buggy since early Qt eras (~**v20+**). Splitter drag → surface floats / orphan mini-player; geometry re-pin on resize / move / show is fragile («physics not in chat»). Lives in `steempeg/ui/player/surface.py` + callers in `app.py` / player controller.

**Goal (when we take it):** one focused Max-Effort pass — re-pin video on splitter drag + window move/resize; kill orphan HWND/X11 surface; Linux native-embed path stays opt-in. Promote old v36 P3 «Splitter video stuck» here.

**Band:** **later / v45+** (Emily 10–11 Aug 2026). **Not a v44 must** — expensive to iterate; don’t block the v44 train. Still needs a dedicated high-effort session, not drive-by / 42.x hotfix.

### Player footer text marquee *(parked / low)*

**Что это:** под плеером рядом с volume/speed длинная строка (игра · пресет · bitrate · codec) на узком окне обрезается — идея была плавно катать текст туда-сюда (ping-pong), если не влезает.

**Band:** не приоритет; Emily не цепляется. Icebox / когда узкий footer реально бесит.

**Related (stronger itch):** **§ Smooth overflow marquee (ClipCard-first)** under **v46** — Emily wanted the soft hitch/delay «вертелка» back since **v42–v43**; prioritize ClipCard titles, not this footer strip.

### Desktop chrome: render panel bg + TrueDark *(v46 theme track — was ~v45)*

**Pain (3 Aug 2026):** панель Render Settings темнее player chrome («ямка»).

**Quick win (когда возьмёмся):** выровнять `BG_SETTINGS_PANEL` с player tab.

**Theme north star:**
| # | Theme | Notes |
|---|--------|--------|
| A | **Powerful customization** | Settings → Visual / Themes |
| B | **TrueDark** | одна тёмная семья без ям |
| C | **TrueDark OLED** | `#000` фон |

**Band:** **v46** (Emily 14 Aug 2026: think v46). Was **~v45** (5 Aug) — not current v45 next after Defer Queue. **Do not build in v45.**

### Volume / speed boost ceiling *(v45 — Emily 8 Aug 2026)*

**Today:** volume slider 0–100%; speed ~0.1x–5.0x (slider units 1–50, 10 = 1.0x). Baseline / “normal” stays **100%** and **1.0x**.

**Idea:** Settings (Player / Advanced) — optional **boost ceiling** so the same chrome sliders can go past normal:

| Control | Baseline | Optional max |
|---------|----------|----------------|
| **Volume** | 100% = unity | **150%** or **200%** (soft amp / gain into mpv) |
| **Playback speed** | 1.0x | extend ceiling similarly if useful (today already >1x; confirm UX vs volume boost wording) |

**Notes:** default ceiling stays **100%** volume so nobody gets surprise boost. Gradient track (green→yellow→red) already reads “hotter toward the right” — when ceiling >100%, mark the 100% tick or keep green→yellow through 100% and push red into the boost zone. mpv `volume` already accepts >100 on many builds — verify clamp in `set_vlc_volume`.

**Band:** **v45**.

**Status (14 Aug 2026):** **landed** — Settings → Visual → **Player controls** (`volume_boost_ceiling` 100/150/200, `speed_boost_ceiling` 5.0x/8.0x/10.0x slider units 50/80/100); live apply + Cancel restore; unity tick + red boost zone on `LevelGradientSlider`; soft-amp via existing perceptual `set_vlc_volume` (no hard clamp at 100). **Defer / leave Render Queue** also **landed**.

### Timeline / player strip size *(v45 — Emily 9 Aug 2026)*

**Was v44 kitchen P2 — deferred** so v44 stays on queue-first header + Render≈Portable.

| # | Item | Notes |
|---|------|--------|
| 1 | **User size** | Settings → Visual **Player timeline** / Strip size: **Small · Medium · Large** (scrubber strip + digit/tick ruler together) |
| 2 | **Baseline / default** | **Large** = today’s pre-pref height **and** stock default for new installs (Medium + low-PPI shrink squashed Evolution). Upgrading stores without the pref still migrate once to **Large** |
| 3 | **IA** | Visual tab. Live preview + Save; Cancel restores. Shared Desktop/Portable timeline widget |

**Band:** **v45** (with volume/speed boost ceiling).

**Status (13 Aug 2026):** **underway / landed** — pref + Settings combo + live apply on `CustomTimelineWidget` (`timeline_strip_size.py`).

### Defer / leave Render Queue *(v45 — Emily 10 Aug 2026)*

**Pain:** Queue already filled, you’re in queue mode (header follows queue context, `Render Queue (N)` / Start Queue), then suddenly need to preview or render **some other** video outside that batch. Today “leave” fights the queue-first chrome or risks feeling like you must Clear / lose the scheme.

**What:** Pause the queue scheme — **exit queue mode without wiping jobs**, do the one-off work, then **return** to the same queue later.

| # | Item | Notes |
|---|------|--------|
| 1 | **Defer / leave queue** | Explicit action: drop queue context (header / Render CTA back to library selection) while **keeping all queued jobs** + order |
| 2 | **Pause the scheme** | Not Clear — panel still holds the list; Start Queue can wait; user can preview / single-render something else |
| 3 | **Return later** | One click / CTA to re-enter queue mode with the same list (resume the scheme, not rebuild from scratch) |

**Band:** **v45** (with timeline strip S/M/L + volume/speed boost). **Not v44** — queue-first header just landed; don’t pile “leave and come back” onto that train.

**Status (14 Aug 2026):** **landed** — **Leave** / **Resume** next to History/Clear (desktop queue toolbar + portable rail). Leave drops queue-first header / Start CTA without wiping jobs or order; one-off preview/render uses library selection. **Resume** (purple) or a queue-card click restores the same scheme. Session-only (restart with jobs = queue mode again).

### Same clip multiple times — cycling queue badge digit *(v45 leftover — Emily 14 Aug 2026)*

**Status (14 Aug 2026):** **landed** — ClipCard queue badge cycles membership indices ~1/s when N>1; static when N==1. Title overflow **вертелка / marquee** stays **v46** (not this).

**Pain / itch:** Same video can sit in the Render Queue more than once. Today’s multi-membership hint leans toward finishing circles/dots on the card; Emily prefers something cooler.

**Decision lean:** When a clip appears **N times** in the queue, the ClipCard queue badge **cycles the digit** about once per second — `1 → 2 → 3 → … → N → 1 → …` forever — reflecting how many times / which queue indices that clip occupies. Prefer this over a static multi-dot / multi-circle finish if that was the older idea.

| # | Item | Notes |
|---|------|--------|
| 1 | **Cycling index digit** | ✅ Soft ~1s step through each membership index; loop forever while multi-instance membership holds |
| 2 | **Not static multi-dots** | Cooler than only “finishing” extra circles/badges for duplicates |

**Cross-links:** **§ ClipCard queue # + shelf corners** (v44 optional polish / desktop queue badges) · Deck **Queue index badges** (Choose-a-clip grid `1, 2, 3…`) · **§ Queue Ready badge** (header numbered status circle) · **§ Defer / leave Render Queue** (queue chrome still warm).

**Band:** **v45 leftover** — ✅ done after Defer; not a must-ship if it had slipped. Title marquee stays **v46**.

### Render History clear-on-open *(v45 — Emily 12 Aug 2026 — confirmed, non-critical)*

**Flow:** When a render **finishes**, a completion dialog appears (buttons include **OK** and **Open Render History**). While that dialog is open, the **Render Queue** still has the jobs. Leaving the dialog **any way** should clear / exit queue presentation; jobs are still **saved into Render History**.

**Bug:** Pressing **Open Render History** (instead of OK) does **not** clear the list even when the clear checkbox/pref is on. Other dismiss paths are fine — this is that button path only, not “history never clears at all.”

**Align with:** prefs like clear queue after batch (`always_clear_render_queue_after_batch` / «Always clear render queue after render») vs History **Clear all** / clear-history controls — don’t confuse **queue** wipe with **history** wipe; the miss is the post-render dialog’s **Open Render History** path.

| # | Item | Notes |
|---|------|--------|
| 1 | **Clear on Open Render History (pref on)** | Pref/checkbox on → leave completion dialog via **Open Render History** should clear/exit queue like other dismiss paths; jobs remain in History |

**Band:** **v45**. Non-critical — fine to skip 44.1 entirely for this.

### Player header / upper tab size *(v45 — Emily 10 Aug 2026)*

**Was backlog** — rethink height / padding / type of the upper player header (game title / «Select a clip to preview» chrome, status chips, queue badges).

| # | Item | Notes |
|---|------|--------|
| 1 | **User size** | Settings → Visual → Player header → **Size**: Small · Medium · Large (scales density `header_*` metrics) |
| 2 | **Baseline / default** | **Large** = today’s pre-pref height **and** stock default for new installs (Medium + low-PPI shrink squashed Evolution). Upgrading stores without the pref still migrate once to **Large** |
| 3 | **Density** | Composes with window density; empty vs filled keep equal `setFixedHeight` (no jump) |
| 4 | **IA** | Same Visual section as Layout. Live preview + Save; Cancel restores. Desktop + Portable shared header |

**Band:** **v45** (with strip S/M/L + defer queue).

**Status (13 Aug 2026):** **underway / landed** — pref + Settings combo + live apply (`player_header_size.py`); Volume / speed boost also **landed** (14 Aug); **Defer / leave Render Queue** also **landed** (14 Aug).

### Update Center rethink *(v45 - Emily 12 Aug 2026; mockup locked; labels polished)*

**Pain today:** versions + changelog crammed into one blob. List is a fat scroll of tags; notes dominate; backups are a combo/`vN (old_version_v*)` label + one «Restore local backup» that swaps the whole tree. Milestones exist in catalog (`VERSION_MILESTONES`) but barely surface - `(i)` tooltip + a thin marker line. Settings «Import from backup…» only merges `rendered_videos` / `Screenshots` / `cache` (skip existing) - no settings/presets/history pick, no sizes, no per-clip choose. Nicer than bare `v42 (backup)` labels.

**Interim (42.x):** bigger window on small res - не redesign. **Not v44.**

**Target IA (authoritative - Emily mockup 12 Aug 2026):** grow **wider**, not taller. Two-ish columns; backpack/migrate checkboxes live in the right pane (not a separate sheet in v1). Still Steempeg purple chrome.

#### Locked English labels (UI copy)

Sketch → ship names. No long dashes in UI strings; risk ranges use `to` (e.g. `v12.1 to v16`).

| Role | Locked label | Notes |
|------|--------------|-------|
| Dialog title | **Update Center** | unchanged |
| Carry-over group | **Keep when updating** | was sketch «What to save?» |
| Checkbox | **Videos** | was `vids` (rendered / library video content) |
| Checkbox | **Settings** | was `settings` |
| Checkbox | **Render history** | was `History` |
| Checkbox (later / optional 4th) | **Presets** | earlier Backpack plan; not on sketch - quiet add OK |
| Backup block title | **Backup** | shows e.g. `v30.2` |
| Backup restore CTA | **Restore vX.Y** | was «Go to v…»; `X.Y` = that backup’s version |
| Primary install CTA | **Update** | install selected release; use **Install update** only if context needs the longer verb |
| Open release page | **GitHub** | was `Github` |
| Risk ack | existing accept-risk pattern | same idea as today; no em dashes in new ack copy |

#### Layout (locked)

| Side | Contents |
|------|----------|
| **Left** | Title **Update Center** + short blurb · full **column of versions** available to update/select (v45, v44, v43, patches like v42.4…) · separate **Backup** block below (shows e.g. `v30.2`) · under Backup: button **Restore vX.Y** |
| **Right** | **Changelog for selected version** (must look nice) · **Keep when updating** checkboxes (**Videos** · **Settings** · **Render history**; optional **Presets**) · accept-risk acknowledgement · footer actions: **Update** \| **GitHub** |

**Ack:** under the checkboxes - existing accept-risk acknowledgement (same pattern as today), not a separate confirm-only flow for the chrome.

#### Version risk / eligibility chrome (locked)

- **Platform blocked:** selecting a version that can’t install here (e.g. Linux → not allowed) still works for browsing changelog; UI states clearly you **can’t install** on this platform.
- **Ancient versions:** messaging e.g. very old = minimum for update is **v12.1**, and even that is risky.
- **Visual banding in the version list:**
  - **Below v12.1** → slight **red** background («жопа» / don’t bother)
  - **v12.1 to v16** → slight **orange** background = risky update era (VLC-based; player was raw, no real fullscreen, theatrical max) - don’t need to keep offering those as normal targets; highlight as risky period
  - **Modern versions** = normal styling

Prior install-policy eras (v16+ stable · v12.1 to v15 risky · v12.0 blocked · v0 to v11 manual) stay the rules behind the chrome; banding makes them readable at a glance.

#### Prior vision still in scope (don’t lose)

- Not cramming everything into one blob; left rail + right detail.
- Backpack / migrate: **Keep when updating** checks (**Videos** · **Settings** · **Render history**; earlier plan also **Presets** / content + sizes).
- Beautiful selected-version story - not just `v42 (backup)`.
- Milestones data kept; presentation can stay quiet in first slice (chip later).
- **Restore vX.Y** on **Backup** is the explicit restore/jump entry (replaces burying restore in a footer combo).

#### First slice (v45 - move toward this layout)

Ship the **shell of the mockup**, not every migrate depth:

1. **Wide dialog** (grow horizontal).
2. **Left rail:** title + blurb · scrollable version column · **Backup** block + **Restore vX.Y**.
3. **Right pane:** nice changelog for selection · **Keep when updating** checks (**Videos** · **Settings** · **Render history**) · accept-risk ack · **Update** | **GitHub**.
4. **Risk chrome:** platform-can’t-install messaging + red/orange/normal banding (wire to existing policy where possible).
5. Do **not** yet: fancy home dashboard, per-clip content picker, multi-backup gallery, milestone redesign, auto-delete policies, full presets/content size matrix unless trivial.

#### Later slices

- **Presets** / content buckets + MB sizes (full Backpack depth).
- Per-clip / per-output content picker + delete/keep.
- Milestone chips / era chapters polish.
- Fold Settings «Import from backup» into this path (one migrate story).
- Optional home strip (update available CTA, backup health) if still wanted after the two-column home lands.

#### Open details (light - don’t block first slice)

- **Presets** checkbox - earlier Backpack plan; not on Emily’s sketch - quiet fourth check or later slice.
- Per-clip content pick - later.
- Exact on-disk map for **Videos** / **Settings** / **Render history** (and **Presets** if added).
- Discard backup after migrate? - later.

**Band:** **v45** start item - **IA + English labels locked**.

**Status (13 Aug 2026):** first slice **underway / landed** — wide two-column shell shipped (left versions + **Backup** / **Restore vX.Y**; right changelog + **Keep when updating** + **Update** / **GitHub** + ack). Polish / deeper migrate (Presets, per-clip pick, Settings import fold-in) still later slices. **Screenshots unified** first slice also **landed**. **Timeline strip S/M/L** first slice also **underway / landed**. **Player header size** S/M/L also **underway / landed**. **Volume / speed boost** also **landed** (14 Aug). **Defer / leave Render Queue** also **landed** (14 Aug).

**Code map (today):** `ui/update_center.py` · `ui/updater_mixin.py` · `services/release_catalog.py` (`VERSION_MILESTONES`, `find_local_backups`, install policy) · `services/backup_import.py` · `ui/update_confirm_dialog.py` · Settings Support import.

### ClipCard design modes *(v45 — Emily 11 Aug 2026)*

**Was v44 optional polish — moved to v45.** User choice in **Settings → Visual** (like `game_icon_shape`). Exactly **3** styles:

| Style | Notes |
|-------|--------|
| 1. **Square** | The style that existed **before v44** (pure square / older look) |
| 2. **SteempegUI** | **Current** look: top square, bottom square, what’s inside is round (avatar/badges/etc.) |
| 3. **Round** (Circle) | Everything round |

**Default:** **SteempegUI** (if already noted / current). Same rule in every library panel/shelf (Clips / Rendered / …).

**Screenshots:** TBD — skip for now.

**Band:** **v45**. **Not v44.**

### Settings IA — Main / Advanced *(rule + backlog)*

**Правило (Emily):** в **Main** только то, что меняет ежедневный поток работы. Всё остальное — **Advanced**, код/UX без галочки, или скин/фича плеера — не prefs.

**Не пихать (кал):**
- пустые «ускорители» без измеримого эффекта  
- дубли одной штуки (live preview + ещё 3 тумблера)  
- интервалы для того, что чинится кнопкой Refresh  
- микрокосметика UI как настройки (Trim outline, центр хедера как галочка) — это фича/скин  
- «дать больше мощностей PyAV/кодеку» без реального рычага  

**Поиск в Settings:** когда Main+Advanced раздуется (>~15–20 пунктов). До тех пор можно без лупы; позже `Search…` / ⌕ / 🔍 текстом, ассет не обязателен.

**Лупа в плеере:** не Settings. Tool таймлайна/маркеров (toggle / hold / Z+колесо). В Main не тащить; максимум Advanced `default zoom` — позже, после самого жеста.

#### Main (трогают не раз в год)

| Item | Status |
|------|--------|
| Default render tab (Video, не Source Info) | ✅ |
| Permanent export folder | ✅ |
| Notifications on/off (+ звук) | ✅ |
| Update check: off / daily / weekly | ✅ |
| Corner shape (game icons) | ✅ |
| Clear cache | ✅ (Support) |
| **Date / time + timezone** | ✅ Visual |
| **Startup library:** quick / full / skip | ✅ Performance |
| **Media cache size limit** (+ purge on clip delete) | ✅ Performance (+ behavior) |
| Preview workers / concurrency | skip — нет честного рычага пока |

#### Advanced (можно насрать, не врать что must)

| Item | Notes |
|------|--------|
| Icon refresh interval | skip — только Refresh |
| Hardware decode for preview | ✅ Advanced (MPV hwdec) |
| Confirm before delete | ✅ Advanced (clip / render) |
| Remember last library tab | ✅ Advanced |
| Screenshots folder | ✅ Advanced (PNG; quality later) |
| Default export preset | если пресеты уже в потоке |
| Marker trim offset | ✅ Visual (Exact / 1s / 2s) |
| Log levels (app / FFmpeg / MPV) | ✅ Support |
| Header layout (SteempegUI / Steam-like) | ✅ Visual — **→ Advanced** при редизайне (см. spike ниже) |
| ClipCard style | ✅ Visual — **Main** (ежедневная полка) |
| Player header size | ✅ Visual — **→ Advanced** |
| Timeline strip S/M/L | ✅ Visual — **Main** (Emily v45; player daily) |
| Volume / speed boost ceiling | ✅ Visual — **→ Advanced** (power-user; не каждый день) |
| Desktop render layout | ✅ General — **→ Advanced** |
| UI shell + ask on startup | ✅ General — **→ Advanced** (restart-required infra) |
| Render process priority | ✅ Performance — **→ Advanced** |
| Pause preview while rendering | ✅ Performance — **→ Advanced** |
| TEST NEW FULLSCREEN | ✅ Advanced — dev/experiment; не Main |

#### Уже не Settings

| Item | Куда |
|------|------|
| Trim outline / portable button polish | UX/code |
| Neo custom tab icons | **v44** / slip **v45** |
| TrueDark / themes | **v46** (was ~v45) |
| Player footer marquee | icebox |
| Magnifier / timeline zoom | player tool |
| Marker Settings (On clip / CS2 / Classes) | player dialog — **§ Marker Settings / On clip (v46)** |
| Markers on the strip (v20 overlay) | optional customization — **§ Markers on the strip (v46)** |

**Tabs сейчас:** General · Visual · Notifications · Performance · Support · **Advanced** (6 в коде; docstring `settings_dialog.py`). Notifications — паразит (1 чекбокс). Дальше **не плодить вкладки**; v46 #5 — Main vs Advanced **внутри** вкладок (секции / collapsible **Advanced ▾**), Search — когда Main+Advanced >~20 видимых строк.

#### Settings IA spike — inventory + proposed grouping *(18 Aug 2026 — v46 #5 — record only, do not build; Emily 20 Aug: still open, wants clearer explanation)*

**Owner:** Settings inventory + IA proposal for **v46 #5** (still open). Emily (14 Aug): dialog already **fills 2K** — problem is **sprawl**, not “add more rows”. **Emily 20 Aug:** wants a **clearer explanation** of how this redesign works before green-light — agent will explain in chat; leave open. Cross-link **§ v46** item #5 · #8 TrueDark. ~~#1 thumb cache~~ cancelled 20 Aug. TrueDark / Steam badges — other agents; this pass is kitchen only.

**Source of truth (today):** `steempeg/ui/settings_dialog.py` + `settings_prefs.py`. No UI rewrite in this spike.

##### Inventory snapshot *(Aug 2026 code)*

| Tab | Sections | Controls (~) | Notes |
|-----|----------|--------------|-------|
| **General** | Updates · Export · Render panel · Shell | 7 prefs + Restart | Export + default render tab = daily; Shell/restart = infra |
| **Visual** | Game icons · Library cards · Player header · Player timeline · Player controls · Date & time · Markers | **11 combos** | Longest tab; 8 section headers; live-preview on most combos |
| **Notifications** | Notifications | **1 checkbox** | Whole tab for one pref |
| **Performance** | Performance · Library startup · Media cache | 4 prefs | Mixes render tuning + library I/O |
| **Support** | Hints · Logs/support · Log levels · Import | 3 actions + 3 combos | Diagnostics + maintenance |
| **Advanced** | Fullscreen · Safety · Library · Screenshots · Preview decode | 5 prefs + folder row | Correct bucket; duplicates “Advanced” idea with Support logs |

**Total:** ~**35** persisted prefs + **6** actions (Browse/Reset/Clear cache/Open logs/Import/Restart). Hints: Visual repeats «Combo previews live; Save persists…» on **~8** rows.

##### 2K sprawl — biggest offenders

| # | Offender | Why it hurts |
|---|----------|--------------|
| 1 | **Visual tab monolith** | 11 combos × section headers × wordy hints → one endless lavender scroll on 1440p/2K |
| 2 | **Notifications tab** | Entire tab for a single checkbox |
| 3 | **Hint boilerplate** | Same live-preview paragraph copy-pasted per combo; doubles perceived length |
| 4 | **General = workflow + infra** | Export (daily) next to Shell + Restart (yearly / break-glass) |
| 5 | **Advanced vs Support overlap** | Power/diagnostic split across two tabs (log levels in Support; hwdec/logs path in Advanced) |
| 6 | **Misaligned Main rule** | Volume/speed ceiling + header layout/size sit in Visual **Main scroll** but aren’t daily-flow prefs |
| 7 | **Missing v46 homes** | TrueDark (#8) not wired yet — will make Visual longer unless IA lands first. ~~Thumb cache (#1)~~ **cancelled** Emily 20 Aug (viewport-lazy only) |

##### Proposed Main vs Advanced map *(v46 #5 target shell)*

**Shell (no new top-level tabs):** keep **General · Visual · Performance · Support** as the four “real” tabs. **Fold Notifications → General.** Retire standalone **Advanced** tab — fold rows into a collapsed **Advanced ▾** block at the bottom of the tab where they belong. Optional later: global **Search…** when visible rows >~20 (rule above).

| Tab | **Main** (expanded by default) | **Advanced ▾** (collapsed) |
|-----|--------------------------------|----------------------------|
| **General** | Check for updates · Permanent export folder · Default render tab · **Notifications** (moved from own tab) | Desktop render layout · UI shell · Ask shell on startup · Restart app (action stays near shell) |
| **Visual** | Corner shape · ClipCard style · Timeline strip size · Date format · Clock · Timezone · **Theme** *(slot v46 #8 TrueDark / OLED — picker here, not new tab)* | Player header layout · Player header size · Volume ceiling · Speed ceiling · Trim from marker |
| **Performance** | On launch (library scan) · Media cache size limit | Priority while rendering · Pause preview while rendering · Screenshots folder *(from retired Advanced)* |
| **Support** | Clear cache… · Open logs folder | Reset dismissed hints · App / FFmpeg / MPV log levels · Import from backup… |
| *(was Advanced)* | — | Confirm before delete → **Support Advanced** · Remember last library tab → **General Advanced** · Screenshots folder → **Performance Advanced** (library I/O) · Hardware decode → **Performance Advanced** · TEST NEW FULLSCREEN → **Visual Advanced** (experiment; loud label ok inside collapsed block) |

**Main row count (target):** ~**14** visible prefs + 2 primary actions (Clear cache, Open logs) — fits 2K without scroll on Visual if Advanced is collapsed and hints are trimmed.

**Hint policy (build pass):** one Visual footnote: *“Combos preview live; Save persists; Cancel restores.”* Drop per-row repetition.

##### Deferred / not Settings

| Item | Natural home when built | Notes |
|------|-------------------------|-------|
| **Screenshot thumb cache** (v46 #1) | — | ❌ **Cancelled** Emily 20 Aug — viewport-lazy only; do not add Settings toggle |
| **TrueDark / OLED theme** (v46 #8) | Visual → Main **Theme** section | Not a new tab; see **§ Desktop chrome: render panel bg + TrueDark** |
| **List view toggle** (Settings toy) | Visual → Advanced **Library** *(deferred)* | Emily: List is parasite UI → toy in Settings before **~v50** kill; **do not ship** in this IA pass |
| Marker Settings dialog | Player — not Settings | **§ Marker Settings / On clip (v46)** |
| Markers on strip overlay | Player / Visual Advanced later | **§ Markers on the strip (v46)** |

**Status:** spike / record — **do not build redesign** until Emily green-lights. Implementation track = **v47 #5** (moved from v46 evening 20 Aug); TrueDark still demo-v46 / ship-v47.

**Emily 14 Sep evening — veto / rethink:**
- **Does not like** the «fold tabs → 4 tabs + Advanced ▾» map. Prefers **many tabs**, each one **clear / self-explanatory**.
- Real itch is less IA collapse, more **interactive Settings** — e.g. live visual preview of custom art / chrome changes («что это такое, как визуально поменяется»). **Energy-expensive** → park; not a near-term build.
- Hint trim (drop obvious Updates copy; keep Export folder blurb) still fine as a **small polish** without the big regroup.
- Cross-link: **§ Dialog chrome DNA (think later)**.

---

### Custom export presets + queue rules *(v41 shipped core → v44/v45 UX depth)*

**Pain today (real):** The Export panel is a **global snapshot**. `add_clip_to_render_queue` / `build_render_job_from_ui` copies **whatever is on screen** (WebM, Original, 1440p, …) onto **every** clip you add. Multi-select 20 clips → 20× the same recipe. Changing the panel sitting for the next add; **already queued jobs do not update** (settings live on each `RenderJob`), but you still cannot mix recipes without fiddling the panel between adds.

**What Emily wants (reasonable — same pattern as HandBrake / Premiere / Adobe Media Encoder presets + queue overrides):**

| # | Piece | Notes |
|---|--------|--------|
| 1 | **Named user presets** | ✅ Save current Export UI as e.g. `Discord &lt;10 MB`, `1440p Ultra`. Store JSON. UI today: Create new preset · Save · Apply to panel · Delete · Saved presets list |
| 2 | **Apply preset → one / many jobs** | Right-click queue card(s): Apply preset `X`. Or toolbar: apply to selection / all pending |
| 3 | **Per-job edit** | Open job settings from queue (small sheet or bold row actions) so card 3 can be MP4 tiny while card 7 stays 1440p Ultra **without** changing the global Export panel for the whole app |
| 4 | **Rule-based auto-apply** | Optional: when adding to queue, pick preset by smart rules — e.g. estimated size / duration / game / health. Examples: `&lt; ~10 MB target` → Discord preset; `&gt; 100 MB source` → `1440p Ultra`. Rules are suggestive defaults the user can still override per job |
| 5 | **Default “add” policy** | Settings: (a) always use panel snapshot (today), (b) always use named preset `Y`, (c) evaluate rules then fall back |

**Not the same as:** Share / Edit / Web (built-in named quality styles) or encoder ultrafast…ultraslow (speed ladder). Custom presets are **Emily’s saved recipes + where they stick on the queue**.

**Code touchpoints:** `render_job_builder.py` (`snapshot_settings_from_ui`, `build_render_job_from_ui`), `RenderJob` / `RenderJobSettings`, `render_queue_panel` / grid context menus, settings JSON.

**Voice of reason:** Yes — teleжка идей нормальная. This bucket is high value and classic editor UX. Ship order that stays sane: **(1) per-job edit / apply named preset** → **(2) save/load presets UI** → **(3) rules**. Rules without per-job edit = more confusion.

#### Preset manager UX v2 *(Emily 8 Aug 2026 — after basic Save/Apply/Delete)*

**Pain with today’s plate:** you can **create** a preset, but day-2 questions are unanswered — modify? what’s inside? favourites? what when the list grows?

| # | Item | Notes |
|---|------|--------|
| 1 | **Modify / overwrite** | ✅ **16 Aug slice:** Select row → **Update** (overwrite from panel; rename-in-place if name field changed) + **Rename** without touching settings. Save as new still asks before clobber. |
| 2 | **What’s inside?** | ✅ Summary + expandable recipe strip on each row (`format_preset_summary`); queue Apply tips too. Dirty 16 Aug: chevron expand / collapse per row. |
| 3 | **Favourites / pin** | ✅ ★ Favourite / Unfavourite; pin order in `export_preset_favourites` (max 5); favourites-first sort (list + queue Apply menu). Dirty 16 Aug: ★ on row (chips strip may fold into rows). |
| 4 | **Scale when there’s a pile** | ✅ Search by name; favourites-first list. Dirty 16 Aug: row Apply ▾ (Update / Rename / Duplicate / Delete). Optional A–Z / recent sort dropdowns still deferred. |
| 5 | **Duplicate** | ✅ Duplicate → `Name (copy)` / `Name (copy N)`. |

**Band:** **v45 must-finish** (Emily 15–16 Aug — park Animations, ship this). First slice **committed unpushed**; polish still **dirty in tree**. IA stays on neo **Presets** tab (Export / Advanced path) — not Main Settings.

**Still deferred:** rule-based auto-apply / default-add policy (table above §); sort mode UI beyond favourites-first.

**Later kitchen (v48):** unify Standard quality ladder + Custom export presets in one categorized UX — see **§ Preset categorization + Video Settings access (v48)**.

---

### Dead-clip salvage: bundled donor pack *(→ v42)*

**Today (shipped ~v36 + v42 start):** Force play / salvage builds `session_salvage.mpd` from surviving chunks. If the clip’s own `init-stream0.m4s` is missing/corrupt, `_find_donor_init` borrows a valid init from a **healthy clip of the same game** already in the library, then falls back to **bundled** `assets/donors/<app_id>/` ([`steempeg/core/dash/donors.py`](../steempeg/core/dash/donors.py)). Harvest: `python tools/harvest_donors.py`. Still no donor for that `app_id` → **finita la commedia** (Nothing to salvage).

**UX copy:** Dead-clip / Force play dialogs say recovery needs a same-game donor (library **or** bundled pack); without any donor, salvage usually fails. Not “magic revive from thin air.”

**Why not one universal / “standard” donor file**

Steam Game Recording is DASH: many short `.m4s` **chunks** (compressed frames) plus `init-stream0.m4s` (the **codec passport** — SPS/PPS / equivalent). Without a matching init the decoder cannot read the chunks.

- Init is **not** a universal key. Different games (and often different encode profiles of the same game) produce different SPS/PPS, resolution, colour, even codec family. A CS2 init will not revive another title’s chunks — demux fails or paints garbage.
- Even one game drifts over time (Steam recorder / driver / HDR / resolution). A 2024 CS2 donor may not open a 2026 CS2 clip.
- Init does **not** restore pixels. Dead chunks stay dead. A mismatched init makes live chunks unreadable.
- Therefore the product is **`assets/donors/<steam_app_id>/init-stream0.m4s`** (optional audio init), **not** `donor_all_games.m4s`.

**Analogy:** PDF pages that are only JPEG payloads with no file header — a “standard” header from another document with different compression does not make those pages readable. Init is that header for a Steam clip.

**Status (v42):** Fallback chain + first harvested pack shipped in-tree (games present on Emily’s library). Expand coverage as new healthy donors appear.

| # | Piece | Notes |
|---|--------|--------|
| 1 | **Per-game donors, not one universal init** | ✅ Bundle `assets/donors/<app_id>/init-stream0.m4s` (+ optional audio init) |
| 2 | **Fallback chain** | ✅ (a) clip’s own valid init → (b) healthy library donor same `app_id` → (c) bundled donor for `app_id` → (d) give up |
| 3 | **How we collect donors** | ✅ `tools/harvest_donors.py` from known-good clips; keep files tiny |
| 4 | **No magic for unknown games** | ✅ If there is no local healthy clip **and** no bundled donor for that `app_id`, still finita |
| 5 | **Optional later** | User-import “donor folder”; community pack download (out of scope until bundled set works) |

**Code touchpoints:** `_find_donor_init` / `_build_salvage_manifest` in `library/controller.py`, `repair.recover_orphaned_clip`, `core/dash/donors.py`, `assets/donors/…` in the PyInstaller / portable asset bundle.

### Chrome & platform

| Idea | Notes |
|------|--------|
| **Hide Windows title bar in immersive** | Immersive works but native bar still draggable |
| **Localization** | UI mostly English today |
| **Real installer (vs zip-only)** | Later kitchen — packaging/distribution. См. § ниже |

### Real installer *(later kitchen — packaging/distribution)*

**Idea (Emily, 13 Aug 2026):** ship Steempeg as a **real installer**, not only a zip drop — **instead of** zip, or **in addition to** zip (GitHub Releases can keep both).

**Why:** zip extract is fine for power users and today’s Update Center pipeline; a proper installer is friendlier for first-time Windows installs (shortcuts, Start Menu, maybe uninstall / path pick). Distribution track, not a UI feature.

**Open questions:** MSI vs Inno vs NSIS / other; whether Update Center still prefers zip for in-app upgrade; Linux / Deck packaging stays its own track (~v40 port).

**Band:** **later kitchen** — packaging/distribution. **Not** a v45 must. Cross-link: Update Center zip path, icebox «fully portable mode», ~v40 Linux packaging.

### Express / quick render from new-clip notification *(later / v45+ kitchen)*

**Idea (Emily, 13 Aug 2026):** when a **new clip appears**, show a notification — «Want to render this clip?» She taps **Express** → it does **not** open the heavy Clip Manager / full library chrome. Instead open something **like Portable**, but with the **file already open** — no Clip Manager, no extra noise. Pure **quick express render**. Emily: genius idea.

**Flow sketch:**

1. New clip detected → OS / in-app notification («Want to render this clip?»)
2. Action: **Express** → lightweight Portable-like window, **clip preloaded**
3. Render from there (saved/default settings or Portable **Render** CTA) — skip desktop three-pane and Choose-a-clip sheet

**Not the same as:** full Portable launch gate / theatre shell as daily shell; **§ OS notifications** render-done toasts (different trigger — new clip, not job finished); v44 queue-first desktop header.

**Cross-link:** **§ Portable / Steam Deck shell** (reuse theatre surface + Render button; skip Choose-a-clip / library docks); **§ OS notifications** (same notify plumbing family, new-clip trigger).

**Band:** **later / v45+ kitchen** — park until Portable + notify paths are steady enough to bolt a preload path onto. **Not** forced as a v45 must.

---

## ✅ Shipped — v32 «Debuggability Update»

**Library & folders**
- Multi-folder library (`Choose Folder` + `+`, main + extra roots)
- Duplicate clips across folders ignored (newest wins)
- Clip health at scan time (healthy / issues / dead)
- Library filters overhaul (cascade, drag-select, games scroll)
- Locale-aware 12h / 24h times

**Debug & support**
- Logs menu (App + FFmpeg, MPV, open folder, clear logs / cache)
- Bug report dialog (description, log bundle, GitHub Issues shortcut)

**Render & playback**
- Per-clip trim memory (`clip_trim_state.json` + queue jobs)
- DASH playback / timeline accuracy fixes
- Bitrate detection & preset cap to source max
- Render queue context menu (select, open folders, remove)
- Immersive fullscreen (no Win32 fullscreen glitch)

**Polish**
- Folder picker pill UI, About disclaimer, styled menus
- Bottom summary: Mbps instead of «Original copy»

**v33 preview**
- Steam auto-discovery — registry path, first-launch auto-add, `🔍 Discover Steam folders…`

---

## 🎯 v33 — «Library & Queue UX» (shipped)

- Steam auto-discovery ✅
- Render Queue grid + job details on card
- Queue history ✅

---

## 🔮 v34 — «Export & Player depth» (shipped)

- Rendered exports shelf (tab from `+`)
- Timeline marker SVG / CDN sprites
- Collapsible export panel — partial
- Browser-style dockable panels — partial

---

## 🎨 v35 — «Export formats + honest bitrate» (shipped)

See **✅ Shipped — v35** at top. Custom chrome was **deferred to v36**.

---

## 📖 Codec primer & licensing *(reference)*

*Not legal advice — practical notes for FFmpeg bundling.*

### Containers

| Format | Typical use |
|--------|-------------|
| **MP4** | Universal — Discord, phones, social |
| **MKV** | Editors, archival, any codec combo |
| **WebM** | Web — VP9/AV1 + Opus |
| **MOV** | Apple / some editors |

### Video codecs

| Codec | License notes |
|-------|----------------|
| **H.264** | Patent pool; FFmpeg `libx264` GPL |
| **H.265** | Patent pool; hobby OSS ships it |
| **VP9** | Royalty-free |
| **AV1** | Royalty-free; slow CPU, NVENC on new GPUs |

### Audio codecs

| Codec | Notes |
|-------|--------|
| **AAC** | Patent; FFmpeg built-in `aac` OK |
| **MP3** | Patents expired |
| **Opus** | Royalty-free |
| **FLAC** | Royalty-free lossless |
| **WAV** | Uncompressed PCM |

**Copy** (`-c:v copy` / `-c:a copy`) — no generation loss when container fits.

### Icebox codecs

FFV1, ProRes — archivist / pro paths. Natural fit under **§ Professional Mode** when that gate exists (don’t dump into default Export).

---

## 🧊 Icebox

- ~~**Windows: first green restore after cold maximize may lack Aero**~~ — ✅ **fixed (Aug 2026):** root cause was `show()` then immediate `showMaximized()` — Windows never recorded a state change for DWM to reverse. Fix: maximize on the *first* show (`app.py`). Dropped unused `SetWindowPlacement` seed. Verified with screen-strip frame capture (first restore animated on Desktop + Portable).
- Library sort by clip health (Bad first / Good first) — partial in 34.x
- Grid queue drag-reorder with live preview
- Fully portable mode (settings relative to exe)
- GitHub Issues API from bug report dialog
- Parse every `libraryfolder.vdf` on all drives
- Parse Steam marker SVG phases (research bucket — largely solved via CDN in 34.2+)
- **«Full C++ video editor in one binary»** — Emily joke / fantasy slam; **not** planned work (Family stays separate-product; don’t treat as commitment)

---

## How to read sizes

| Tag | Meaning |
|-----|---------|
| **v36** | Design system + bugs/polish in this doc |
| **v36.1+** | Patch only if critical |
| **v36dev** | Private build for Emily + tester |

| Tag | Rough effort |
|-----|----------------|
| **S** | Hours, one screen |
| **M** | Days, one subsystem |
| **L** | Multi-week |
| **XL** | Research + unknown deps |

---

## Suggested priority (August 2026)

1. **v41 / v41.1 / v42** — already shipped or parked (density rollback, taller strip parked, etc.)
2. **v44 ship prep (12 Aug 2026)** — version bumped locally; kitchen P0/P1 landed; neo glyphs + reclaim; ClipCard SteempegUI/Square/Round shipped early (was v45). Still open before tag: library filter drag/persist if energy, animations pack leftover. **No mandatory 44.1** — skip unless a critical post-ship bug shows up.
3. **v44 also (if energy)** — animations pack (full) · **preset manager UX v2** if Export prefs itch · **library filter drag-select + persist** (Emily 11 Aug — high interest; see § Library filters)
4. **v44.1** — **skip unless critical** (Emily 12 Aug). Under-reveal not confirmed; don’t burn a patch for it.
5. **v45 remaining before ship (stop stuffing after these)** — large intermediate (v30/v40 scale). Already landed this band: Update Center first slice · Screenshots unified · Timeline strip S/M/L · Player header size · Volume/speed boost · **Leave/Resume Defer Queue** · **cycling queue badge** · **ViewModeChrome / Grid·List unify** · **Neo tab icons** · **library filter drag-select + persist** · **Preset manager UX v2** first slice (unpushed 16 Aug; dirty polish: expandable rows / Apply ▾). **Animations pack parked** (15–16 Aug). **TrueDark / render panel bg** → **§ v46**. **Desktop List → Settings toy** may slip **v47** densify / **~v50** kill. **Before tag:** finish/commit dirty Preset polish + ship prep (**45dev→45**, release notes, milestones if ready) — then **stop stuffing**. Non-critical if time: Render History clear-on-open. Screenshots Go to clip → **§ v46 #4**; Steam/Steempeg distinction → **§ v47** (was v46 #3).
6. **v45.1 (patch after v45 ship — Emily 14 Aug)** — **DEV MODE diagnostics**: Render Queue stress/fidelity reconcile (~100 jobs) + Library filter/sort verify. Interesting as an **in-app** power/dev feature — **not** blocking main v45 (Defer + cycling already done). See **§ v45.1**.
7. **v46** *(Emily **20 Aug 2026** evening)* — **Build:** **#2b** smooth overflow marquee («вертелка») ClipCard titles · **#9** fullscreen enter/exit icon wiring (asset `btn_exit_fullscreen.png` exists). **#8 TrueDark:** Desktop largely landed; **Portable polish → v47**. **✅ Wired:** #13 Rendering/Completed queue badge (assets + Ready-cluster paint). **✅ Done:** #4 open related clip · #6 capsule scroller · #7 ViewModeChrome · #10 Marker Settings / On clip · #11 Markers on the strip · **#14** Steempeg screenshot game logos · #17 1080p footer + Portable splitter. **Cancelled:** ~~thumb cache~~. **→ v47:** #2 denser ClipCards · #3 Steam vs Steempeg screenshot distinction · #5 Settings IA redesign · #12 Steam Deck controls · **TrueDark for Portable**. **Post-ship combo bugs → § v46.1**. See **§ v46**.
8. **v46.1 (minor patch — Emily 22 Aug 2026)** — kitchen / candidates: **TrueDark mid-apply** video overflow / layout flash (**before** Portable; settles when apply finishes; Windows loud) · ClipCard titles **clipped from the left** · TrueDark apply still **slow on Windows** (Linux fast). Portable may be separate/combo — not the first reading of the overflow screenshot. **Also shipping / just shipped:** *Like a Portable* **no middle splitter** — **4px air gap** (title-bar↔player-header style) instead of player↔dash drag handle. Opt-in restore → **§ Like a Portable middle splitter restore (v47)**. **Not** the v47 deeper Portable theme pass. See **§ v46.1**.
9. **v47** *(ship band — Emily **25 Aug 2026**)* — **✅ Shipped / in tree:** Smart Launch · Friendly FFmpeg errors · related-clip seek + VDF · Update Available never-again · Like a Portable middle-splitter opt-in · TrueDark Portable polish (About / Queue / Marker Settings / Export path) · timeline hover preview polish · player outline prefs · Render Settings open/close lag fix · markers parallel load · clip-open / tab / theater perf · splitter telemetry (Dev Mode). Deeper hover redesign → **v50+**. **Leftover kitchen moved → v48** (Emily 25 Aug): Deck library/queue · denser ClipCards · Steam vs Steempeg · Settings IA · right splitter jitter.
10. **v48** *(Emily **24–27 Aug 2026**)* — **Moved from v47 (25 Aug):** **Steam Deck controls** (library + queue) · **Denser ClipCards / List-kill prototype** · ~~**Steam vs Steempeg screenshot distinction**~~ ✅ tint shipped (27 Aug) · **Settings IA redesign** · ~~**Right splitter jitter / open-close**~~ ✅ Stage A (26 Aug) + **Stage B** (27 Aug — open→kiss custom + header/queue minHint). **Already on v48:** ~~Clip vanishes mid-render / active RQ~~ ✅ (27 Aug — job ERROR, stays visible) · **Steam Deck player controls** (ABXY player) · **DEV Mode gamepad button emulation** (Emily 27 Aug — required for QA without physical pad) · ~~Preset categorization + Video Settings access~~ ✅ (27 Aug — Standard/Custom) · ~~ClipCard marquee edge blur/fade~~ ✅ · ~~Timeline tick labels density~~ ✅ · Splitter movement telemetry (Dev Mode). **✅ Shipped (26 Aug):** **Pause playback plaque** (yellow + `pauserender.png`).
11. **v49** *(Emily **25–29 Aug 2026** — kitchen + first builds)* — **Resume update download** (HTTP Range + keep partial zip across network fails) · **Screenshots-style progressive library load** (default Progressive + Quick companion; Full for first/new folder; Smart dropped after timed test; scroll hitch known) · **Preset mini-editor** (create/edit recipes in a dedicated editor — not «tune Video Settings → Save as new») · **Marker Settings rethink** (classes / On clip / CS2 — rethink the model, improve the function) · **Deck controls v2** (Y → Trim · Render Queue rail nav · settings combo focus ring) · **Timeline preview cache — source frames on disk** (PyAV hover / batch thumbs: stop pre-«шакал» at decode; persist source-res frames, scale in UI; media cache GB cap + prune). Feasible ideas, not a ship commitment. See **§ Resume update download (v49)** · **§ Screenshots-style progressive library load (v49)** · **§ Preset mini-editor (v49)** · **§ Marker Settings rethink (v49)** · **§ Deck controls v2 (v49)** · **§ Timeline preview cache — source frames on disk (v49)** · cross-link **§ Smart Launch (v47)** · **§ Preset manager UX v2** / **§ Preset categorization (v48)** · **§ Marker Settings / On clip (v46)** · **§ Steam Deck controls (v48)** · **§ Timeline hover preview style**.
11a. **v49.1** *(shipped 5 Sep 2026)* — filter badge outside capsule · PyAV sniper speed · Render Settings light dash glue · Clip/Queue re-preview · Trim debounce / adaptive placement · yellow trim ring DWM.
11b. **v49.2 / next patch (kitchen — Emily 6 Sep 2026)** — **Delete clip while locked / playing** (WinError 32 on phantom DASH `.m4s` even after stop; must wait for unload today — want one-click delete: release handles, including during playback) · **After delete: library shows only ~20 clips** until Refresh restores full set · **First filtered clip: RMB context menu missing**. See **§ Delete clip / filtered RMB (v49.2)**.
12. **v50** *(Emily **6 Sep 2026** — thinking / ship band)* — see **§ v50 ship band (Emily 6 Sep)**. **Must / plan:** **Startup / loading window** (logo · version · progress strip **before** Progressive «Preparing workspace…») · **Corner-hover** (default **right = Render Queue**; left optional) · **Kill List** (gone by default; Settings opt-in restore only) · **Desktop About / Updates / Settings → title bar** (with Settings choice) · **Cache Steam DASH init bytes** (must) · **Filter badge polish** (must) · **Steempeg PRO** small seeds (**DEV Mode** toggle only — hidden eyes). **Maybe:** UI fade / liveliness · hover preview deeper redesign. **v50+ / later:** Smart Deletor · Screenshot Editor · combinable tabs · Steempeg Family · Never-show-again hover-only · full PRO surface — see individual §§.
12b. **v51 kitchen (Emily 14 Sep)** — **Click video → play/pause** · **Player loupe / zoom** (100/120/150%…, **v51–52**) · existing: splash progress bar · Hover RQ chrome · Clips≈Screenshots Medium · Screenshots List · PyAV source-frame cache. See §§.
12c. **v51.1 (patch after v51 ship — Emily 23 Sep)** — **Dead clips vanish** after adding a library folder · **dupes ignored / not written** · dead/health verification · **perf + delete garbage helpers** · Linux 50.1/51 zips **without WSL**. See **§ v51.1**.
13. **v45–v52 (rest)** — **MPVWrapper hard fix** (later / v45+) · preset/library leftovers · themes polish **beyond** first TrueDark pass (TrueDark itself is **v46**; acute TrueDark mid-apply / related → **§ v46.1**).
14. **Later kitchen (parked, not must)** — **real installer** (zip +/− installer packaging) · **Express render from new-clip notification** (notify → Portable-like preload → quick render) — see Ideas backlog §§

*(Player transport press anim already early; full animations pack stays v44–v45.)*

**Version branding:** Emily doesn’t care about burning a «43» — ship when ready as **44**.

---

## Library tabs and footer chrome (Emily 7 Aug 2026; clarified 10–11 Aug 2026)

**Pain today:** footer mega-pill always shows Choose Folder + Refresh (clips-oriented), even on Rendered videos. About / Updates / Settings stay; folder/refresh should follow the active tab.

**What «library chrome» means:** each library tab (**Clips** / **Rendered** / **Screenshots**) owns its own **Folder** picker + **Refresh** behavior and paths — not one global toolbar shared across all tabs. Switch tab → Folder/Refresh target and semantics follow that tab.

### Absorbed spike *(was «v43» — now ships under **v44**)*

| # | Item | Notes |
|---|------|--------|
| 1 | **Per-tab folder button** | Clips → Choose Folder. Rendered → Records folder (change export path; optional migrate later). Screenshots → Screenshots folder |
| 2 | **Per-tab Refresh** | ✅ Main Refresh scopes by active tab (Clips / Rendered / Screenshots). ▾ always offers **Refresh all**; Steam extras (icons/names/clip health) only on Clips; Rendered gets **Re-check rendered health**. Caveat: **Refresh all** still runs Clips’ heavy path (clear filter / close clip / queue deselect). See kitchen note 11 Aug 2026 |
| 3 | **Screenshots library tab** | New panel mode `screenshots` — grid of PNGs from `resolve_screenshots_folder` |
| 4 | **Screenshots card UX** | Compact photo cards + press/hover/selection; RMB **Open** + **Open folder**. Press animation should press the **whole screenshot card/block**, not only a thin strip |

### v44 / v45 — full overhaul (split if needed)

| # | Item | Notes |
|---|------|--------|
| 1 | **Tab-owned chrome** | Each tab owns Folder + Refresh (paths + behavior); show only when that content tab needs them |
| 2 | **Close all content tabs** | Allow zero tabs — only About · Updates · Settings (+ reopen via +). Today blocked at 1 tab |
| 3 | **Records folder migrate** | Ask Move existing files? on path change |
| 4 | **Refresh scopes menu** | This tab · All · Clips Steam maintenance |
| 5 | **Desktop List → Settings toy → kill** | Grid default. List → Settings toy (late **v45** or with **v47** densify) → **full remove ~v50**. Emily (13–14 Aug): List is crap / parasite UI. **Screenshots must not ship List** (Grid-only). |

**Band:** per-tab Folder/Refresh chrome starts in **v44**; slip close-all / migrate to **v45** if Screenshots spike eats the release. **MPVWrapper is no longer a v44 must** (→ later / v45+).

### Kill / hide List *(global — Emily 13–14 Aug 2026; **design lock 10 Sep 2026**)*

**Emily 10 Sep — how we actually kill List (not just hide the toggle):**

Replace **Grid / List** `ViewModeChrome` with a **card-size picker** (same energy as Render Settings **preset** tiles / Quality popup — one chrome control, pick a tile):

| Size | Footprint | Info |
|------|-----------|------|
| **Big** *(stock default)* | Today’s giant ClipCard (~254×184 + footer) | Full meta as now |
| **Medium** | ~Screenshots photo scale | Title + compact meta still fits |
| **Small** | Dense thumb grid | Meta **optional** — either none, or a small **ⓘ** whose hover/tooltip shows the full info (Emily TBD while building) |

**Surfaces (same language):**
| Surface | Notes |
|---------|--------|
| **Clips manager** | View Grid/List → **Size** Big/Medium/Small |
| **Rendered videos** | Same control |
| **Render Queue** | Today Grid/List; Emily: List looks better → migrate to **same size tiles** (likely Medium/Small stock for density). Grid/List chrome dies here too |
| **Render Settings** neo | Same strange Grid/List — fold into the **same** size picker pattern |
| **Screenshots** | ✅ **Size** Big/Medium/Small (11 Sep). **Medium = stock** (classic photo). Big ≈ Clips Big (time + size). Small ≈ Clips Small. **Still Grid-only** — List tile for Screenshots → **§ Screenshots List (v51)** |

**List fate:** **gone from the toolbar by default.** Optional **Settings → restore List** keep-a-way only if someone still wants the parasite (Emily 6 Sep). Prefer **not** to invest in List polish — sizes replace the need. **Screenshots List** (for the rare strip-fan) → **v51**, not stock.

**Chrome control sketch:** one button / pill (like preset chooser) → popup with **three preview tiles** (Big · Medium · Small). Persist per surface (`clips_card_size` / `rendered_card_size` / `screenshots_card_size` / `queue_card_size`).

| Surface / phase | Plan |
|-----------------|------|
| **Screenshots** | ✅ Size ladder (11 Sep); Grid-only until **§ Screenshots List (v51)** |
| **Clips / Rendered (Desktop)** | **→ Size picker** (10 Sep). List out of toolbar; Settings opt-in restore only |
| **v47 prototype** *(was v46; Emily 20 Aug)* | denser ClipCards — **absorbed** into Medium/Small sizes |
| **v50** | **Kill List by default** + ship **Big/Medium/Small** — see **§ v50 ship band** |
| **Render Queue** | **Same size system** (10 Sep expand) — List not a forever track |
| **v51** | Clips Medium ≈ Screenshots Medium · Screenshots List opt-in — see §§ below |

### v45 — Screenshots unified *(✅ first slice done — Emily 14 Aug 2026)*

**Pain (spike):** Screenshots tab listed files from `resolve_screenshots_folder` (Steempeg player shots) only. No game filter. List toggle was pointless. Press anim could feel like image-only, not whole card.

**Emily clarifications (13 Aug 2026 — authoritative):**

1. **Whole-card press** — entire screenshot card clickable/pressable (not tiny hit targets / thin strip)
2. **Game filters** — add filter-by-game (none today)
3. **Grid-only** — she doesn't understand why List is there; wants List gone later (Desktop → Settings toy / kill). Screenshots: Grid-first; hide/remove List here
4. **Unified shelf** — Steam + Steempeg screenshots in one place + game filter

| # | Item | Notes |
|---|------|--------|
| 1 | **Unified screenshot library** | ✅ **Steam** + **Steempeg** (clip-linked + not-from-clips) in one Screenshots grid — source tagging (Steam / Steempeg) |
| 2 | **Filter by game** | ✅ Detect game per Steam (`app_id` / userdata) + Steempeg (filename prefix / clip meta); filter chips like Clips/Rendered |
| 3 | **Whole-card press** | ✅ Press animation scales the **entire** photo card (ClipCard purple accent language) |
| 4 | **Grid-only (no List)** | ✅ Screenshots never offers List; hide List toggle on this tab |

**Band:** **v45**. Spike (Steempeg folder + photo cards + RMB) shipped under **v44**. First useful unified slice **landed** (13–14 Aug) — unified Steam+Steempeg scan · background Steam userdata walk · game filter popup · whole-card press · List hidden · **viewport-lazy** photo tiles (default; placeholders until visible + overscan; dematerialize far cards).

**Next after this slice (Emily queue):** Timeline strip S/M/L **landed** → player header **landed** → volume/speed boost **landed** → **Defer / leave Render Queue landed**. **TrueDark / render panel bg** slipped to **v46**.

**Parked still in Screenshots / library (not v46):**

| # | Item | Notes |
|---|------|--------|
| C | Steam game-name backfill beyond `games.json` | ✅ Local appmanifest + async Steam store fill; cards + filter chips update when names arrive; local logos when cheap |
| D | Clip-linked vs not-from-clips tagging depth | |

**Moved to v46:** **TrueDark / render panel bg** (Emily 14 Aug: think v46) · **Go to clip / open related clip** — see **§ v46**. Clearer **Steam vs Steempeg** distinction → **v47** (Emily 20 Aug evening). ~~Settings full/background thumb cache~~ — **cancelled** Emily 20 Aug (viewport-lazy only).

### v46 — Screenshots + shelf polish + TrueDark + Marker Settings + strip overlay *(Emily 14 Aug 2026; +13 Aug ideas; Marker Settings 17 Aug; strip overlay 17 Aug; **Emily 20 Aug 2026** decisions + **evening** queue clear)*

**Emily 20 Aug 2026 evening — build queue clear:** **v46 build = #2b · #4 · #9 · #10 · #11 · #14.** Move **#3** (Steam vs Steempeg screenshot distinction) + **#5** (Settings IA redesign) → **v47**. **#9** icon wiring now (asset `btn_exit_fullscreen.png` exists). **#13** Rendering/Completed queue badge ✅ wired (assets landed). Earlier same-day table: cancel #1 · densify ClipCards **→ v47** · #6/#7 ✅ · #8 unchanged · #12 still v47 plan only.

| # | Item | Notes |
|---|------|--------|
| 1 | ~~**Settings: full / background thumb cache vs viewport-only**~~ | ❌ **Cancelled / won’t do** (Emily **20 Aug 2026**). She can have **thousands** of screenshots (~**7000**); a full/background thumb cache would eat too much **disk/RAM**. **Viewport-lazy stays the only mode** (v45 default). Future agents: **do not implement** a Settings toggle or background all-thumbs cache. Was a named v46 item from 14 Aug — struck. |
| 2 | **Prototype kill-List via denser ClipCards** | **→ v48** (was v47; Emily **25 Aug 2026** leftovers). **уменьшение ClipCards** — shrink / densify Grid so List isn’t needed; Settings toy may land first; full kill ~**v50**. Pointer — **§ Kill / hide List** + Suggested priority **v48**. |
| 2b | **Smooth overflow marquee («вертелка»)** | ✅ **Do in v46 — build** (Emily **20 Aug 2026**). Wanted since **v42–v43**. When title/label text doesn’t fit: smooth marquee **forward… pause/delay… back… pause… forward…** with a soft hitch — not a harsh loop. **ClipCard-first** (titles/labels). Elsewhere optional / TBD. Cross-link icebox **§ Player footer text marquee**. **v46.1 candidate:** left-clipped titles under Portable+TrueDark — see **§ v46.1** #2. **Follow-up (v48 kitchen):** edge blur/fade instead of hard cutoff — see **§ ClipCard marquee title — edge blur/fade (v48)**. |
| 3 | **Clearer Steam vs Steempeg screenshot distinction** | ✅ **Done** (Emily **27 Aug 2026**). Steempeg-shot cards: light purple wash + idle ring + purple meta (`screenshot_photo.py`); Steam/chips untouched. Source tagging already from v45. No further badges/grouping unless itch returns. |
| 4 | **Open related clip from screenshot** | ✅ **Wired** (21 Aug 2026). RMB **Open related clip** on Screenshots cards → Clips tab + preview. Match: sidecar / `__clipfolder` suffix (new Steempeg captures) · Steam time-window vs clip · sole/app_id fallback. Unmapped / ambiguous → dialog or pick menu. Was parked **Go to clip**. |
| 5 | **Settings redesign — clearer layout / IA** | **→ v48** (was v47; Emily **25 Aug 2026**). Spike 18 Aug in **§ Settings IA — Main / Advanced**. Do not build until she green-lights. |
| 6 | **Library + Render Queue vertical scroller — slightly rounded thumb** | ✅ **Done** (capsule / rounded vertical scrollbar — Emily 20 Aug confirm). Was: library lavender thumb had square ends; timeline scrubber had pill ends — round V to match; same pass for Render Queue list scroller. |
| 7 | **Unify Grid/List chrome → Render Queue design** | ✅ **landed** (14 Aug) — shared `ViewModeChrome` on Clips / Rendered / Screenshots + Render Queue (same pill; Screenshots Grid-only). Keep ✅. |
| 8 | **TrueDark / render panel bg** | **Desktop largely landed in v46** (Emily 21 Aug evening). Quick win: neo/render settings bg = player `#2d2d2d`. Then TrueDark / TrueDark OLED `#000`. **Portable TrueDark polish → v47** — see **§ TrueDark for Portable (v47)**. Acute **TrueDark mid-apply** overflow/flash · ClipCard left-clip · Windows-apply slow → **§ v46.1** (not the deeper theme pass). Was: demo v46 / ship v47 (18–20 Aug). See **§ Desktop chrome: render panel bg + TrueDark**. |
| 9 | **Player fullscreen — distinct enter vs exit icons** | ✅ **Do in v46 — build** (Emily **20 Aug 2026 evening**). Asset exists: `assets/btn_exit_fullscreen.png`. Wire swap: enter = `btn_fullscreen.png`, exit (already fullscreen) = `btn_exit_fullscreen.png`. Theme-agnostic icon swap. |
| 10 | **Marker Settings / On clip** | ✅ **Done** (21 Aug 2026). On clip = **one row per instance** (icons like Classes) + type-apply count for shared game prefs. See **§ Marker Settings / On clip (v46)**. |
| 11 | **Markers on the strip (v20 overlay)** | ✅ **Done** (21 Aug 2026). Settings → Visual → Markers: **Markers on the strip** (default OFF). Overlay centers icons on the groove; shrinks marker-row chrome. Hover tooltip; **Ctrl+click** jumps (plain click scrubs). Key `markers_on_strip` in settings.json. See **§ Markers on the strip (v46)**. |
| 12 | **Steam Deck controls** | **→ v48** (was v47 plan; Emily **25 Aug 2026** leftovers). Extra input so you don’t poke the mid-screen scrollbar with the trackpad cursor. Full kitchen **§ Steam Deck controls (v48)**. |
| 13 | **Render queue badge — Rendering / Completed icons** | ✅ **Wired** (20 Aug evening). Assets: `completed.png`, `rendering.png`, `rendering_square.png`. Ready-cluster badge: Completed = static check notepad; Rendering = static cube + square spinning around it (tinted via BW→glyph pipeline like dash chrome). Cross-link: **§ Queue Ready badge** (v44 landed). |
| 14 | **Steempeg screenshot game logos** *(Emily 18 Aug screenshots **#7** / Point 3 leftover)* | ✅ **Done** (21 Aug 2026). Cards + Games-filter chips reuse `{appid}.jpg` when mapped. Point 3 reverse-lookup (exact / underscore-punctuation / fuzzy) kept; leftover pass: sidecar + `__clipfolder` app_id enrich, treat generic `Clip`/`Unknown` as placeholders so known app_id upgrades the title, `&`↔`and` normalize, filter chips re-lookup by name when catalog id empty. **Still unmapped (by design / missing data):** bare `Clip_*` shots with no sidecar and no `__clip_*` suffix; game labels absent from `games.json`; mapped app with no local `cache/{appid}.jpg` / Steam librarycache logo. **Do not rebuild the whole Games filter.** |
| 15 | **Screenshots filter sorting** *(Emily 18 Aug screenshots **#8**)* | Header **Sorting** stuck on **Default**; Games filter popup has **no sort controls**. Record only — **do not build now.** Separate from Point 3 logos. |
| 16 | **Player idle placeholder — no queue bleed** *(Emily 18 Aug **Point 9**)* | When **no clip is open** in the player: center placeholder shows **Steempeg logo stub** + **«Choose a clip to preview…»** — **not** the first queue job’s game icon/name (e.g. CS2). Player header must **not** show queue context game+logo while idle; queue preview belongs in **render dash only**. **Record only — do not build now.** Cross-link: **§ v44 kitchen — P0 Render Queue drives the player / header context** (queue-first chrome bug when nothing is loaded). |
| 17 | **1080p footer rearrange + Like a Portable splitter hover-reveal** *(Emily 21 Aug 2026)* | ✅ **Building / landed this session.** (1) Tight player footer: stack marker + marker-settings under theater/fullscreen; nudge Trim tools left when Trim active — rearrange, don’t shrink (`adaptive_trim_tools.py`). (2) **Like a Portable** only: hide splitter handles until ~1s hover near handle; **It's a Desktop** unchanged (`portable_splitter_reveal.py`). |

**Band:** **v46** (Emily **20 Aug 2026 evening** queue clear). **Build now:** #2b marquee · **#9 fullscreen exit icon**. **✅:** #4 open related clip · #6 · #7 · **#10 Marker Settings / On clip** · **#11** Markers on the strip · **#13** queue badge icons · **#14** Steempeg screenshot game logos · **#17** 1080p footer + Portable splitter reveal. **Cancelled:** #1 thumb cache. **→ v48 leftovers (25 Aug):** #2 densify ClipCards · **#3** Steam vs Steempeg · **#5** Settings IA · #12 Deck controls. Cross-link: **§ Kill / hide List**; Screenshots unified (v45); **§ Settings IA — Main / Advanced**; **§ Marker Settings / On clip**; **§ Markers on the strip**.

### Emily 18 Aug 2026 — screenshots + player chrome *(session 2)*

**Plan order (this session):** Points **1–3** done · **4** TrueDark deferred · **5** unified player block deferred · **6** screenshots status toast ✅ · **7–9** later.

| Point | Item | Status |
|-------|------|--------|
| 4 | **TrueDark** | **Desktop largely landed v46**; **Portable polish → v47** (see v46 table #8 · **§ TrueDark for Portable (v47)**). Acute combo layout bugs → **§ v46.1**. |
| 5 | **Unified player block** | **Deferred** until after Points **6–9** land. |
| 6 | **Screenshots status toast** | ✅ Purple accent (`ACCENT_PRIMARY` / `#b29ae7`) + **3.5s** auto-dismiss → Ready/queue chrome. `set_status` in `lifecycle.py` · `rendered_library._on_screenshot_game_names_finished`. |
| 7 | *(next)* | TBD this band. |
| 8 | **Screenshots filter sorting** | Record only — v46 #15. |
| 9 | **Player idle placeholder** | Record only — v46 #16. Cross-link queue-only chrome bug (§ v44 P0). |

### Marker Settings / On clip *(v46 — Emily 17 Aug 2026; **build** Emily 20 Aug; **done** 21 Aug)*

**Pain:** Emily: «тут чет не срастается» — Marker Settings (**On clip** / **CS2** / **Classes**) feels inconsistent. Not a **v45.1** bugfix. Later (21 Aug): CS2 clip with **50+** markers showed only a handful of **type-collapsed** rows; editing one “You killed …” row felt like it might silently hit all 20.

| # | Item | Notes |
|---|------|--------|
| 1 | **On clip list should show marker icons already** | ✅ Icons in the list (Classes-style), not only in the preview after selecting. |
| 2 | **CS2 marker count / type vs instance** | ✅ **One row per marker instance** on the clip (all kills/deaths/etc.). Game events still share prefs by Steam/legacy **type** under the hood — editor shows **“Applies to N markers of this type”**. Custom pins / screenshots stay per-instance. Help copy rewritten. |

**Status (Emily 21 Aug 2026):** ✅ **Done** (`clip_marker_setting_rows` instance rows + On clip icons + type-apply hint). Was green-lit 20 Aug.

**Band:** **v46**.

**Cross-link:** Marker Settings dialog (**On clip** / **CS2** / **Classes**) · **§ P5 — Custom timeline marker images** · **§ v41** Custom marker images + CS2 pack toggle · **§ Marker trim offset** (different — that’s trim lead-in, not this dialog) · **§ Markers on the strip (v46)** (placement on the seekbar vs a row above — separate from On clip list / type-vs-instance).

### Markers on the strip *(v46 — Emily 17 Aug 2026; **build** Emily 20 Aug)*

**Idea:** Bring back **v20-style markers on the progress bar** as an **optional customization** — not the forced default. Today’s strip keeps icons in a band **above** the groove (connector lines down to the track), which costs vertical height. Overlaying icons/numbers **on** the purple/gray seekbar was how strips first looked in **Steempeg v20**.

**Why / compromise:**
| # | Item | Notes |
|---|------|--------|
| 1 | **Optional overlay, not default** | “If you like it” toggle — **Settings → Visual → Markers → Markers on the strip** (default OFF). Keep the current above-strip row as the default so people who dislike on-bar clutter aren’t forced. |
| 2 | **Small-screen height** | No extra marker row eating player chrome. Overlay sits **on the groove** — useful on Steam Deck / short windows. |
| 3 | **Click vs scrub is awkward** | Emily named this: hit-testing icons on the same pixels as the seekbar fights scrub. **Shipped compromise:** hover tooltip + narrow hit; plain click scrubs; **Ctrl+click** (Meta on macOS) jumps. |

**Status (21 Aug 2026):** ✅ **Done** — optional v20 overlay in current `timeline.py` (not a smpeg20 port). Toggle + `markers_on_strip` in settings.json; careful hit-test as above.

**v20 technical memory** (`c:\Projects\Steempegold\smpeg20.py` — first custom strip):
- **Widgets:** `TimelineCanvas` (`QWidget`, ~L4635) is the inner canvas of `CustomTimelineWidget` (`QScrollArea`, ~L5210). Canvas `setFixedHeight(32)` — track + ruler ticks in one widget; **no separate marker row**.
- **Data:** `self.markers` list; `load_timeline_json` (~L4730) + `parse_event_to_icon` (~L4769). Icons via `get_icon_pixmap` (~L4801) — CS2 PNGs / glued round digits, `scaledToHeight(16)`.
- **Paint (the overlay):** `TimelineCanvas.paintEvent` (~L4895). Groove: `track_y = 2.0`, `track_height = 12.0`, fill `#b29ae7`. After track + ruler, loop `self.markers` (~L4968): `drawPixmap` at `icon_x = m_x - pixmap.width()/2`, `icon_y = max(0, int(track_y - 18))`. Comment said “above the stripe”; clamp to `y=0` put **16px icons on top of the 12px groove** (what the screenshot shows). Hover tooltip painted in the same `paintEvent` above the icon (~L4981).
- **Hit-test (the awkward bit):** `mouseMoveEvent` (~L5072) hitbox = icon width × `y ∈ [0, 20]`. `mousePressEvent` (~L5034): if `hovered_marker`, `force_jump(time_ms - 2000)` and **return** — blocks normal playhead seek. That’s why clicking markers on the strip fights scrub.

**Band:** **v46**.

**Cross-link:** **§ Marker Settings / On clip (v46)** (list icons + CS2 types vs instances — dialog, not strip placement) · **§ P5 — Custom timeline marker images** · **§ v41** Custom marker images + CS2 pack toggle · current `steempeg/ui/player/controls/timeline.py` (`draw_marker`: default row above groove with connector; overlay centers icons on track when `markers_on_strip`).

### Steam Deck controls *(v48 — was v47; Emily 25 Aug 2026 moved leftover)*

**Pain:** On the Deck build, browsing Clips / queue means hunting a **scrollbar in the middle of a 1280×800 screen** with the **trackpad-as-mouse** cursor. Tiny thumb, lots of travel, easy to miss. Extra **gamepad** input should move **focus / selection** so you rarely need that bar.

**Band history:** Was **v47** plan-only (Emily 17–20 Aug). **Emily 25 Aug 2026:** leftover v47 kitchen → **v48** (v47 ship band closed for polish). Player face buttons stay **§ Steam Deck player controls (v48)** sibling.

**Status:** **v1 + raw v49 shipped** (Emily 27 Aug evening). Bus + View/Menu/A/B/X/Y(Trim) + D-pad/L1/R1/L2/R2 sheet nav + Dev pad. Gated by **Settings → Advanced → Dev tools** (`deck_controls` / `dev_mode`). Real HID / Steam Input = later polish.

#### DEV Mode — gamepad button emulation *(required for QA — Emily 27 Aug)*

Emily has **no physical gamepad / Deck** on the Windows kitchen PC → cannot QA ABXY / D-pad / shoulders by hand.

**Need:** in-app **Developer Tools** surface to **emulate Deck buttons** (and optionally sticks as coarse N/E/S/W) into the same code path the real HID / Steam Input handler will use later.

| Piece | Notes |
|-------|--------|
| **UI** | Dev Mode tab/panel: grid of **View · D-pad · L-stick · STEAM(disabled label) · Menu · ABXY · R-stick · QAM(disabled label) · L1/R1 · L2/R2** — press = inject synthetic event |
| **API** | One internal bus, e.g. `steempeg.input.gamepad.emit(Button.A, down=True)` — real device + Dev pad both call it |
| **Do not emulate** | **STEAM** / **QAM `…`** as OS overlays (show as locked / “SteamOS only”) |
| **Optional later** | Virtual Xbox 360 pad via ViGEm / Steam Input desktop — only if in-app inject isn’t enough for Gaming Mode tests |
| **Band** | Spike with **§ Steam Deck controls / player controls (v48)**; can land Dev emulator **before** full Portable mapping |

**Cross-link:** `ui/dev_mode_dialog.py` · Suggested priority **v48** · sibling **§ Steam Deck player controls (v48)**.

#### What a Deck physically is

Handheld **PC** + **Xbox-style gamepad** + **two haptic trackpads**, 7" 1280×800. Not “a Switch with a mouse.” SteamOS: **Gaming Mode** (Steam compositor) vs **Desktop Mode** (KDE + real cursor). Steempeg today launches in **Desktop Mode** (`README` / `*_steamdeck.zip`); Portable shell is theatre-only.

Hold it landscape, screen in the middle — **Emily photo pass 27 Aug** (correct names):

| Side | What you see | Official name | Default SteamOS job |
|------|--------------|---------------|---------------------|
| **Left · top near screen** | Small “two windows / rectangles” | **View** | Select-like / view (library prompts often “options adjacent”) |
| **Left** | **Cross** (“крестик”) | **D-pad** | Directions — menus / WASD-like. **Not** ABXY. |
| **Left** | Stick | **Left thumbstick** (+ click = **L3**) | Move / look / scroll (game-dependent) |
| **Left** | Square panel | **Left trackpad** (haptic) | Touch + click; Desktop Mode ≈ **mouse** |
| **Left · bottom** | **STEAM** | **Steam button** | Opens **Steam overlay / Steam menu** — **OS; never bind for Steempeg** |
| **Right · top near screen** | **Three horizontal lines** ☰ | **Menu** (Options) | Start-like / options |
| **Right** | Diamond **Y / X / B / A** | **ABXY** (Xbox labels) | **A** south = confirm · **B** east = back · **X** west · **Y** north |
| **Right** | Stick | **Right thumbstick** (+ **R3**) | Camera / look / scrub (game-dependent) |
| **Right** | Square panel | **Right trackpad** (haptic) | Same family as left; often mouse / radial menus |
| **Right · bottom** | **Three dots `…`** | **Quick Access (QAM)** | Quick Access Menu (perf overlay, friends, TDP…) — **OS; never bind**. **Not** a second STEAM button. |
| **Top edge** | L1/R1 · L2/R2 · volume · power | Bumpers / analog triggers | Index fingers |
| **Back grips** | L4 / R4 (+ often L5/R5 on OLED) | Grip paddles | Extra; ignore v1 |
| **Also** | Touchscreen · gyro · speakers | — | Touch already works; gyro not needed for clip manager |

**Common mix-up:** left top is **View** (two rectangles), **not** three lines. Three lines ☰ = **Menu** on the **right**. Three dots `…` = **QAM**, opposite STEAM — leave both to SteamOS.

Official inventory also on [steamdeck.com/en/tech](https://www.steamdeck.com/en/tech) (Controls and Input). Steam Input can remap almost everything **per app** in Gaming Mode; Desktop Mode still exposes a standard gamepad HID + trackpads-as-mouse via KDE.

The **“square sensors”** = the two **capacitive haptic trackpads**. In Desktop Mode they **already are the mouse** — that’s the cursor used to poke the scrollbar.

ABXY ≠ D-pad. ABXY = four **action** buttons on the **right**. D-pad = **direction cross** on the **left**.

#### Repo today — already have / nothing yet

**Have (shell + channel, not input):**
- Portable / theatre shell: `steempeg/ui/portable/` (`sheets.py`, `queue_sidebar.py`, `chrome.py`)
- Startup: Deck zips skip chooser, default Portable (`shell_chooser.py`, `app.py`); Settings can still pick Desktop
- Layout floor 1280×800 (`layout_defaults.py` `STEAM_DECK_*`)
- Update channel `steamdeck` / `*_steamdeck.zip`
- Kitchen already waved at this: Portable P0 **Cursor + gamepad** (“D-pad / scroll after focus”) — **never spiked**. Old band line “gamepad multi-select polish **v44**” did **not** happen.

**Nothing yet (grep 17 Aug 2026):** no `QGamepad` / `QtGamepad`, no SDL / pygame / evdev / joystick, no Steam Input `.vdf` / action set, no `Key_Gamepad*`. `pyproject.toml` is PySide6 + mpv + PyAV + Pillow + psutil + requests — **no gamepad extra**. Qt widgets don’t even have a dedicated arrow-key grid-nav helper for library/queue.

#### Don’t fight the SteamOS compositor

Desktop Mode already gives Qt a **real mouse** from the trackpads via KDE. If we also bind those same pads as a gamepad axis, we **double-bind** (cursor + virtual stick fighting).

| Launch path | Who sees buttons first |
|-------------|------------------------|
| Dolphin / `.desktop` in Desktop Mode | KDE → Qt. Trackpads = mouse. Gamepad nodes exist (`event` / `js`) but Steempeg ignores them. |
| Add as **non-Steam game** / Gaming Mode | **Steam Input** can eat or remap buttons **before** Qt. Overlay (STEAM / QAM) stays Steam’s. |
| SDL / PySide gamepad in-process | Works if Steam Input is **passthrough** or we ship a Steempeg action set. Fighting the compositor = random missing A / stuck cursor. |

**Spike rule (when we build):** leave **trackpads as cursor**; bind **D-pad, sticks, shoulders, ABXY**. Prefer one stack, not three: **Steam Input action set** (if we want Gaming Mode / Big Picture launch) **or** SDL2 GameController **or** Qt — research on device; don’t stack all three. Qt6 `QtGamepad` is not in our deps and is a dying module; don’t bet the farm on it.

Optional later: a small **Steam Input** action set named Steempeg (Browse / Player / Sheets) so Deck users can rebind in Steam’s UI without us shipping a settings page first.

#### Draft Steempeg mapping *(v1 locked Emily 27 Aug 2026)*

**Problem framed:** scrollbar-in-the-middle is painful with cursor; **gamepad should move focus/selection** (library grid, queue list, sheet rows). Cursor stays for picky clicks (Settings, tiny chrome).

| Input | v1 bind | Notes |
|-------|---------|--------|
| **Both trackpads** | **Keep mouse / cursor** | Already works in Desktop Mode. Do not steal. |
| **View** | **Choose a Clip** | Opens Clips Manager sheet (`open_portable_clip_picker`). |
| **Menu** ☰ | **Render** | Opens Render settings sheet (`open_portable_render_settings`). |
| **A** (south) | **Play / Pause** (theatre) · **Confirm clip** (Choose a Clip) · **Activate focused control** (Render sheet) | Sheet paths wired v1. |
| **B** (east) | **Close top sheet** | Choose-a-Clip first, then Render sheet. |
| **X** (west) | **Add to queue** | Current export clip → RQ. |
| **Y** (north) | **→ v49:** **Trim** | Toggle / focus trim tools when clip open — Emily 27 Aug evening. |
| **D-pad** | **Choose a Clip:** ◀▶▲▼ card grid · **Render:** ▲▼ focus prev/next control; ◀▶ same as L1/R1 tab cycle | v1 shipped. |
| **L1 / R1** | **Choose a Clip:** Clips ↔ Rendered tab · **Render:** prev/next settings tab (Source…Presets) | v1 shipped. |
| **L2 / R2** | **→ v49+** | Page scroll / modifiers TBD. |
| **Right stick** | skip v1 | Fine scrub later. |
| **STEAM / QAM `…`** | **Leave to Steam** | Never bind. Dev pad shows locked. |
| **L4 / R4 / gyro** | Ignore v1 | |
| **Touchscreen** | Keep as-is | Finger tap already selects. |

**Code (v1):** `steempeg/input/gamepad.py` (bus) · `steempeg/input/deck_actions.py` (binds) · `steempeg/input/deck_navigation.py` (D-pad / L1/R1 / A in sheets) · Dev Mode tab **Deck pad** · `install_deck_actions(app)` from `app.py`.

#### Deck controls v2 *(v49 raw — Emily 27 Aug evening)*

**Shipped raw:** **Y → Trim** · **Render Queue** ▲▼ (L2 = queue zone, R2 = settings) · settings focus ring ▲▼ · opt-in **Settings → Advanced → Dev tools**.

**v2 polish (30 Aug):** purple **focus ring** on the current Render control (so combos are obvious) · combo **popup ▲▼** + **B** dismisses popup (not the sheet) · **Choose a Clip L2** toggles multi-select (D-pad adds cards; **X** queues all) · skip nested combo internals in the focus list.

**Still kitchen for v49 polish / v50:** Steam Input · stick scrub · Gaming Mode launch · hold-shoulder vs L2-toggle if a real pad feels better.

#### Build notes when spiked *(not now)*

| # | Item | Notes |
|---|------|--------|
| 1 | **Focus model** | Qt focus + explicit “selected card / selected queue row” so D-pad has somewhere to go. Today’s pain is **no focus target**, so the only browse gesture is drag-the-bar. |
| 2 | **Don’t steal trackpads** | Cursor remains valid; gamepad is extra, not a replacement. |
| 3 | **One input backend** | Steam Input **or** SDL **or** Qt — pick after a Deck spike; document Gaming vs Desktop. |
| 4 | **Portable first** | Theatre + sheets + queue sidebar. Desktop three-pane on Deck is not the reason for this work. |
| 5 | **Action set (optional)** | `steempeg.vdf` (or Steamworks file) so users rebind in Steam. |

**Band:** **v48**. v46 pointer only. **Player** face-button / no-stick-as-mouse mapping is sibling **§ Steam Deck player controls (v48)** (library/queue nav vs player ABXY — both v48 now; Emily 25 Aug moved leftovers).

**Cross-link:** **§ Portable / Steam Deck shell** (P0 Cursor + gamepad; P1 multi-select) · **§ Steam Deck player controls (v48)** · `steempeg/ui/portable/` · `shell_chooser.py` · `layout_defaults.py` · README Steam Deck / SteamOS.

### Timeline hover preview style *(v47 polish shipped — deeper redesign → v50 maybe)*

**Idea:** Restyle the **timeline hover preview** — floating thumbnail + timestamp under the scrub cursor (frame thumb + time like `01:46`).

**v47 shipped (Emily last polish, 25 Aug 2026):** chrome font (Segoe / `FONT_APP`) · slightly larger thumb+tip · thinner 1px themed frame · Default + TrueDark tokens · **trim zone** = yellow digits + scissors (`trim_icon.png`) left of time when hover is inside `trim_start`–`trim_end`. Do **not** disturb Portable hover sniper.

**Further redesign (Emily 25 Aug — «подумаю»; 6 Sep — still maybe):** deeper visual rethink of the tip → **v50 maybe** (not a must). Speculative; leave room.

**Not the same as:** **§ Larger timeline hover preview** (~v43+ size/readability backlog — v47 bump covers the acute 2K itch) · **§ Timeline / player strip size** (v45 S/M/L scrubber height — already landed).

**Band:** polish **v47**; deeper redesign kitchen **v50 maybe**.

**Cross-link:** **§ Larger timeline hover preview** · **§ Timeline / player strip size** · **§ v50 ship band** · player timeline strip (`timeline.py` / hover preview chrome) · Suggested priority **v47** / **v50 maybe**.

### Friendly FFmpeg errors *(v47 — Emily 21 Aug 2026 — kitchen / record only)*

**Idea:** When a render fails, Steempeg should **recognize common FFmpeg / OS error shapes** and show a **short friendly English line** under (or instead of) the raw log soup — so users aren’t left staring at encoder dumps alone.

**Examples (intent, not final copy):**
- `NOT ENOUGH MEMORY` / disk full / `ENOSPC` / “Cannot allocate memory” → e.g. “Storage or memory ran out — free some space and try again.”
- Other classes TBD (missing encoder, unsupported input, permission denied, …) as patterns surface.

**Status:** kitchen / record only — **do not build now.** TrueDark chrome for the error window can land earlier; this is the *friendly classification* layer.

**Band:** **v47**.

**Cross-link:** `_show_steempeg_render_error_dialog` (`render_controller.py`) · Dev Mode **Simulate FFmpeg error dialog** · Suggested priority **v47**.

### Smart Launch *(v47 — Emily 21 Aug 2026)*

**Idea (UI name: “Smart Launch”):** Don’t rescan the library top-to-bottom on every launch if folders are unchanged / no new clips. Launch from memory/cache when nothing changed; if something changed, load only the new clip(s) or rescan as needed.

**Status:** **Smart Launch — implementing** (4th On launch mode; roots fingerprint in `clips_library_cache.json`; unchanged → session snapshot; changed → snapshot + incremental / Quick fallback). Skip · Quick · Full kept.

**Band:** **v47**.

**Cross-link:** Settings → Performance → On launch (`startup_library_scan` / Smart · Skip · Quick · Full) · clips / rendered / screenshots session caches · Suggested priority **v47** · Emily reaction / alternative → **§ Screenshots-style progressive library load (v49)** («Smart Launch → Stupid Launch»).

### Open related clip → seek to screenshot time *(v47 — Emily 21 Aug 2026 — kitchen / record only)*

**Idea:** Enhancement to **v46 #4** (Open related clip from screenshot). When opening the related clip, seek / place the playhead at the **fragment / time where the screenshot was taken** — not just open the clip at `0`.

**Status:** kitchen / record only — **do not build now** (not trivial: parse capture offset from name/sidecar + seek after load).

**Band:** **v47**.

**Cross-link:** **§ v46 #4** Open related clip · `screenshot_clip_link.py` · Screenshots RMB **Open related clip**.

### Right splitter jitter / open-close *(v48 — ✅ Stage A shipped 26 Aug 2026)*

**Symptom:** Right splitter (**player | Render Queue**) has **jitter / strange open-close bugs**. **Left splitter is fine** — only the right one.

**Status:** ✅ **Stage A shipped** (Emily confirm 26 Aug) — mid-drag `_splitter_dragging` gates the 100ms snap/`sync_queue_minimum` floor slap; snap arms on right drag-end. ✅ **Stage B shipped** (27 Aug) — right handle **open→kiss** driven like left (hysteresis + swallow native `moveSplitter`); freeze player floor on press; pause header title elide/soft-min mid-drag; queue scroll `minimumSizeHint` elevates **height only** (cards no longer inflate horizontal floor). Stage C deferred unless a new verge case appears.

**Optional skim:** Opus splitter/player notes somewhere in `docs/` (player handbook) — maybe N/A (player-focused); right splitter issue is what matters. Skim if relevant; **primary suspects are RQ cards + non-min width drag-close.**

#### Suspect 1 (~99% Emily) — Render Queue job plaques/cards

Empty queue → **no** right-splitter bugs. With clips in the queue (**visual cards / plaques**) → jitter and weird bugs. Suspected **layout / min-size from queue cards fighting the splitter**.

#### Suspect 2 — snap/collapse when RQ was wider than minimum *(repro without needing cards?)*

Snap/collapse semantics break depending on **how wide RQ was** before close:

| # | Repro | Expected | Actual |
|---|--------|----------|--------|
| 1 | Open RQ at **minimum** width → close → reopen to minimum | Snap expand/collapse OK | **OK** |
| 2 | Expand RQ **beyond** minimum → hold **LMB** and drag toward close **without releasing** | Still snap / jerk open-close like normal Steempeg **verge** behavior | Weird openings: first opens as if it has **no snap collapse/expand concept**; instead it **drags gradually like a scroll** («свиток») — continuous scroll-drag, not verge snap |

#### Clear repro checklist

1. Confirm **left** splitter (Clips | player) still fine under the same window.
2. **Empty RQ:** open/close right splitter — should stay clean (supports Suspect 1).
3. **Add clips to RQ** (visible job cards) — open/close / verge drag — watch for jitter (Suspect 1).
4. Open RQ at **floor/min** → close → reopen → verify snap still OK (Suspect 2 baseline).
5. Widen RQ past min → LMB-hold drag shut without release → reopen/drag again — watch for continuous «свиток» instead of snap (Suspect 2).

**Band:** **v48**.

**Cross-link:** **§ Desktop splitters — five states + verge kiss** (v41.1 shipped) · `ui/splitter_rules.py` · `render_queue_panel` / queue job cards · Suggested priority **v48**.

### TrueDark for Portable *(v47 — ✅ largely shipped 25 Aug 2026)*

**Idea:** Polish / finish **TrueDark** for the **Portable** version/shell. **Desktop TrueDark** largely landed in **v46**; Portable theatre chrome / sheets match the dark family.

**Shipped in v47 tree (25 Aug):** About card · Queue buttons/cards · Render strip · Marker Settings · Export destination path · live theme retint. Spot leftovers OK on Linux QA.

**Not the same as v46.1:** acute mid-apply overflow/flash / ClipCard left-clip / Windows apply slow stay **§ v46.1**.

**Band:** **v47** (ship).

**Cross-link:** **§ Desktop chrome: render panel bg + TrueDark** · **§ v46** #8 · **§ v46.1** · **§ Portable / Steam Deck shell** · Suggested priority **v47**.

### Update Available plaque — never show again *(v47 — Emily 22 Aug 2026 — ✅ shipped)*

**Idea:** On the title-bar **Update Available** plaque / badge (silent chip when a newer release is found), add a **checkbox / preference** so the user can choose to **never show it again** — dismiss permanently / “don’t show Update Available”.

**Status:** **✅ shipped in v47** — plaque checkbox + Settings toggle (`hide_update_available_badge`). Manual Check for updates / **Update Center** stay available.

**v50 follow-up:** checkbox should not sit visible by default — see **§ Update Available «Never show again» hover-only (v50)**.

**Band:** **v47** (shipped) · polish → **v50**.

**Cross-link:** title-bar **Update Available** chip · `window_chrome.py` (`chk_never_show_update_available`) · **§ Update Available «Never show again» hover-only (v50)** · **§ Update Center** · Settings **Updates** · Suggested priority **v47** (done).

### Like a Portable middle splitter restore *(v47 — Emily 22 Aug 2026 — kitchen / small polish)*

**Context (46.1):** *Like a Portable* ships / just shipped with **no middle splitter** — player↔dash joint is a **4px air gap** (same language as title-bar↔player-header gap), not a drag handle.

**Idea:** Checkbox / setting to **bring back the middle splitter** in *Like a Portable* — opt-in restore of the player↔dash drag handle. **Default stays gap-only** (46.1 behavior).

**Status:** kitchen / record only — **do not build now.** Small polish for **v47**, not a 46.1 must.

**Band:** **v47**.

**Cross-link:** Desktop layout *Like a Portable* (v44 P1) · **§ v46.1** · **§ Right splitter jitter / open-close (v48)** · Suggested priority **v47** (shipped opt-in).

### Clip goes missing mid-render / active RQ *(v48 — Emily 24 Aug 2026 — ✅ shipped 27 Aug)*

**Pain:** Clip **vanishes** / becomes **Dead** while **rendering** or sitting in an **active Render Queue**.

**Shipped behavior:**
| Case | Result |
|------|--------|
| Source folder missing or uncured **Dead** at job start | Job → **ERROR** (stays visible); batch **auto-continues** next queued |
| No playable `session.mpd` | Same — ERROR + continue (no longer stops whole batch leaving QUEUED) |
| Clip **deleted** in library while queued | Matching **QUEUED** jobs → ERROR *Source clip folder is missing.* |
| Clip deleted / gone **mid-encode** | Active FFmpeg aborted as **ERROR** (not user Cancel / re-queue); existing batch Continue/Stop dialog |
| User Cancel | Unchanged — job back to QUEUED, batch stops |

**Not:** separate Dead job status; jobs stay on the ERROR plaque language.

**Band:** **v48**.

**Cross-link:** `render_controller.py` (`_queue_source_unavailable_reason` · `_fail_queue_job` · `_on_queue_source_removed`) · `delete_clip` / `delete_all_dead_clips` · Suggested priority **v48** · sibling **§ Pause playback plaque (v48)**.

### Pause playback plaque *(v48 — Emily 26 Aug 2026 — ✅ shipped)*

**Idea:** Player-header status plaque family: **In queue** · **Rendering** · **Completed** · **Paused** · **Error** · **Canceled**.

**Shipped:**
- **Paused** — yellow `#ffcc00` + tinted `pauserender.png` while dash Pause suspends encode.
- **Error** — red `#ff4444` + **untinted** `issue.png`; latched on failed clip; batch Continue clears plaque (job stays ERROR); Stop keeps it.
- **Canceled** — coral `#ff6b6b` + tinted `cancel.png`; visible while cancel dialog is open until OK.

Ready-cluster digit language unchanged.

**Band:** **v48**.

**Cross-link:** `update_playback_badge` / `_playback_badge_for_context` (`render_controller.py`) · **§ v46** #13 Rendering/Completed queue badge · Queue Ready / Leave / Pause dash · Suggested priority **v48** · sibling **§ Clip goes missing mid-render / active RQ (v48)**.

### Steam Deck player controls *(v48 kitchen → v49 Console mode)*

**Idea:** On **Steam Deck**, use **face buttons** for player controls — **not** stick-as-mouse.

**Status (30 Aug 2026):** **Console mode** landed — Settings → General → Shell → **Console mode (gamepad)**. Default **on** for `steamdeck` builds, **off** for Windows / Linux. Key still `deck_controls`. Dev mode still enables pad for QA. **App Settings** dialog also has pad nav (L1/R1 tabs · ▲▼◀▶ fields · A activate · B close) — same language as Render sheet.

**Theatre map (no sheet):** A play/pause · Y trim toggle · L1/R1 ±15s · R2 fullscreen · in trim X/A = start/end · L2 jump to trim start · X (trim off) = queue · View / Menu = sheets.

**Next (Emily):** a **simpler Console style** — only ▲▼◀▶ focus like PlayStation home (every control is a selectable object). Full mapping stays the current Console variant until then.

**Cross-link:** **§ Steam Deck controls (v48)** · `steempeg/input/deck_actions.py` · `deck_navigation.py` · `settings_prefs.load_deck_controls` / `default_deck_controls`.

### Preset categorization + Video Settings access *(v48 — Emily 24 Aug 2026 — kitchen / record only)*

**Pain today:** **Quality Preset** (Video Settings) is a flat ladder — Original, 1440p…144p, Target File Size. **Custom export presets** live under the neo **Presets** tab with Apply. Applying one saved recipe to one clip means a trip to Presets — awkward when Video Settings is already open.

**Idea — two categories:**
1. **Standard presets** — immutable Steempeg quality standards (built-in; not user-editable as “custom”)
2. **Custom presets** — user-saved export presets (existing Save / Apply / Delete / favourites track)

**UX:**
- **Presets tab** = **manager only**. Apply from there is fine, but must not be the only path.
- **Video Settings → Quality Preset** dropdown lists **both Standard and Custom** so you can apply without opening the Presets tab.
- In the **Presets** manager UI: section/split — **Standard** (shown simply) vs **Custom** (rows show **extra information** / more detail than standard).

**Goal:** unify the standard quality ladder + custom export presets into one categorized UX.

**Status:** ✅ **Shipped** (Emily **27 Aug 2026**). Video Settings → Quality Preset lists **Standard** (ladder + Target) and **Custom** (favourites★ first); picking Custom applies the full recipe. Presets manager shows **STANDARD** / **CUSTOM** sections — Standard rows are Apply-only (immutable); Custom keeps expandable ★ / Apply ▾ CRUD. Search filters both.

**Band:** **v48**.

**Cross-link:** `quality_presets.py` · `_rebuild_quality_preset_combo` / `on_quality_preset_combo_changed` · `StandardPresetRow` · Suggested priority **v48**.

### ClipCard marquee title — edge blur/fade *(v48 — Emily 24 Aug 2026 — kitchen / record only)*

**Pain:** Moving/scrolling game title text on ClipCard (overflow marquee / «вертелка») currently **hard-cuts** at the edge («разрыв, обрыв»).

**Idea:** **Blur/fade** at the card edges so scrolling text soft-fades instead of a sharp cutoff.

**Status:** kitchen / record only — **do not build now.**

**Band:** **v48**.

**Cross-link:** **§ v46 #2b** smooth overflow marquee («вертелка») · **§ v46.1** #2 ClipCard titles clipped from the left · Suggested priority **v48** · sibling **§ Timeline tick labels — density / overlap (v48)** · **§ Clip goes missing mid-render / active RQ (v48)** · **§ Steam Deck player controls (v48)** · **§ Preset categorization + Video Settings access (v48)**.

### Timeline tick labels — density / overlap *(v48 — Emily 24 Aug 2026 — kitchen / record only)*

**Pain:** When zoomed in / long duration (hours), timeline timestamp numbers (`1:10:00`, `1:11:00`…) get too dense and **overlap each other**.

**Idea:** At some zoom/density threshold, **don’t show every label** (thin out, hide, or cap) so they don’t stack on top of each other.

**Primary (screenshots):** timeline **ruler** labels — the complaint to fix.

**Secondary (optional):** yellow ClipCard queue number badges — Emily mentioned «большие цифры» in passing; note only if screenshots also show yellow `1` circles as a size itch (not the primary ask).

**Status:** kitchen / record only — **do not build now.**

**Band:** **v48**.

**Cross-link:** Timeline strip / ruler · **§ Timeline / player strip size (v45)** · Suggested priority **v48** · sibling **§ ClipCard marquee title — edge blur/fade (v48)** · **§ Clip goes missing mid-render / active RQ (v48)** · **§ Steam Deck player controls (v48)** · **§ Preset categorization + Video Settings access (v48)** · **§ Splitter movement telemetry (Dev Mode, v48)**.

### Splitter movement telemetry *(Dev Mode, v48 — Emily asked «на 38 версии»; implement as Dev Mode now)*

**Ask (Emily):** «на 38 версии сделаем скрипт который будет отслеживать движение сплиттеров… что стопорит… телеметрия для разработчика».

**Clarify:** she said **v38**, but **v38 already shipped** long ago; current kitchen band is **v48** (~app 46.1 / v47 WIP). Treat as: **build now as opt-in Dev Mode tooling**, and keep the kitchen note under **v48** (not a fake v38 section).

**Goal:** developer telemetry for QSplitter movement — what happens, what stops/blocks them — useful for Render Queue open/close, portable gaps, theater restore, five-state / kiss rules, etc.

**Surface:** Developer Tools → Tools → **Splitter movement telemetry** toggle (+ optional on-screen overlay + Dump snapshot). Logs `[splitter-tel]` into session `steempeg_*.log`. Settings keys: `dev_splitter_telemetry`, `dev_splitter_telemetry_overlay`. Off = no hooks / no perf hit.

**Tracked:** `main_splitter`, `right_h_splitter`, `main_v_splitter`. Events: `setSizes`, `splitterMoved`, drag begin/end, blockers (mins, hidden panes, theater, kiss, frozen queue, portable-like gap/middle, queue collapsed).

**Code:** `steempeg/ui/splitter_telemetry.py` · Dev Mode Tools tab · light breadcrumbs in `splitter_rules.py`.

**Status:** **implemented as Dev Mode** (this pass). Kitchen band stays **v48** for the «v38» misremember. Polish / more reason-tags can land later if needed.

**Band:** **v48** (Dev Mode; Emily said «v38»).

**Cross-link:** **§ Desktop splitters — five states + verge kiss** (v41.1) · **§ Right splitter jitter / open-close (v47)** · **§ Like a Portable middle splitter restore (v47)** · Suggested priority **v48** · `ui/splitter_rules.py` · `ui/dev_mode_dialog.py`.

### Screenshots-style progressive library load *(v49 — Emily 25 Aug 2026 — building)*

**Title vibe:** Smart Launch turned out to be **Stupid Launch** — replace (or rethink) with **Screenshots-style on-scroll / visible load**.

**Pain:** Why reload / preload the library on every launch and wait for a finished result, when cards can appear **as you look / scroll** («на глазах»)?

**Idea:**
- Like the **Screenshots** tab: load as you browse / as content comes into view — fast, progressive (viewport-lazy language).
- **No cache needed** for this mode (or no Smart Launch fingerprint cache as the point of the design).
- **No photo generation** — just read clip info, take logo, take preview from the folder.

**Shipping first slice (Emily 29 Aug — 1A + 2A):**
- New On-launch mode **`Progressive, load as you scroll`** (default).
- **Clips Manager only** — placeholders → viewport materialize ClipCards; disk logos + folder/cached thumbs (`allow_generate=False`).
- Refresh still full / Quick-style rescan.
- Rendered progressive deferred.

**Emily timed launch modes (29 Aug evening — real library):**

| Mode | Verdict |
|------|---------|
| **Progressive** | Fastest everyday launch; **scroll hitch** while materializing (expected / known) |
| **Quick (fast)** | Best companion to Progressive for rescans / daily |
| **Full** | Somewhat slow — **best for first launch or adding a new clips folder** |
| **Smart** | Junk — ≈ Skip, very slow («Stupid Launch»). **Dropped from On-launch UI**; old `smart` prefs migrate → Progressive |
| **Skip** | Same ballpark as Smart; keep as last option («хз») |

**Product retune after that test:**
- Settings combo: **Progressive** (default) · **Quick** · **Full** · **Skip** — no Smart row.
- Choose Folder / Add clips folder / Steam discover-add → **Full** scan (`fast=False`), not Quick.
- **Keep once seen (30 Aug):** off-viewport ClipCards used to dematerialize (same as Screenshots) → scroll-back hitch. Now already-viewed cards stay; drop only if live widgets exceed a RAM cap (farthest first). First pass down a new stretch may still hitch. Screenshots still dematerialize.
- **Don't paint library roots (30 Aug):** Progressive used raw `collect_clip_roots` and listed the clips folder itself as **Unknown / FG** (e.g. SteamLibrary). Refresh already filtered it. Now Progressive uses `discover_clip_paths` + skips configured roots.

**Status:** **building** (product retune landed after timed test).

**Band:** **v49**.

**Cross-link:** **§ Smart Launch (v47)** · Settings → Performance → On launch / Library startup · **§ ООООптимизация** (incremental UI / defer expensive work) · Screenshots **viewport-lazy** photo tiles (v45; Settings thumb-cache cancelled v46) · Suggested priority **v49** · siblings **§ Preset mini-editor (v49)** · **§ Marker Settings rethink (v49)** · **§ Timeline preview cache — source frames on disk (v49)**.

### Preset mini-editor *(v49 — Emily 27 Aug 2026 — kitchen / record only)*

**Pain today:** creating a Custom export preset = dial Video / Audio / Export on the live panel, then **Save as new**. Feels like a side-effect of the render panel, not a real authoring flow.

**Idea:** a **whole mini-editor** for presets — open a dedicated surface to build / edit a recipe (quality, FPS, bitrate, codec, audio, container, encode speed, …) **without** hijacking the live Video Settings you’re about to render with. Save / Update / Duplicate live there; Apply still pushes the recipe onto the panel / queue.

**Not:** another «Save as new» polish pass on the current Presets tab alone. **Yes:** rethink create/edit UX as its own editor (dialog or Presets-tab workspace — TBD when spiked).

**Status (31 Aug 2026):** **v1 mini-editor landed** — Presets tab **Create…** / ▾ **Edit in editor…** open a dedicated dialog (quality · bitrate tier · FPS · codec · encoder · speed · audio · container). Soft “taller than your screen?” confirm. Optional **If unavailable** quality fallback (then Original). Apply clamps quality/FPS to the clip. Panel **Save as new** still snapshots the live panel.

**Band:** **v49**.

**Cross-link:** **§ Custom export presets + queue rules** · **§ Preset manager UX v2** · **§ Preset categorization + Video Settings access (v48)** · `export_presets.py` · `ui/preset_mini_editor.py` · Presets tab / Apply ▾ · Suggested priority **v49** · sibling **§ Marker Settings rethink (v49)**.

### Marker Settings rethink *(v49 — Emily 27 Aug / 4 Sep 2026 — partial build; polish 12 Sep)*

**Ask:** rethink classes + improve Marker Settings (On clip / CS2 / Classes).

**v49 slice (4 Sep — building):**
1. **Empty clip → no strip chip band** — Markers button stays; above-groove pad collapses until ≥1 pin.
2. **Classes scoped by game** — `app_id` on each class (CS2 `730` ≠ other games). Clip inherits the game’s class list; no per-clip class dump. Legacy classes without `app_id` stay visible everywhere until recreated.

**Polish (12 Sep):** copy purge (no On clip / Classes / intro walls) · On clip **table** (Time / Name / Kind) + **seek** on select · Name / Description / Class / Icon editor · Classes **multi-select** + silent Delete / Del + RMB Duplicate·Delete. Legacy unscoped `app_id` migration still kitchen.

**Still kitchen:** deeper IA (type-vs-instance / CS2 pack discoverability) · migrating legacy unscoped classes to a game id.

**Idea (Emily 13 Sep — v50–60 maybe):** dock / half-panel Marker Settings beside the render control strip (Pause/Cancel/Logs zone) — jump markers from the dash, maybe per-marker screenshot thumbs so you hunt moments without scrubbing the strip. Unsure if it will stick; kitchen only, not a build ask.

**Design itch (Emily 14 Sep — think later, not a build):** Function of Marker Settings is «more or less» OK after the polish pass. **Chrome still feels slightly off-planet** vs Render Settings + the original About / Report-a-bug / FFmpeg-error button language. Tabs read **Win95 / banal** (`QTabWidget` purple blocks) — Emily might drop tabs entirely once a better IA appears, but **doesn’t know what yet**. Buttons/fonts should eventually match the **About · Report · FFmpeg** layout family (and RS youthfulness), not the Update Center / Settings / Marker Settings «same DNA, wrong sibling» look. **Record only — think; do not redesign now.**

**Status:** polish shipped in tree (table/seek/multi-delete · modeless dialog · Time width · On clip RMB Delete/Duplicate · strip RMB **Go to Marker Settings** · danger Remove/Reset · column Icon/Name/Time/Kind); legacy migration still kitchen. Dock panel → **v50–60** if it still feels useful. Dialog chrome / tab rethink → **§ Dialog chrome DNA (think later)**.

**Band:** **v49**.

**Cross-link:** **§ Marker Settings / On clip (v46)** · **§ Markers on the strip (v46)** · **§ Custom marker images + CS2 pack** · **§ Dialog chrome DNA (think later)** · `marker_settings_dialog.py` · `marker_prefs.py` · `timeline.py` · Suggested priority **v49** · sibling **§ Preset mini-editor (v49)** · **§ Timeline preview cache — source frames on disk (v49)**.

### Dialog chrome DNA — think later *(Emily 14 Sep 2026 — kitchen / no build)*

**Observation:** Render Settings feels **smart / stylish / on-brand**. About · Report-a-bug · FFmpeg error share a coherent **button layout + type** language Emily likes. **Check for updates · Marker Settings · Settings** (agent-era dialogs) share the purple DNA but still feel **banal / Win95-adjacent / slightly another planet** — especially **tabs** and generic dialog buttons/fonts.

**Not decided:** replace Marker Settings tabs with what (segmented control · side rail · single scroll · RS-like sections)? Unify all SteempegDialog footers on About/Report primary faces?

**North star (when energy returns):** one button/type system from **About / Report / FFmpeg** (+ RS youthfulness), applied to Marker Settings · Update Center · Settings — so nothing reads like a leftover template.

**Status:** kitchen / think only — **do not build now.**

**Band:** later / when Emily has a sketch (could ride **v51** chrome pass or a dedicated polish band).

**Cross-link:** **§ Marker Settings rethink (v49)** · About / `report_dialog` / FFmpeg error · Update Center · Settings dialog · Render Settings · `ui_theme.py` dialog button tokens · Suggested priority **think later**.

### Timeline preview cache — source frames on disk *(v49 — Emily 28 Aug 2026 — kitchen / record only)*

**Pain / observation (Emily 28 Aug):** PyAV hover preview («sniper») and batch timeline thumbs feel like they **decode the original, then immediately «шакалят» to low quality** (160×90). Why bake the downscale into the cache path if we could **store source-resolution decoded frames** and only scale when painting the hover tip / strip?

**Today (code reality):**

| Path | Decode | Stored as | Persistence |
|------|--------|-----------|-------------|
| **PreviewSniperWorker** (PyAV hover) | Full frame from file / DASH chunk | `img.resize((160, 90))` → `QPixmap` in RAM | Session only — **~160 entries**, cleared on clip switch; **not** on disk |
| **ThumbnailBatchWorker** (ffmpeg strip) | ffmpeg `-s 160x90 -q:v 7` | JPEG in `%TEMP%/steempeg_batch_{hash}/` | Temp dir — **outside** Settings media-cache cap |
| **Clip posters** (library cards) | ffmpeg poster | `cache/clip_posters/` | **Under** media cache limit |

**Idea:** Persist **source-res (or at least not pre-160×90) frames** under `cache/` (new subdir TBD, e.g. `timeline_previews/`). First visit: PyAV/ffmpeg decode once → write disk cache. Revisit same second-bucket: load file → cheap UI scale for 160×90 hover / strip density. Accept larger cache footprint; **Settings → Performance → Media cache limit (GB)** already has a cap — **prune deletes oldest files by mtime** when over limit (`prune_media_cache` at **startup** + **Settings Save**; subdirs today: `clip_posters`, `rendered_posters`, `mpd_playback`).

**Verified (28 Aug):** prune **does run** and **does delete** LRU-style when over cap — but **sniper / batch temp paths are not in `_MEDIA_CACHE_SUBDIRS` yet**, so a v49 spike must wire a new subdir into `media_cache.py` + size accounting, or batch thumbs stop living in `%TEMP%`.

**Not the same as:** **§ Timeline hover preview style** (chrome / trim tip — v47 shipped; deeper redesign → v50+) · **Settings → Preview quality** (`preview_quality.py` — **MPV playback** decode tier, not hover thumbs) · v46 **cancelled** generic thumb cache (this is a **targeted** timeline/sniper disk strategy, not library Smart Launch posters).

**Open questions (record only):** JPEG vs PNG vs WebP on disk · key = `(clip_path, sec_bucket, source_fingerprint?)` · share one cache between sniper + batch worker · whether to cap per-clip footprint · Linux / Deck IO.

**Status:** kitchen / record only — **do not build now.** Emily **13 Sep**: confirmed direction for **v51** — store decoded **originals** (cut/write source frames), scale in UI for hover/strip; avoid baking 160×90 into the cache path («зачем сжимаем если можем нарезать оригиналами»). Still needs media-cache subdir + prune wiring. Band note → **v51** when scheduled.

**Band:** **v49** kitchen → aim **v51** for build.

**Cross-link:** `ui/player/thumbnails.py` (`PreviewSniperWorker`, `ThumbnailBatchWorker`) · `infra/media_cache.py` · Settings → Performance → **Media cache limit** · **§ Timeline hover preview style** · **§ Cache Steam chunk init bytes (v50)** · v46 cancelled ~~thumb cache~~ · Suggested priority **v49** · siblings **§ Screenshots-style progressive library load (v49)** · **§ Preset mini-editor (v49)** · **§ Marker Settings rethink (v49)** · **§ Resume update download (v49)**.

### Cache Steam chunk init bytes *(v50 must — Emily 5–6 Sep 2026)*

**Pain:** PyAV DASH sniper (`PreviewSniperWorker._decode_dash_frame`) **re-reads `init-stream0.m4s` (init bytes) from disk on every hover decode**, then concatenates with the media chunk into a RAM `BytesIO` for `av.open`. Same init file, same clip — paid IO over and over while scrubbing the strip.

**Idea:** Cache init bytes **in memory per open clip / base_dir** (invalidate on clip switch / manifest change). Optional later: small disk sidecar under `cache/` if RAM-only isn’t enough — still **not** the same as **§ Timeline preview cache — source frames on disk** (that one caches decoded frames; this one caches the DASH init segment bytes before decode).

**Status (Emily 6 Sep):** **must-have for v50.** Keep sniper reformat / thread_type wins from 49.x; init-byte cache is the next sniper IO lever.

**Status (Emily 14 Sep):** **✅ done** — RAM cache per `init_path` in `PreviewSniperWorker` (`_init_bytes_cache`); cleared on clip switch. Optional disk sidecar still later / not required.

**Band:** **v50**.

**Cross-link:** `ui/player/thumbnails.py` (`_decode_dash_frame`, `_STEAM_VIDEO_INIT`) · **§ Timeline preview cache — source frames on disk (v49)** · **§ v50 ship band** · Suggested priority **v50 must**.

### UI fade / liveliness pack *(v50 maybe — Emily 5–6 Sep 2026 — kitchen)*

**Want (Emily 5 Sep):** more **fade / soft motion** so the UI feels alive — not a full Disney-every-widget mandate, but **many** surfaces where appear/disappear currently pops.

**First hits (examples, not exhaustive):**
- **ClipCard** — smooth fade-in when cards appear in the grid (load / filter / tab switch), not hard pop-in
- **Player header plaques** — top-of-player chips / badges (Healthy · Preview · pause plaque family, etc.) ease in/out the same way Trim tools / footer overlays already fade
- Shared short opacity (and light tuck where it helps) — reuse the footer-pill anim spirit, don’t invent 12 different easings

**Also in scope later:** other chrome that still hard-shows (toolbar pills, queue cards, neo tab chrome) — pick high-visibility surfaces; skip dense rapid updates (scrubber, every timeline tick).

**Not the same as:** old **§ Animations pack** (press/hover прожатие — parked from v44–v45) · Trim tools fade (already in tree) · ClipCard marquee edge blur.

**Guardrails:** respect reduced-motion if/when we wire it; don’t tank progressive library scroll with per-card 200ms on 500 cards — stagger / only animate newly inserted / viewport-visible.

**Status (Emily 6 Sep):** **maybe for v50** — «подумаю / мб добавлю». Not a must.

**Band:** **v50 maybe**.

**Cross-link:** `footer_pill_anim.py` · ClipCard / library grid · player header chrome · **§ Animations pack** · **§ v50 ship band** · Suggested priority **v50 maybe**.

### Filter funnel badge polish *(v50 must — Emily 5–6 Sep 2026 — ✅ 10 Sep)*

**Shipped (10 Sep):** larger readable circle (comfort **17** / compact **14**, digit **10** / **9**); parked on the **top-right** corner of the filter chip (funnel clear); floated sticker **tracks splitter / layout** via ancestor `eventFilter` (v49.1 ghost fix). Count = active filter categories.

**Emily 10 Sep:** «так и оставь» — no further lip/size churn unless something regresses.

**Status:** **✅ done**.

**Band:** **v50**.

**Cross-link:** `ui/widgets/filter_pill_button.py` · `sync_filter_pill_badge` · **§ v50 ship band**.

### Resume update download *(v49 — Emily 29 Aug 2026 — building)*

**Pain:** Update zip download retries from **byte 0** after a network drop. Each attempt deleted `{asset}.tmp` and started over (up to 5 tries).

**Idea / shipping behavior:**
- Keep the partial `{asset_name}.tmp` on retryable network / incomplete failures.
- Sidecar `cache/update_download.json` records url + asset + expected size/sha so a later attempt only resumes when it is the **same** release asset.
- HTTP `Range: bytes={existing}-` → expect **206**; if the server returns **200** (full body), rewrite from scratch.
- Size / SHA256 / `zipfile.testzip()` still run **only when the file looks complete**.
- Cancel / checksum / corrupt zip → delete partial. Exhausted network retries → **leave** partial so the next Update click can continue.

**Code:** `steempeg/services/updater.py` (`UpdateDownloadThread`).

**Status:** **building** (first v49 item Emily green-lit 29 Aug).

**Band:** **v49**.

**Cross-link:** `update_handler.py` · `update_job.py` · Update Center / progress dialog · Suggested priority **v49**.

### Update Available «Never show again» hover-only *(v50 polish — Emily 6 Sep 2026 — ✅ in tree; test ≥v51)*

**Pain today:** When the title-bar **Update Available** plaque is showing, the **Never show again** checkbox sits visible next to the chip all the time — noisy chrome for a rare action.

**Idea (Emily 6 Sep 2026):** Keep the green **Update Available** chip as-is. Hide **Never show again** by default. Show the checkbox **only while the cursor is over the top title-bar / plaque chrome** (hover on that upper tab strip). Leave the hover zone → checkbox disappears again. Checking it still permanently hides the plaque (existing `hide_update_available_badge` path).

**Not:** remove the preference — Settings toggle stays. Not a new Update Center feature.

**Status:** **✅ in tree** (6 Sep). Emily will smoke-test on **v51+** (not blocking current bugfix pass).

**Band:** **v50** polish / verify **≥v51**.

**Cross-link:** `window_chrome.py` (`_sync_never_show_update_available_hover`) · `updater_mixin.py` · **§ Update Available plaque — never show again (v47)** · **§ v50 ship band**.

### Delete clip / filtered RMB *(v49.2 — Emily 6 Sep 2026 — ✅ fixing)*

**Bugs / UX (Emily 6 Sep 2026, post-v49.1; clarified same day):**

1. **Delete + phantom DASH chunk lock** — Delete *does* work, but often only after waiting. Windows `[WinError 32]` on a Steam DASH segment even when **playback is already off** — sniper background warm held `.m4s`. **Fix:** always `kill_worker` + stop thumb/poster before rmtree; retries on WinError 32/5; works while playing (close then delete).

2. **Delete while playing** — same path: release + close + delete in one tap.

3. **First clip + filters: no RMB menu** — **Fix:** context menu uses the known `ClipCard` grid item (no fragile `itemAt(mapFromGlobal)` for card RMB).

4. **After delete: only ~20 clips visible** — full `scan_clips()` + kept filters looked like a shrunken library until Refresh cleared filters. **Fix:** surgical `_remove_library_clip_paths_from_ui` after delete (keep filter state; no full rebuild).

**Status:** **fixing** (6 Sep).

**Band:** **v49.2** / next patch after 49.1.

**Cross-link:** `library/controller.py` (`delete_clip` · `_rmtree_clip_folder` · `_handle_grid_card_context_menu`) · `player/controller.py` (`release_media_before_delete` · `_force_release_clip_file_handles` · `_clear_player_surface`) · Suggested priority **now**.

### v50 ship band *(Emily 6 Sep 2026 — thinking / plan)*

Emily’s numbered plan for **v50** (kitchen — not building until green-lit):

| # | Item | Priority | Notes |
|---|------|----------|--------|
| 1 | **Startup / loading window** | ✅ | Splash in tree; cold-start smoothness → **§ Splash progress like render bar (v51)** |
| 2 | **Corner-hover slide-out** | ✅ | Right = Render Queue (`queue_hover`) — Emily confirmed 14 Sep |
| 3 | **Kill List → Size picker** | ✅ | Stock: List **off** (`library_allow_list_view` default **False**). Settings → Advanced → «Restore classic List view». Size tiles on Clips/Rendered/Screenshots |
| 4 | **About / Updates / Settings → title bar** | ✅ | Desktop shell tools — Emily confirmed 14 Sep |
| 5 | **UI fade / liveliness pack** | maybe | «подумаю / мб добавлю» — **§ UI fade / liveliness pack** |
| 6 | **Cache Steam DASH init bytes** | ✅ | RAM `_init_bytes_cache` in sniper (`thumbnails.py`) — re-read per clip, not every hover |
| 7 | **Filter badge polish** | ✅ **10 Sep** | Size + corner seat + splitter track — **§ Filter funnel badge polish** |
| 8 | **Hover preview deeper redesign** | maybe | «подумаю» — **§ Timeline hover preview style** |
| 9 | **Steempeg PRO** | ✅ seeds only | DEV/Settings gate + splash chrome; **no converter unlock / features yet** — Emily 14 Sep |
| 10 | **Site shell + Getting Started** | **docs** | Empty GitHub site + mini Basics (+ optional README rethink) — **§ v50 docs / site slice** |

**Still v50+ / not this numbered list:** Smart Deletor · Screenshot Editor · combinable / split tabs · Steempeg Family · full PRO unlock · Never-show-again hover-only (✅ in tree; smoke ≥v51).

**Status (Emily 14 Sep evening):** numbered must/plan items **1–4 · 6–7 · 9 seeds** confirmed done in product. Open in the band: **#5 maybe** · **#8 maybe** · **#10 docs** · PRO feature surface later · splash smoothness → v51.

### Startup / loading window *(v50 — Emily 21 Aug / clarified 6 Sep 2026 — ✅ building)*

**Idea:** Proper **startup / loading window** (not just the in-window settle veil). Inspired by the Skip settle veil («Preparing workspace…»). Goal: no micro-crooked chrome at first paint; polished splash / loading shell until the workspace is ready.

**Emily 6 Sep (Progressive path):** **before** the in-window «Preparing workspace…» veil, show a **loader window**: app **logo** · **version** · a **progress strip** that reflects what is currently happening to get the app up (imports / settings / shell / library kickoff — TBD labels). Then hand off into Progressive settle / Preparing workspace as today.

**Emily 6 Sep evening (build):** Vegas / Adobe–style card — logo · **Steempeg** · **vXX** · gray wash · status top-left of bar · **%** top-right · smooth 0→100 fill. After 100% → main window (Progressive still gets Preparing workspace; Quick/Full keep their settle language). Module: `steempeg/ui/launch_splash.py`. Skip with `STEEMPEG_NO_SPLASH=1`.

**Emily 6 Sep evening (polish feedback):**

- **Busy spinner** left of status — independent rotating arc (liveness even if work stalls; only dies with the process on crash).
- **Top wash** drifts charcoal → soft **violet** with progress (not a hard black slab).
- **Progress strip** should feel like the **render bar** (eased fill + shimmer + soft creep between milestones) — not jump 67%→100%. Extra cold-start milestones + pump frames mid-constructor.
- **Top-right / top-left credits:** GitHub mark (hover ring → repo) top-right; avatar + bold purple `@applejuicy23` (→ profile) top-left. Bundled assets; offline-safe.
- **After 100%:** splash **stays** through post-show settle («Preparing workspace…») and closes when the settle veil reveals — so the inner chrome settle is still on the splash card, not a blank wait.
- **PRO later:** wash → red + `[logo] Steempeg [PRO] vXX` with PRO slide-in — see **§ Steempeg PRO** splash/brand chrome.

**Emily feedback on current Skip settle veil (21 Aug 2026):** veil helped (no 2–5s crooked wait) but still a micro UI glitch + micro strip loading; feels weird that the veil also flashed on Quick/Full when the crooked thrash was mainly a Skip issue. (Interim tune: veil on Skip only; Quick/Full keep a short settle pass without the cover. Full splash → this v50 band.)

**Status:** **in tree** (v50 splash card). Smoothness still imperfect on real cold-start (UI thread blocks splash timers). **Phased / render-bar-like polish → § Splash progress like render bar (v51).**

**Band:** **v50** (ship splash) · smoothness kitchen **v51**.

**Cross-link:** `launch_splash.py` · `startup_settle.py` · `app.py` `main()` · On launch Progressive / Skip / Quick / Full · **§ Steempeg PRO** · **§ v50 ship band** · **§ Splash progress like render bar (v51)**.

### Splash progress like render bar *(v51 — Emily 7 Sep 2026 — parked after failed wiring)*

**Idea:** Make real cold-start splash as smooth as DEV Simulate / Render Settings bar.

**Diagnosis:** splash `%` / spinner live on UI `QTimer`s. `SteempegApp()` monopolizes the UI thread → timers freeze, then catch-up. Render bar is smooth because heavy work is **not** on the UI thread. Putting the strip in a worker thread will not work (Qt widgets stay on UI).

**Approach (when resumed):**

1. Reuse `AnimatedRenderBar` on the splash (same lerp / shimmer as the dash).
2. Phased cold-start under a running `app.exec()` so timers tick between phases (`QTimer.singleShot` / short yields) — **not** a second thread for painting.
3. Preparing hold via real `QTimer` (~1s), not `sleep` + manual spin.
4. Feature-flag first (`STEEMPEG_PHASED_SPLASH=1`); keep today’s sync boot as default until proven.

**Archive (local, gitignored):** `steempeg/.cold_start_phased_archive.py` · `steempeg/.cold_start_phased_notes.md` — first attempt (7 Sep) broke launch; product tree reverted.

**Status:** **parked / do not wire into `main()` until v51 green-lit.**

**Band:** **v51**.

**Cross-link:** `launch_splash.py` · `animated_render_bar.py` · `app.py` `main()` · **§ Startup / loading window** · Suggested priority **v51**.

### Combinable / split tabs *(v50+ — Emily 22 Aug 2026 — kitchen / bigger idea; Emily excited)*

**Idea:** **Combinable / split tabs** — divide a tab pane in half so two library modes can be open at once, e.g. **Clips Manager + Rendered videos** side by side.

**Possibly later:** split space in **Render Queue** for **Render Settings** too.

**Long-term tease:** browser-like tabs — later, **not** for **v47** / **46.1**.

**Status:** kitchen / record only — **do not build now.** Bigger kitchen idea for the **v50 / v50+** band.

**Band:** **v50+** (file only had discrete **v50** sections; parked here with the 50+ note).

**Cross-link:** Library tabs / Clips · Rendered · Screenshots · Render Queue · Suggested priority **~v50 / v50+**.

### Desktop chrome — About / Updates / Settings → title bar *(v50 — Emily 25 Aug / clarified 6 Sep 2026)*

**Idea:** On **Desktop**, move footer mega-pill **About** · **Check for updates** · **Settings** into the **window title bar** — same language as **Portable** (title-bar shell tools).

**Today:** Portable already lives in the top bar; Desktop still keeps About / Updates / Settings in the library footer mega-pill (Folder / Refresh stay tab-owned).

**Goal:** one top-chrome pattern Desktop ↔ Portable; footer mega-pill = library Folder / Refresh / count only (no About / Updates / Settings).

**Emily 6 Sep:** **do it in v50**, with a **Settings choice** — user can pick title-bar vs keep footer chrome (opt-in / preference, not a forced one-way migrate with no escape).

**Status:** **building / in tree** (11 Sep) — pref `desktop_shell_tools_in_title_bar` default **off** (stock footer). Settings → Visual → Side panels checkbox; live preview. Portable unchanged (always title bar).

**Band:** **v50**.

**Cross-link:** `SteempegTitleBar` shell tools · Portable title-bar About / Updates / Settings · library footer mega-pill (`app.py` / `_apply_library_footer_*`) · **§ Library tabs and footer chrome** · **§ v50 ship band** · Suggested priority **v50**.

### Corner-hover slide-out panels *(v50 — Emily 27 Aug / clarified 6 Sep 2026)*

**Idea:** Cursor to the **edge of the screen / window** → panel **slides out**; do what you need → it goes away. Comfortable on-demand chrome without living splitters.

**Emily 6 Sep v1 sketch:**
| Edge | Panel |
|------|--------|
| **Right (default first)** | **Render Queue** — ship this first |
| **Left (optional / later)** | Library / Clips — «по желанию», not required for v50 day-one |

**Product feel:** player stays full-bleed by default; chrome is **on-demand** via cursor proximity (smooth ease-in/out), not permanent drag handles. Splitters become optional / gone in that shell mode.

**Not:** Portable theatre (already one surface). This is a **Desktop shell** rethink — sibling energy to *Like a Portable* / combinable tabs, not a v48 splitter patch.

**Status:** kitchen — planned for **v50** (right RQ first); **do not build now.**

**Band:** **v50**.

**Cross-link:** **§ Desktop splitters — five states + verge kiss** · **§ Right splitter jitter / open-close (v48)** · **§ Portable / Steam Deck shell** · **§ Like a Portable middle splitter restore (v47)** · **§ Combinable / split tabs (v50+)** · **§ v50 ship band** · **§ Hover Render Queue chrome restyle (v51)** · Suggested priority **v50**.

### Hover Render Queue chrome restyle *(v51 — Emily ~Sep 2026 — kitchen / lost mock)*

**Idea:** Emily sketched (screenshot in chat; later lost) how the **hover / corner Render Queue** panel should sit **under Chrome** — tablet/plaque language, not the current splitter dock look. First polish slices already landed (wider min width, hairline, scrollbar thumb, immersive gutters). **Full restyle** of that floating surface → **v51**.

**Also absorbs:** once Kill List ships Size Big/Medium/Small, Hover RQ should speak the **same card sizes** (not a leftover Grid/List).

**Status:** kitchen — **v51**; mock may need re-sketch if the screenshot stays lost.

**Band:** **v51**.

**Cross-link:** Hover RQ / corner-hover · `queue_sidebar.py` · **§ Corner-hover slide-out panels** · **§ Kill / hide List** · Suggested priority **v51**.

### Clips Medium ≈ Screenshots Medium *(v51 — Emily 11 Sep 2026)*

**Idea:** Screenshots **Medium** (stock photo card) already feels right. Try reshaping **Clips Manager Medium ClipCard** toward that layout/padding language (not a blind copy — keep clip badges / queue # / health). Do **not** rush in v50 Size polish.

**Status:** kitchen — **v51**.

**Band:** **v51**.

**Cross-link:** **§ Kill / hide List** · `screenshot_photo.py` · `card_sizes.py` · `grid_view.py` ClipCard · Suggested priority **v51**.

### Screenshots List *(v51 — Emily 11 Sep 2026)*

**Idea:** Screenshots stay **Grid-only** for now (Size Big/Medium/Small is enough). In **v51**, maybe add a **List** tile in the Size popup (same Settings opt-in / allow-list energy as Clips) for the rare fan of полоски — developer thinks about users.

**Not stock** unless Emily flips it later.

**Status:** kitchen — **v51**; do not build now.

**Band:** **v51**.

**Cross-link:** **§ Kill / hide List** · Screenshots Size ladder · `library_allow_list_view` · Suggested priority **v51**.

### Click video to play/pause *(v51 — Emily 14 Sep 2026 — kitchen)*

**Pain:** To pause/resume you have to drop to the footer and hit Play/Pause. Extra mouse travel when you’re already looking at the picture.

**Idea:** **LMB on the video surface** toggles play/pause — same as the transport button. No need to aim at the footer. Keep scrub / markers / trim on the strip; surface click is transport only (don’t steal double-click fullscreen / other existing gestures if any — confirm while building).

**Status:** kitchen — **v51**; do not build now.

**Band:** **v51**.

**Cross-link:** player surface / MPV embed · footer Play/Pause · immersive / theater · Suggested priority **v51**.

### Remote Ko-fi / tip link (fetch from Pages) *(v51 — Emily 17 Sep 2026 — kitchen)*

**Pain:** Tip link baked into a release stays forever. Friend’s Ko-fi (`ko-fi.com/milloriin`) may be correct for **v51**, but when Emily later has her **own** Ko-fi (e.g. ~v64), old builds would still point at the friend’s page — unfair / confusing.

**Idea:** Do **not** hardcode the live tip URL per version forever. Ship a tiny client that **HTTP-fetches** the current tip/Ko-fi URL from the **GitHub Pages** site (same host as the product landing — a small JSON or text file on the server). App displays whatever the server says. Update the file once → **old and new** installs show the right link. No need to rewrite history or republish old zips.

**Sketch (TBD when building):**
| Piece | Notes |
|-------|--------|
| Server | e.g. `applejuicy23.github.io/steempeg/…` tip URL file (JSON/`kofi.txt`) |
| Client | One fetch on About / tip chrome open (cache + timeout; offline → last-known or hide) |
| Content | Current Ko-fi (friend’s for now; swap to Emily’s later without code change) |

**Not:** per-release hardcoded URL that freezes at ship. Not GoFundMe KYC path.

**Status:** kitchen / record only — **do not build now.**

**Band:** **v51**.

**Cross-link:** About / tip chrome · Website Pages · Suggested priority **v51**.

### Player loupe / zoom *(v51–52 — Emily 14 Sep 2026 — kitchen)*

**Idea:** A **лупа** (magnifier) so you can inspect fine detail on the frame — e.g. UI text, distant enemies, artifact check. One sketch: discrete **zoom steps** like **100% · 120% · 150%…** (and back), not free-form pinch unless that falls out cheap. Exact chrome (corner loupe · header control · hold-to-peek) TBD when building.

**Not:** export crop / Screenshot Editor (separate). Not timeline sniper thumbs.

**Status:** kitchen — aim **v51–52**; do not build now.

**Band:** **v51–52**.

**Cross-link:** **§ Click video to play/pause (v51)** · player surface · mpv pan/zoom if available · Suggested priority **v51–52**.

### Screenshot Editor *(v50+ — Emily 27 Aug 2026 — kitchen / interesting feature)*

**Pain today:** Want a **custom** screenshot to post (e.g. Steam) → take the shot, open Paint, paste, save, **reload Steam** — photo-swap is heavy костыль.

**Idea:** Do it **in Steempeg**. Pick a **victim** screenshot → open editor → drop/choose **your own image** → it **replaces** the file (same path / Steam-facing identity as needed) → tweak if you want → **Save**. No Paint round-trip, no Steam restart dance.

**Sketch (TBD):**
| Step | Notes |
|------|--------|
| 1 | Select victim from Screenshots library (Steam and/or Steempeg) |
| 2 | Open Screenshot Editor — preview + replace with custom file |
| 3 | Optional light edits later (crop / fit) — v1 can be **replace + save** only |
| 4 | Write back so Steam/library still sees that slot as that screenshot |

**Not:** full Photoshop. Not progressive-load (v49). Sibling to Screenshots tab / Steam vs Steempeg chrome.

**Status:** kitchen / record only — **do not build now.**

**Band:** **v50+**.

**Cross-link:** Screenshots library · `steam_screenshots.py` · Steempeg capture path · **§ Clearer Steam vs Steempeg screenshot distinction** · Suggested priority **~v50 / v50+**.

### Smart Deletor *(v50+ — Emily 6 Sep 2026 — kitchen / bigger idea)*

**Pain today:** Clearing **big** clips or obvious **junk** is one-by-one RMB Delete (and file locks / Progressive quirks — see **§ Delete clip / filtered RMB**). No batch “queue” for cleanup.

**Idea:** **Smart Deletor** — user picks what to wipe (large clips, junk / dead / short / filtered set — as they wish), then runs a **Delete Queue** shaped like **Render Queue**: stage many clips → confirm → delete through the list with progress / cancel / per-item status. Not a silent auto-purge.

**Sketch (TBD):**
| Piece | Notes |
|-------|--------|
| Pick rules | Size · duration · Dead · game / filter · manual multi-select — user-driven, not a fixed “smart” policy |
| Delete Queue | Cards / list like RQ: pending → deleting → done / error; Cancel stops the rest |
| Safety | Confirm before start; respect locks (unload / retry from delete-clip patch); don’t nuke without intent |
| Scope | Clips library first; Rendered / Screenshots later if useful |

**Not:** auto-delete policies with no UI. Not a replacement for single RMB Delete.

**Status:** kitchen / record only — **do not build now.**

**Band:** **v50+**.

**Cross-link:** Render Queue UX · `delete_clip` · **§ Delete clip / filtered RMB (v49.2)** · library filters · Suggested priority **~v50 / v50+**.

### Performance acceleration shortlist *(v50+ — on review / profiler-first)*

**Goal:** speed up heavy internals without rewriting the whole app. Do only where profiling shows Python-side hotspots on real large libraries.

**Candidates under review:**
- Scan / indexing path for clips (thousands of folders, `stat`, sidecars)
- Steam DASH init-bytes cache and chunk handling
- Decode/scale path for timeline sniper + batch thumbs (if not fully covered by FFmpeg/PyAV workers)
- Media-cache prune passes (`hash` / `size` over large trees)
- Heavy parse paths (VDF and large library JSON caches)

**Guardrail:** no global language rewrite; consider small native/helper modules only for proven hotspots.

**Status:** record only — **do not build now**.

**Band:** **v50+**.

**Cross-link:** **§ Cache Steam chunk init bytes (v50)** · **§ Timeline preview cache — source frames on disk (v49)** · **§ Screenshots-style progressive library load (v49)** · `infra/media_cache.py` · `core/steam_vdf.py` · library cache JSON paths.

### Library filters — game checklist UX *(Emily 11 Aug 2026 — «сейчас хочется»)*

**v44 candidates / high interest** (optional polish in **v44**, else **v45** kitchen/library). Place with library chrome / filters — not Screenshots-unified scope.

| # | Item | Notes |
|---|------|--------|
| 1 | **Drag multi-select / deselect (games)** | Game filter checklist: hold LMB and drag down (or across) to check/uncheck many games without a click per row. Pain today with ~10–20 games — tedious uncheck-one-by-one. (Likely the Clips/Rendered game filter checklist.) |
| 2 | **Persist filter state across sessions** | «Filter memory» — remember last session’s filter selections (esp. games) on next launch. Optional reset via existing **Clear** inside filters. High value at ~100 games |

**Scale note:** with ~100 games, **persist is the sane default**; drag-select still helps medium lists (~10–20).

**Band:** **v44 optional / v45** — Emily wants them now; mark high interest, don’t block P0/P1.

---

## 🎯 v44 kitchen — desktop render + player prefs *(Emily 8 Aug 2026 — plan only, do not build yet)*

**Branding:** skip public **v43**; next ship is **v44**. Emily green-lit build (9 Aug 2026) — start with **P0**.

### P0 — Render Queue drives the player / header context

**Pain:** desktop render chrome still tracks the **library selection**, not who’s actually next in the queue.

| # | Item | Notes |
|---|------|--------|
| 1 | **While queue is active** | ✅ header + badge follow queue context job (`_queue_context_job` / `_sync_player_header_to_queue_context`); Clips/Rendered preview without stealing title |
| 2 | **After batch, completed still listed** | ✅ same helper while `len(queue) > 0` |
| 3 | **After queue clears** | ✅ `_on_queue_became_empty` → `_restore_header_from_library_selection` (Clips **or** Rendered) |
| 4 | **Rendered videos selection** | ✅ `is_unknown` from missing **game_name** (not only app_id); sidecar name keeps real identity |

### P1 — Desktop Render like Portable (keep the panel)

**What Emily meant (clarified 9 Aug 2026):** not “delete the neo dock” — make the **desktop Render / Start button row** speak like Portable when the queue is alive, **with numbers on the chrome**, while the export panel stays for depth.

| # | Item | Notes |
|---|------|--------|
| 1 | **Render button = Portable analog** | ✅ Settings **Desktop layout**: *It's a Desktop* (classic docked neo) / *Like a Portable* (purple **Render Settings** beside Start → floating neo-only window, min/max, click again to close). Trim-adjacent Render removed |
| 2 | **Keep render panel** | ✅ neo dock stays for Desktop; Like a Portable borrows neo into the floating window while open |
| 3 | **Numbers on the start CTA** | ✅ `Render Queue (N)` / portable `Start Queue (N)` |
| 4 | **Optional size figures** | ❌ dropped — Emily: no est. size / free disk on the dash / Ready panel |
| 5 | **Queue Ready badge** | ✅ numbered status circle (yellow/orange/red/green) while queue non-empty; plain Ready+green when empty |

### P2 — ~~Timeline / player strip size~~ → **v45**

Moved 9 Aug 2026 (Emily): Settings Small/Medium/Large for the player timeline strip — not in the v44 train. See **§ Timeline / player strip size (v45)**.

### Also absorb into v44 (from older «v43 must» bands)

| Item | Notes |
|------|--------|
| **Date/TZ + marker trim offset** | Already in Settings IA as ✅ / planned — verify shipped vs leftover |
| **ClipCard queue # + shelf corners** | Optional v44 polish — kitchen spike (desktop queue badges; top/mid/bottom radii); finish if not already. Full shape modes → **§ ClipCard design modes (v45)**. Multi-instance same-clip → **§ Same clip multiple times — cycling queue badge digit (v45 leftover)** |
| **Neo tab icons** *(Emily 11 Aug 2026)* | ✅ Landed — PNG glyphs on neo sidebar + page titles (not global chrome). Confirm with Emily if any glyph still wants a redraw |
| **Soak / fuzz harness** | Optional, not blocking ship → **v45.1 DEV MODE** |
| **Preset manager UX v2** | ✅ First slice committed (unpushed); dirty polish (expandable rows / Apply ▾). Then **v45 release prep**. See § Custom export presets → Preset manager UX v2 |
| **Library chrome (per-tab Folder/Refresh)** | Each of Clips / Rendered / Screenshots owns its own Folder picker + Refresh paths/behavior — not one global toolbar. Main Refresh ✅ scoped; ▾ menu extras tab-aware (see Per-tab Refresh row above) |
| **Library filters — drag-select + persist** *(Emily 11 Aug 2026)* | ✅ Drag-select + filters persist committed (late-15-Aug batch). See **§ Library filters — game checklist UX** |

**Pushed out of v44 (Emily 10–12 Aug 2026):**

| Item | Goes to |
|------|---------|
| **ClipCard design modes** (Square / SteempegUI / Round) | ✅ landed early in **v44** (12 Aug) — Settings → Visual; was deferred to v45 |
| **Update Center rethink** | **v45** — first slice **landed** (13 Aug); polish later |
| **MPVWrapper hard fix** | **later / v45+** — not a v44 must; expensive to iterate |
| **Screenshots unified** (Steam + Steempeg + game filter + whole-card press + Grid-only) | **v45** — first slice **done** (13–14 Aug); cache vs viewport Settings → **v46** |
| **Render History clear-on-open** (Open Render History from completion dialog) | **v45** — confirmed bug, non-critical; skip 44.1 |
| **Splitter under-reveal** | struck as 44.1 must; unverified/low scrap only if it returns |

**Building** — Emily green-lit 9 Aug 2026; **P0 + P1 landed**. **v45:** Update Center + Screenshots unified + Timeline strip S/M/L + Player header size + Volume / speed boost (→500%) + **Defer / leave Render Queue** + cycling queue badge + ViewModeChrome + Neo icons + filter drag/persist ✅ + **Preset v2** first slice ✅ (unpushed; dirty polish). **Animations pack parked**. **Now:** finish dirty polish → commit/push → **v45 release prep** (notes / `45dev→45` / milestones). Non-critical: Render History clear-on-open. Desktop List → Settings toy may slip **v46**. **TrueDark** → **v46**. **MPVWrapper** → **v45 / later**.

---

## 🩹 v44.1 — skip unless critical *(Emily 12 Aug 2026)*

**Empty / skip.** Emily doesn’t remember or repro the old right-splitter «недораскрытие»; Render Queue already opens on first open when there’s a clip. **Not worth a 44.1.** Only burn a patch if something critical shows up after the v44 tag.

~~Former must (9 Aug): first-open under-reveal / open-floor physics~~ → struck. Optional low scrap below if it ever returns.

**Out of scope:** full three-pane redesign, portable shell.

### Splitter under-reveal *(unverified / low — v45 scrap if at all)*

Old first-open under-reveal («недораскрытие») — Emily (12 Aug) doesn’t repro; queue already opens when a clip exists. **Keep only as low/unverified** if it resurfaces; do **not** prioritize over confirmed **§ Render History clear-on-open**.

---

## 🩹 v45.1 — bugfix patch after v45 *(Emily 17 Aug 2026)*

**Band:** **v45.1** — accumulated bugfixes after **v45** shipped (zip + version `45`). **Not** a feature train. Emily (17 Aug): «нужно начать делать версию 45.1 т.к очень много багов накопилось».

**DEV MODE diagnostics** (14 Aug kitchen) stay recorded below as **later / optional** — they are **not** the reason for this patch. Do **not** treat soak/fuzz as the 45.1 headline.

In-progress version string: **`45.1dev`** until ship (`45.1`).

### P0 — Known accumulated bugs

| # | Item | Notes |
|---|------|--------|
| 1 | **Update Center slightly buggy** | Emily: «окно обновлений слегка забагалось» after the wide two-column rethink. Layout / scroll / centering / Keep-when-updating clip on cramped widths. `update_center.py` + `updater_mixin.py`. |
| 2 | **Portable Add blocks UI + squashes queue cards** | Emily: Add goes through the UI thread (MPD walk / probe), and adding **сплющивает** render-queue clip cards. Desktop was fixed in `render_queue_panel.py` (`minimumSizeHint` = `sizeHint` + Fixed rows); portable sidebar missed it / Add rebuild reset size policy. Offload Add; pin scroll-body height. |
| 3 | **Bundled freeze icons** | `exit.png`, `resume.png`, `phibechipeegg.png` must be in `BUNDLED_ASSET_FILES` / `_BASE_ASSETS` or frozen builds miss Leave/Resume + About egg. |
| 4 | **Render History clear-on-open** | v45 leftover, non-critical. Open Render History from the completion dialog still wipes the list. Still open unless time. |
| 5 | **Portable middle splitter hover-reveal** | **Killed 21 Aug** — `portable_splitter_reveal.py` cursor poll + `setStyleSheet` thrash lagged the **whole UI** and ate SplitH/V cursors. Module is paint-only (always-visible handles). Reintroduce later only with transition-only paint, handle-scoped events, **no** global poll. |

**Suggested priority:** 1–3 this patch (user-visible). 4 if cheap. 5 already neutralized. DEV MODE only if energy is left — it is not why 45.1 exists.

### Optional / later — DEV MODE diagnostics *(Emily 14 Aug 2026 — kitchen only, do not build as the patch headline)*

**Framing:** diagnostic tooling gated behind **DEV MODE** — leave running when hunting regressions; if something breaks, fix it. Supersedes / absorbs older **§ Render soak / fuzz harness**. Slip to a later 45.1 slice or the next patch if the bugfix list eats the release.

#### A — Render Queue stress / fidelity diagnostics

Stress the real **Render Queue** path from Clips Manager — many jobs, many knobs, then **reconcile** what came back.

| # | Item | Notes |
|---|------|--------|
| 1 | **Job matrix** | Build ~**100** queue jobs from her library: vary presets · formats (mp4 etc.) · FPS · bitrate · **target file size** · output names · **segments / clip cuts** |
| 2 | **Output folders** | Render into **user-specified folders** (not a hard-coded dump path) |
| 3 | **Reconcile (most important)** | Report where **errors** occurred · whether the **chosen preset matches** the obtained result · for target file size: how far **real size drifts** from the requested target |
| 4 | **DEV MODE home** | In-app diagnostic surface (not only `python -m …` one-off) — power/dev users can re-run after queue/render changes |

#### B — Library filter / sort diagnostics

Same spirit for **filters + sort** — prove the resulting set matches the applied window.

| # | Item | Notes |
|---|------|--------|
| 1 | **Full list in** | App holds the full clip list (folder, game, created time, …) |
| 2 | **Valid random windows** | Pick windows that **actually have data** (e.g. 2–4 AM on a date that has clips) — not empty traps like 1970 that correctly return nothing |
| 3 | **Apply + verify** | Run filters; assert results belong (e.g. must **not** return 4 PM when the filter was 2–4 AM). Also exercise **sorting** (e.g. by game name first letter) |
| 4 | **Mismatch report** | Must understand: **original list** · **applied filters** · **resulting set** · detect mismatches. Useful to leave running |

---

## 🩹 v46.1 — minor patch after TrueDark (+ Portable combo notes) *(Emily 22 Aug 2026)*

**Band:** **v46.1** — minor bugfix **candidates** around **TrueDark apply** and related chrome. **Not** a feature train. Kitchen / record — **do not build now** unless Emily green-lights a patch slice.

**Clarification (22 Aug 2026):** The screenshot symptom — video/player window **overflowing its banks** — happens **before** she applies *Like a Portable* / *It's a Portable*, i.e. during **TrueDark theme apply**. While TrueDark is still applying (**slow on Windows**), the video pane overflows / looks wrong; **once TrueDark finishes applying**, the video window becomes normal again. So the **primary** issue for that overflow is **TrueDark apply timing / mid-apply layout flash** (Windows especially; Linux apply is fast). Portable may still be a **separate or combo** case, but **overflow-before-portable** is the key nuance — do not treat the screenshot as “Portable+TrueDark layout permanently wrong.”

**Split from v47:** these are acute **mid-apply flash / marquee / Windows apply-perf** items. Deeper Portable TrueDark theme polish (holes vs Desktop theatre chrome) stays **§ TrueDark for Portable (v47)**.

### P0 — TrueDark apply + related

| # | Item | Notes |
|---|------|--------|
| 1 | **TrueDark mid-apply video overflow / layout flash** | **Primary (clarified 22 Aug).** During TrueDark apply (before Portable is toggled), the video/player pane **overflows its banks** / looks wrong; settles once apply completes. Suspect: apply timing / re-layout while theme is mid-flight — loud on **Windows** (slow apply), quieter on **Linux** (fast). Portable *Like a Portable* may still combine or reproduce a related overlap with Video Settings — keep as secondary/combo suspect, not the first reading of the overflow screenshot. |
| 2 | **ClipCard titles clipped from the left** | Text under thumbs appears **clipped from the left** (e.g. “ject DIVA Mega Mix+” missing “Pro”) — marquee / elide / layout bug (recorded with Portable+TrueDark context). Cross-link **§ v46 #2b** smooth overflow marquee («вертелка»). |
| 3 | **TrueDark apply still slow on Windows** | Apply felt **mega-fast on Linux** with no severe bugs; **Windows** apply still slow. Perf / apply-path — same family as #1’s mid-apply flash (slow apply makes the flash visible longer), but shipable as its own win even if layout is hardened. |

**Also shipping / just shipped in 46.1:** *Like a Portable* **drops the middle splitter** — replaced with a **4px air gap** (title-bar↔player-header style). Opt-in restore of the player↔dash drag handle → **§ Like a Portable middle splitter restore (v47)** (default stays gap-only).

**Suggested priority:** 1 mid-apply overflow/flash (Windows). 2 ClipCard left-clip. 3 Windows apply speed if energy. Deeper Portable theme holes → **v47**, not this patch. Middle-splitter restore checkbox → **v47** small polish, not this patch.

**Cross-link:** **§ v46** #8 TrueDark · **§ v46 #2b** marquee · **§ TrueDark for Portable (v47)** · **§ Like a Portable middle splitter restore (v47)** · Desktop layout *Like a Portable* (v44 P1, combo-only suspect) · Suggested priority **v46.1**.

---

## 🩹 v50.1 — post-v50 RC patch candidates *(Emily 16 Sep 2026 — kitchen / record; do not build yet)*

**Band:** **v50.1** — small bugfix / UX patch after v50 RC. Kitchen only until Emily green-lights a slice.

| # | Item | Notes |
|---|------|--------|
| 1 | **Shell change via Settings → restart: skip Ask Shell once** | ✅ Implemented 17 Sep — one-shot `ui_shell_skip_ask_once`; cold start still asks when Ask is on. |
| 2 | **Portable: ClipCard Size in Choose a Clip** | ✅ Implemented 17 Sep — toolbar: Choose Folder · Refresh · **Size** · N Clips (grid-only). |
| 3 | **MPV micro-glitch on Side panels change** | ❌ Cancelled 17 Sep — Emily: false alarm («показалось»). |
| 4 | **Hover RQ + Side swap: splitter stuck on left** | After Side swap with Hover on, queue handle hide stuck on the old splitter — left-edge ghost; player\|Clips handle missing. Live preview without Save **kept** (Emily). Fix: rebind handles after side sync. |

**Status:** 1–2 done; 3 cancelled; 4 in progress / fixing.

**Cross-link:** Shell / `ui_shell` · ask-on-startup (40.1) · Choose a Clip Size · Hover RQ · Side panels · Suggested priority **v50.1**.

---

## 🩹 v51.1 — post-v51 bugfix / polish *(Emily 23 Sep 2026 — kitchen; fix after dogfooding fresh v51 zip)*

**Band:** **v51.1** — bugfix + cleanup patch **after v51 ships**. **Not** a feature train. Emily will unpack a clean **v51** build and hunt regressions; critical library / identity bugs land here. Do **not** burn 51.1 as the current product version while 50.1 / 51 are still unreleased.

**Framing (23 Sep):** dead-clip verification and multi-folder dedupe feel broken since ~v48; code paths were heavily reworked and still misbehave. Also need performance / dead-code cleanup and native Linux builds (no WSL — RAM hog).

### P0 — Library identity / health (critical)

| # | Item | Notes |
|---|------|--------|
| 1 | **Dead clips vanish after adding a new library folder** | Add second root (e.g. `SteamLibrary`) → dead / no-video packages disappear from Clips. Dedup / health / Full-scan keep rules must keep dead packages visible and verifiable. |
| 2 | **Duplicates not written / silently ignored** | Same-clip multi-folder cases: announce gone (log-only in v51) but keep/merge behavior unclear — either not recorded or dropped. Need clear keep rules + visibility again. |
| 3 | **Dead / health verification** | Session health vs disk / Dead filter must stay consistent after folder add/remove and Progressive vs Full scan paths. |

### P1 — Performance & cleanup

| # | Item | Notes |
|---|------|--------|
| 4 | **Startup / Progressive / Screenshots perf** | Further optimize cold start, Progressive warm, Screenshots shelf paths after the v51 timing work. |
| 5 | **Remove dead / unused helpers** | Delete garbage functions and leftover rework debris from the Progressive / library rewrite. |

### P2 — Packaging

| # | Item | Notes |
|---|------|--------|
| 6 | **Linux builds for 50.1 + 51** | Native Linux machine (not WSL). Ship `*_linux.zip` lines when Emily can compile off Windows. |

**Suggested priority:** 1–3 first (user-critical). 4–5 while dogfooding. 6 when on a Linux box.

**Cross-link:** `clip_identity.py` · library `controller` / filters · Progressive warm · `newver_compilator.py` · Suggested priority **v51.1**.

---

*Last updated: 23 Sep 2026 — v51.1 kitchen: dead clips / dupes after multi-folder · perf cleanup · Linux zips without WSL.*
