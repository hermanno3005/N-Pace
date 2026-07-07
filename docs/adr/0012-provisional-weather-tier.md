# Provisional weather tier: instant preview from forecast models, finalized by ERA5

Runs inside ERA5's ~week publication lag are analysed immediately against **Open-Meteo's
forecast API** (current ICON/GFS/ECMWF model runs, which cover the recent past) and stored
**provisional**; when the archive catches up, the next `sync` recomputes against pinned
ERA5, overwrites the result as final, and republishes the annotation. This is how
MeteoPace-class apps annotate instantly — they read forecast/observation-tier data; PaceLab
adds the self-correcting upgrade so history stays reanalysis-consistent.

**Why this doesn't break ADR-0004 (the reproducibility pin):**

- The provisional value is **never the final word** — every provisional result is replaced
  by a deterministic ERA5 recompute, so longitudinal NP comparisons (V-3) only ever rest on
  pinned-reanalysis data. The forecast tier is deliberately *not* pinned; drift is irrelevant
  for a preview.
- Forecast weather is **never written to the disk cache** (`WeatherService(disk_cache=False)`)
  — persisting a preview under the (cell, day) key would block the eventual ERA5 value. The
  disk cache stays ERA5-only.

**Honesty (NFR-2):** a provisional annotation marks the pace with a tilde — `NP ~5:15/km` —
removed on finalization. The store carries a `provisional` flag; the recompute clears it and
resets `published_version`, so the existing publish machinery replaces the block naturally.

**Sync semantics:** archive first; on `WeatherUnavailable` fall back to the forecast tier
(outcome `provisional`); both dry → `no-weather`, deferred. A stored provisional activity is
re-attempted every sync (never `skip`) until the archive serves its day (outcome
`finalized`); originals re-analyse from the immutable FIT cache without refetching.

In practice provisional vs final differ by a few percent at most; the annotation barely
moves — but the final number is always ERA5's.
