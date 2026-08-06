# PaceLab

[![CI](https://github.com/hermanno3005/pacelab/actions/workflows/ci.yml/badge.svg)](https://github.com/hermanno3005/pacelab/actions/workflows/ci.yml)

**Normalized Pace from grade, heat, and wind** — what you would have run in cool, flat,
still conditions at the same effort.

## Why

A run in July reads as lost fitness. Same route, same effort, ninety seconds a kilometre
slower than April, and the trend line says you have been getting worse all summer. You
have not; it was 30 °C.

Strava's grade-adjusted pace corrects the hills and ignores the weather entirely, so half
the story is missing exactly when it matters most. **Normalized Pace** strips the
conditions out — grade *and* heat — so what is left is the thing you actually wanted to
look at: whether you are getting fitter.

PaceLab analyses each **Activity** as it lands, and writes the answer back onto the
activity itself, where you already read it.

## What it looks like

An ordinary summer evening run from the author's corpus — 11.2 km on 24 June 2026, at
26 °C and 67% humidity — and the **Annotation** PaceLab wrote onto it:

```
🏃 PaceLab · NP 4:41/km (ran 5:33/km)
⛰️ grade +1 · 🌡️ heat +51 · 💨 wind +0 s/km (wind not in NP)
```

Fifty-one seconds a kilometre of that observed pace was the heat, on a route flat enough
and a day still enough that neither grade nor wind had anything to say. Three lines up the
trend from an April run at the same effort, this one no longer looks like a bad week.

The three components are the **Environmental Cost**, reported in full; only grade and heat
form the **Applied Cost** that was removed to get the **Normalized Pace**. The block is
spliced into the activity's description and replaced in place on every republish — it never
stacks, and it never touches your own text.

## How it works

```
FIT/GPX ──▶ Track ──▶ Segments ──▶ +Weather ──▶ Penalties ──▶ NP + decomposition ──▶ SQLite
  ingest    preprocess  (100 m)     weather      models[]       engine              store
```

- `ingest` — a FIT or GPX file becomes a stream of **Trackpoints**; every source is an
  adapter onto the same record.
- `preprocess` — the track is smoothed and cut into 100 m **Segments**, over which
  grade, bearing, and conditions are treated as locally constant.
- `weather` — each segment is enriched from a *pinned* reanalysis model, so the same run
  re-analysed next year gets the same weather (ADR-0004). Runs newer than the archive's
  publication lag get a **Provisional Analysis** from the forecast tier, marked `~`, and
  finalized automatically once the archive catches up.
- `models` — grade and **WBGT** heat each produce a **Pace Penalty**: a fractional
  slowing at constant effort. Wind produces one too.
- `engine` — the penalties are combined in pace space, never in mixed units. Grade and
  heat form the **Applied Cost** and come off the observed pace; wind is computed and
  reported but excluded from **Normalized Pace** (ADR-0005).
- `store` — the result and its per-segment inputs go to SQLite, stamped with the model
  version that produced them, and the **Annotation** is written back to intervals.icu
  (which pushes it on to Strava).

Why each of those is the way it is: `CONTEXT.md` for the vocabulary, `docs/adr/` for the
decisions.

## Commands

| Verb | What it does |
| --- | --- |
| `pacelab analyze <path>` | Analyse a local FIT/GPX file or directory. No network beyond weather. |
| `pacelab sync --from <date>` | Discover new activities from intervals.icu, analyse them, annotate them. |
| `pacelab recompute` | Reconcile activities already stored: re-analyse every row that disagrees with itself — stale model version, still provisional, never annotated — and republish it. Discovers nothing. |
| `pacelab publish --from <date>` | Re-write annotations for activities already analysed, without re-analysing them. |
| `pacelab watch` | The always-on loop: reconcile, then sync a rolling window, every tick, forever. |
| `pacelab health` | Is the loop alive and succeeding? Exit code is the whole interface. |
| `pacelab trend` | Normalized Pace over time — fitness with the conditions stripped out. |
| `pacelab calibrate` | Fit your own coefficients against your own corpus. Reports; applies nothing. |
| `pacelab snapshot` | Write one verified snapshot of the corpus (ADR-0018). |

**Sync** and **Recompute** are the pair worth keeping straight: sync asks the provider what
is *new*, recompute asks the store what is *stale*. A coefficient change reaches history
through recompute, never through sync.

## Setup — local

```sh
git clone https://github.com/hermanno3005/pacelab.git
cd pacelab
uv sync                                  # Python 3.11+, dependencies from uv.lock

uv run pacelab analyze path/to/run.fit   # no credentials needed for a local file

cp .env.example .env                     # then fill it in, see below
set -a; . ./.env; set +a                 # the CLI reads the environment, not the file
uv run pacelab sync --from 2026-01-01    # fetch, analyse, annotate
uv run pacelab trend
```

Credentials come from **intervals.icu** → Settings → Developer:

- `INTERVALS_API_KEY` — the API key on that page. Required.
- `INTERVALS_ATHLETE_ID` — your athlete id, the `iNNNNNN` in your intervals.icu URL.
  Optional; unset means the key's own owner. Set it, though: it is the **Account** key
  every stored row and cached file is filed under, so changing it later re-files nothing.

They are read from the environment and nowhere else — never from the store or from
`pacelab.toml`. `.env` is a convenience the container reads directly (`env_file`); a local
shell has to export them, which is what the `set -a` line above does.

intervals.icu is the only account you need: it already holds your activities from Strava
or your watch, and its description field is the **Publish Target** that pushes back to
Strava (ADR-0011). Weather comes from Open-Meteo, which needs no key.

The results database `pacelab.db`, the weather cache, and the downloaded FIT files all
land under the working directory.

## Setup — container

The intended home is a Raspberry Pi, running unattended (ADR-0013):

```sh
git clone https://github.com/hermanno3005/pacelab.git ~/docker/pacelab
cd ~/docker/pacelab
cp .env.example .env         # the same credentials
docker compose up -d --build
docker compose logs -f
```

`compose.yaml` builds from the checkout (`build: .`), so the whole repository has to be
there — a lone `compose.yaml` has no `Dockerfile` to build. CI also publishes an arm64
image to `ghcr.io/hermanno3005/pacelab`, tagged `:latest` and `:<sha>` and only ever from a
green test run; pointing compose at it instead of building is a one-line `image:` change.

- **The corpus lands in `./data`** beside `compose.yaml` on the host — bind-mounted at
  `/data`, so `pacelab.db`, the pinned weather cache, and the snapshots stay ordinary files
  that `sqlite3` and `scp` can reach without going through Docker (ADR-0015).
- **Poll cadence is 15 minutes** by default, over a rolling 14-day window, so an
  annotation appears within minutes of an upload and provisional analyses finalize as the
  weather archive catches up. `pacelab watch --interval` and `--window-days` change them.
- **`pacelab health` is the health predicate**, and the compose `HEALTHCHECK` runs nothing
  else. *Unhealthy* means one thing: **no successful tick within 3 × the loop's recorded
  interval** — 45 minutes at the default cadence. That single clause covers a dead loop, a
  wedged loop, and a live-but-failing loop alike, because all three stop producing
  successes. The threshold is derived from the interval the loop *recorded*, so it tracks
  whatever `--interval` you started it with. It reads a **Heartbeat** row that is not keyed
  by **Account**, so expired credentials report as unhealthy rather than crashing the probe.

```sh
docker compose exec pacelab pacelab health     # the verdict, plus last tick / last error
docker compose exec pacelab pacelab snapshot   # a verified backup, by hand
```

Nothing auto-acts on unhealthy yet: it colours `docker ps` and gives a future notifier
something to read.

## Configuration — `pacelab.toml`

Optional. A fresh clone needs no file at all: with none present the engine computes with
its shipped values, and `pacelab.example.toml` documents every key.

Copy it to `pacelab.toml` **beside your results database** (in the container, that is
`./data/pacelab.toml` on the host — compose needs no change). It carries two kinds of
number (ADR-0019):

- **The seven coefficients** — `k_grade`, `wbgt_ref_c`, `wbgt_a`, `wbgt_b`, `heat_a`,
  `heat_b`, `drag_area_per_mass`. These shape the penalty curves and are properties of
  *how the model was fitted*, not of what it normalizes to.
- **The reference altitude** — `home_elevation_m`, a fact about where you run, filling a
  slot in the frozen **Reference Conditions**.

Every key is checked: a misspelling or a non-numeric value fails loudly with the key
named, and never falls back silently.

> **The shipped coefficients were fitted to one athlete's corpus**, in one location, over
> one summer (`docs/research/calibration-findings-2026-07.md`). They are a starting point,
> not a calibration of you. `pacelab calibrate` fits `k_grade` and `wbgt_a` against your
> own runs and prints them next to what you are currently using; this file is where the
> ones you trust go.

**Changing a coefficient drifts your whole corpus.** The model version stamped on every
stored result is *derived* from the coefficients in force, so the moment you edit the file
every existing row is stale by definition — it was computed with different numbers. The
next `pacelab recompute` reconciles it: snapshot first, then re-analyse and republish every
drifted activity, one at a time. The reference altitude is excluded from the stamp, because
it changes no stored number and so must invalidate none.

## Status

v0.1 — it runs unattended on a Raspberry Pi and has been annotating a real corpus for a
season. What that does and does not mean:

- **Single-account by design, with multi-user seams.** One athlete's credentials, one
  corpus. But every stored row and cached file is already keyed by account, and a
  **Provider** takes its credentials by injection — so a second athlete is data, not a
  redesign (ADR-0009).
- **Wind is reported, not applied.** It is computed per segment, with the correct
  headwind/tailwind asymmetry, and shown in the decomposition — but it stays out of
  Normalized Pace until it is calibrated as well as grade and heat are (ADR-0005).
- **Adjusted Pace is not built.** The forward direction — projecting a goal pace *into*
  a forecast to get splits — is the inverse transform, and the engine's round-trip
  identity is already tested. The command is not there yet.
- **The heat curve is the least settled part of the model.** It is the one that most
  wants your own `pacelab calibrate` numbers.

## Development

```sh
uv sync            # exact dependencies from uv.lock
uv run pytest      # the whole suite
```

CI runs the suite on every push and only then publishes the image — an unattended Pi must
never be able to pull a tag built from a red suite. The badge at the top of this file is
that workflow.

## Docs

| Where | What |
| --- | --- |
| `CONTEXT.md` | The domain language — every capitalised term above (Normalized Pace, Pace Penalty, Annotation, Recompute…) is defined there, along with the words this project deliberately avoids. |
| `docs/adr/` | Why each decision went the way it did — the reference-conditions freeze, the WBGT model, wind's exclusion, the recompute contract. |
| `SRS_AdjustedPace.md` | The requirements the whole thing answers to. |
| `docs/runbooks/` | Operating it: pulling a snapshot off the Pi, restoring one. |
| `docs/research/` | The reading behind the models, and the calibration findings. |
| `CLAUDE.md` | How agents are expected to work in this repository. |

## Licence

MIT — see `LICENSE`.
