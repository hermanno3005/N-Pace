# Coefficients become data, and their values reach `model_version`

The seven numbers that turn a **Pace Penalty** into a slowing were fitted to one athlete's
corpus in one location (`docs/research/calibration-findings-2026-07.md`). They live in
`config.py`, so anyone else who runs `pacelab analyze` gets a **Normalized Pace** computed
with my heat curve and calls it theirs, and the only way to change that is to fork and edit
`src/`. `pacelab calibrate` makes this worse rather than better: it reports coefficients the
athlete has nowhere to put.

This ADR decides that the coefficients — and the reference altitude — become data supplied
per installation through an optional `pacelab.toml`, read from the directory holding the
results database. Absent, the engine behaves exactly as it does today. The corpus directory
is the lookup location because the **Watch** container's working directory *is* the
bind-mounted corpus directory, so the file arrives through a mount that already exists.

## The surface is the reference altitude plus the seven coefficients

`home_elevation_m`, `k_grade`, `wbgt_ref_c`, `wbgt_a`, `wbgt_b`, `heat_a`, `heat_b`, and
`drag_area_per_mass`. What is left out is left out for a reason:

- **`apply_wind` stays a CLI flag.** ADR-0005 makes wind-in-NP a per-invocation reporting
  choice, not a property of an installation. Admitting it to the file would create a
  configured value that changes the **Applied Cost** — and therefore every stored NP —
  without the version story the rest of this ADR builds, since the flag is a decision about
  what to report rather than a coefficient that can be hashed alongside the others.
- **`step_m` and `reference_temp_c` stay in code.** `step_m` is a pipeline constant; changing
  it changes what a **Segment** is, which is a model change, not a personalisation.
  `reference_temp_c` is a term of the **Reference Conditions**, and those are frozen
  (ADR-0002). Neither is a personal tunable.
- **`model_version` is never settable.** It is derived, never declared.

## Filling the home-altitude slot does not unfreeze ADR-0002

Read carelessly, this ADR and ADR-0002 contradict each other: one freezes the baseline, the
other lets an installation change part of it. They do not.

What ADR-0002 freezes is the *definition* of the **Reference Conditions** — 0% grade, 10 °C,
50% RH, no wind, no sun, **home altitude**. "Home altitude" is a slot in that definition, and
it has always been one: ADR-0002 itself says the reference is home altitude rather than sea
level "so that running at home in still air incurs no spurious air-density penalty; the
home-elevation value lives in config." The number that fills the slot is a fact about where
an athlete runs, not a tunable that trades accuracy for convenience. An installation in
Denver and one in Rotterdam are both normalizing to the same frozen definition; they are not
running two different models.

The frozen thing is the meaning of NP — "equivalent ideal cool-weather pace, at home." That
meaning is unchanged by this ADR, and nothing here re-opens it.

## Coefficient values must reach `model_version`

`model_version` exists so a re-tune can recompute history consistently (FR-10.2). ADR-0016
makes **Recompute** the mechanism by which "a coefficient re-tune reaches history", and it
finds its work with a query that compares each **Activity**'s stored `model_version` against
the running one.

That comparison works today only by accident of where the coefficients live. They are in
code, and the version is a string in the same file, bumped by hand in the same commit — so
"the model changed" and "the version changed" are one act. Once coefficients are data, the
two come apart. Editing `wbgt_a` in `pacelab.toml` changes every number the engine produces
while leaving the declared version untouched; the corpus stays stamped as current,
**Recompute** enumerates nothing, and history silently disagrees with itself. Worse, it
disagrees *invisibly*: the annotations on intervals.icu still look current, and a `calibrate`
fit would run across a corpus whose rows were produced by two different models without saying
so — the mixed-corpus failure ADR-0016 went out of its way to make loud.

So the effective coefficient values are canonicalised and hashed into a short stable digest
appended to the declared version: `0.2.1+<digest>`. Derived from the values themselves, not
from the file's presence or its modification time, so two installations with identical
coefficients produce comparable stamps and a no-op file that merely restates the defaults
costs nothing.

Nothing downstream needs to change. `needs_recompute`, `is_current`, and `needs_publish`
already do exactly the right thing once the stamp moves, and ADR-0018's **Snapshot** — taken
before a **Recompute** rewrites rows at a new `model_version` — covers the coefficient case
for free. A bad re-tune is recoverable by the path that already exists.

## `home_elevation_m` is excluded from the derivation

It is declared in `Config` and read nowhere in `src/`: an inert slot documenting the altitude
term of the **Reference Conditions**, with no air-density model behind it yet. A value that
cannot change a stored number must not invalidate a stored number, so changing the reference
altitude leaves the version — and therefore the whole corpus — alone. The alternative would
charge a full re-analysis and a republish of every **Annotation** for a change that alters
nothing.

If a future model consumes it, it moves into the digest in the same commit that makes it
load-bearing.

## Defaults produce the bare declared version

When no configuration file is present, *and* when a file is present that sets every
coefficient to its shipped value, the version is the bare `0.2.1` — no suffix.

This is load-bearing rather than tidy. The existing corpus is 55 **Activity** rows stamped
`0.2.1`. Any scheme that suffixed the default version would mark all of them drifted the
moment this change shipped, and the next **Watch** tick would re-analyse and republish every
one of them. That would be *safe* — a **Snapshot** precedes it, weather is pinned and cached
(ADR-0004), FIT files are cached (ADR-0008) — but it would rewrite 55 public descriptions to
produce bit-identical numbers. Invalidating a corpus is a real cost and is only ever paid for
a real change.

## Rejected: a README caveat

The obvious cheap alternative is to say it in prose — "these coefficients were fitted to one
athlete; your numbers will be somewhat wrong" — and stop there. It was rejected because it
documents the limitation instead of removing it. The reader learns that their **Normalized
Pace** is not theirs and is given nothing to do about it short of forking, and `pacelab
calibrate` remains a report with no destination. A caveat that cannot be acted on is an
apology, not a decision.

## Rejected: bumping the declared version by hand on a re-tune

Keeping `model_version` hand-written and asking the operator to bump it after editing
`pacelab.toml` preserves ADR-0016 exactly as written, at the cost of making corpus
consistency depend on remembering. The failure is silent, unbounded in time, and lands on the
one surface — history — the version stamp exists to protect. Deriving the suffix removes the
opportunity to forget.
