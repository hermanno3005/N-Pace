# Pin a specific reanalysis model (ERA5-Land→ERA5), not Open-Meteo `best_match`

Weather is fetched from Open-Meteo pinned to **fixed** models — ERA5-Land (~9 km) and ERA5
(~25 km) — rather than the API's default `best_match`.

**Field split (found by probing the live API):** ERA5-Land only carries temperature and
relative humidity; wind, cloud cover, and surface pressure are null there and come from
ERA5. The client fetches both models and merges per field — ERA5-Land where present, ERA5
otherwise — so temperature/humidity get the finer grid without losing the other fields.

`best_match` chooses a model per location/date and that choice can change over time, so
re-running an old activity could return different weather and silently shift a historical
NP. A pinned model keeps history deterministic (NFR-3); combined with the local cache
(keyed by grid-cell + hour) and the model-version stamp on each result (FR-10.2), re-runs
are network-free and frozen. The cost is slightly lower per-location accuracy than
`best_match` — acceptable, since wind is already confidence-tagged and the grid is coarse
by design.

Conditions are interpolated **linearly in time** to each segment's timestamp (a run spans
multiple weather hours); **space** uses the nearest grid cell at the segment's position
(bilinear is optional polish, low value at 9–25 km resolution).
