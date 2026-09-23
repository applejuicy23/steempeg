# Steempeg v51

🚀 **NEW FEATURES:**

- **Steempeg PRO chrome:** About **PRO** badge / red accents, **Support** → Ko-fi, Settings → **PRO** tab with unlock banner, and an About-style unlock dialog with a Donate Me CTA.
- **Donate Me / Ko-fi tip:** Title-bar cup mark, Donate Me dialog (Fredoka CTA), remote tip URL from GitHub Pages `steempeg-meta.json` (quiet refresh after startup + splash cache).
- **Product site — Donate Me:** Landing nav + Donate Me page driven by tip meta; Pages deploy for the tip JSON.
- **Render Queue View:** One icon chip (like Clips **Size**) — click opens Grid / List popup; the chip shows the active mode.
- **RQ hover grip:** Edge resize handle as a filled **hill → flat → hill** tab with the inner grip stripe (not a floating oval / bare brace stroke).
- **Screenshots shelf load modes (Settings):** **As you scroll** vs **Full shelf after launch (like v50)** — placeholders plant either near scroll or drip in the background after launch.
- **Screenshots List (opt-in):** Classic table beside the photo grid when Settings restores List view.
- **Player — click video to play/pause** with a short pulse overlay; timeline sniper can reuse tip JPEG disk hits (`timeline_previews`) after the first decode.
- **Progressive library probes:** Background thumb / poster-cache probe workers (UI-safe) with teardown stop; ClipCard title/icon can update without a full grid rebuild.
- **Cured health chip:** Filter pill appears when salvage/cure lands; rematerialize after cure.

✨ **IMPROVEMENTS:**

- **Progressive cold start:** Splash **Preparing** handoff hardened before shell maps / `showMaximized`; unveil settle before density + hydrate; throttle Progressive warm off the hot path; yield between poster backfill and Steam name refresh on big libraries; ClipCard marquees keep a precise tick with suspend.
- **Side libraries after Progressive:** Rendered / Screenshots chunk after Progressive settle; side-library hydrate deferred until Progressive finishes (no mid-Clips “bomb” of Rendered cards); Screenshots catalog warm vs tab paint by shelf mode.
- **Library chrome:** Folder-picker **+** spins while the library loads; Sorting / combo popups size to the longest label (no elided sort rows); Progressive Default sort between discover batches; Clear keeps real Default sort and restores filter pill logos.
- **Ko-fi fonts/assets:** Fredoka + Selawik trees ship in frozen packs; cup mark for tip / Donate Me.

📝 **OTHER UPDATES & BUGFIXES:**

- **Dead / health:** Keep dead Steam folders in Full scan; assess health when Progressive cache misses; refresh session health so the Dead filter matches disk.
- **Folders + filters:** Keep Clips folder **+** visible when the list is empty; restore folder-plus panel and heal stale filters after Clear; removing a library folder wipes remembered filters and runs a full scan (no blank shelf with a live filter badge); new library roots join an active Folders filter list; filter menu Folders click revives empty Games/Health (no stuck Apply (0)).
- **Screenshots shelf:** Scroll mode keeps planting when there is nowhere to scroll yet; switching to Full / like v50 **rescans** Steempeg + Steam folders (empty session JSON no longer leaves 0 shots); empty/failed session prefetch falls back to a real folder scan.
- **RQ / View:** Duplicate-clips announce dialog removed (log only); cascade helper restored so the filter funnel opens again after a regression.
- **Player / cache:** Sniper `cache_dir` + DISK latency on the sensor; prune/purge `timeline_previews` with media cache; Esc clears Screenshots list; play/pause pulse cancelled on teardown.
- **Progressive grid:** Rematerialize after sort; refresh names in place; stop Progressive thumb probe on app teardown.

---

**Full Changelog**: [v50.1...v51](https://github.com/applejuicy23/steempeg/compare/v50.1...v51)
