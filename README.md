# raw-data-for-digital-twin

Synthetic CSV data for a **digital twin of an organization's IT infrastructure**, at two scales,
plus the **schema graph** — the model — which is identical at both.

Nothing here is real. Every hostname, person, certificate, CVE, account number and site is
generated. There are no real credentials, no real people, and no real infrastructure in this
repository. It exists so an ETL pipeline can be built and tested against data with the shape of a
large enterprise, without needing one.

---

## What is here

```
data/small/     48 files,   6.9 MB    a complete estate: 42 entity types, ~7,100 nodes, ~20,600 edges
data/full/     132 files, 1051.0 MB    the same shape at ~995,700 nodes and ~3,501,900 edges
schema_graph/    5 files,  85.7 KB    the MODEL: 38 types, 31 relationship types, 38 spine entries
BUILD.json                           what was copied, what was split, and every sha256
```

### `data/<size>/`

A corpus in the pinned CSV dialect: scope-partitioned, UTF-8, LF line endings, `NULL` as an
unquoted `\N`, temporal block contiguous and last. `manifest.json` declares the observation window
and the schema version; `run_report.json` and `generate_report.json` are the generator's own
account of the run that produced it.

**The scope is a property of the path.** A file under `orgs/acme/` carries `organization_id`; a
file under `global/` does not. A file whose columns contradict its directory is a corpus error,
not a formatting preference.

### `data/full/` has two split files

Two files exceed GitHub's **100 MB hard block** and would be rejected outright:

| file | size | parts |
|---|---:|---:|
| `orgs/acme/relationships.csv` | 719.8 MB | 72 |
| `orgs/acme/source_refs.csv` | 111.6 MB | 12 |

Each is split into 10 MiB parts under `parts/<stem>/`, with a `MANIFEST.json` carrying a sha256
for **every part and for the original file it was cut from**. Reassembly is exact and needs no tool:

```sh
cd data/full/parts/relationships
cat relationships.part*.csv > relationships.csv
sha256sum relationships.csv      # must equal MANIFEST.json's source_sha256
cd ../source_refs
cat source_refs.part*.csv > source_refs.csv
```

Same on Windows PowerShell:

```powershell
cd data/full/parts/relationships
Get-Content relationships.part*.csv -Raw | Set-Content -NoNewline relationships.csv
```

**Compression was not used because it does not solve it:** `relationships.csv` gzips to ~115 MB,
still over the limit. Splitting is lossless, needs no Git LFS quota, and clones instantly.

### `schema_graph/` — and why it is the most useful small file here

`schema.graphml` is **byte-identical at both scales** (`sha256 dc493a57134b6489`, 70,928 bytes),
and so are `types.parquet`, `relationships.parquet` and `spine.parquet`.

That invariance is the point. The schema graph answers *"what kinds of thing can exist and how may
they connect?"* — 107 nodes: 38 entity types, 31 relationship types, 38 containment-spine entries,
and **no row from the estate's vocabulary at all**. The estate graph answers *"what actually
exists, at this coordinate?"*, and that is the one that scales.

**A schema that grew with the data would be a schema describing the data.** If you build a loader,
check this property holds on your own output: generate at two scales, and the schema graphs should
be identical. If they are not, something in your pipeline is reading the data to decide the shape.

---

## What this data is FOR

It is shaped to support a **sophisticated ETL pipeline for huge enterprises** — the kind that
ingests a real CMDB export, resolves identity across sources, and keeps a bitemporal history so a
question about March can be answered as it was known then.

The properties that make it useful for that, and that a naive generator would not give you:

- **Identity is derivable.** `id = {org}:{type}:{slug}~{hash12}`, a pure function of
  (organization, entity type, natural key). No lookup table needed; a collision always fails.
- **Time is bitemporal.** Four time columns: `valid_from`/`valid_to` is when it was true in the
  world, `system_from`/`system_to` is when the twin learned it. `NULL` means *no end known* and
  nothing else. Ends are recorded rows (`operation = retract`), not closed intervals.
- **A retract does not close its predecessor in transaction time.** This is the single most
  important property in the set, and getting it wrong is silent: a table that ended on 1 April
  disappears from every as-of coordinate before its end, so a question about March cannot see it.
  A validator rule enforces it, and it found three violations in hand-built fixtures on the day it
  was written.
- **The schema version rides transaction time.** An as-of coordinate is the triple `(V, S, K)`
  with `K = f(S)`. A model that did not exist cannot say "no" about anything, so coordinates before
  the first version **refuse by name** rather than answering with today's model.
- **Absence is a named state, not a zero.** An entity the twin has not learned is
  `not_yet_known`; one whose belief was superseded is `retrospective_gap`; one that ended is
  `expected_dead`. A row count is never an answer.

---

## Known caveats — read before you rely on any of this

These are real and deliberate. They are recorded here because a data repo that hides them is worse
than one that omits the data.

1. **The observation window is a declaration the data honours.** `data/small` covers
   `[2026-01-01, 2027-04-25]`. Five years of *pre-window* estate is generated on purpose — an estate
   whose history starts at the window would be a snapshot pretending to be a history. Those rows
   exist, and asking about a coordinate inside them **refuses by name** rather than answering.
2. **A corpus's window must be contained in the model's window, one-directionally.** A model window
   may and must extend past a corpus's end: a model is in force for corpora not yet generated.
   Requiring them to end together is the freeze this design rejects.
3. **The generator's default leaves one table with two in-force `designated_data_tier`
   relationships**, and the reader refuses that corpus by name. The published artefacts were
   generated with the producer-side fix; the naive output is reproducible and is *not* what is here.
   A demotion must be a **retract of the existing relationship id**, not a second assert — an
   identity is a pure function of `(type, from, to)`, so asserting the id twice is a violation of
   uniqueness, not a fix.
4. **The full-scale corpus has never been validated by the rule engine**, because the engine keeps
   every row as a dict at ~2,373 bytes/row, which projects to ~11.9 GB at 5.45 M rows. The
   small-scale corpus is validated: **3,833 findings across 10 named causes, 0 unclassified.**
5. **Every claim the twin makes is currently capped at `claim_strength: unknown`**, and the
   "departed administrators" question refuses on all three paths. That is the gate working, not a
   bug — the twin declines to assert more than it can support — but it means nothing here should be
   read as an established fact.
6. **One security rule computes the wrong quantity and was deliberately left unfixed.**
   `public_certificate_expiring_with_notice_window` is titled for the renewal-notice window and
   computes the *age* of the interval: it fires on certificates with 1,905 days of validity left
   and is silent on any inside 30. It is left visible rather than patched because a rule whose
   direction is ambiguous is worse to flip silently than to report loudly. **If you consume these
   findings, ignore this rule.**

---

## Provenance

Generated by the `digital-twin` project and verified by a checker that re-derives the fold from the
corpus and compares CSV against Parquet against GraphML, across three coordinates, with no
sampling: **411 checks at full scale, 379 at small, 0 failed.** The estate check count did not
change when the checker was refactored to stream, so bounded memory was not bought by checking less.

Composition, the domain mix, the event schedule and every parameter are in `data/<size>/*.json`.
