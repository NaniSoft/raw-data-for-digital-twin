# The viewer, and what it can and cannot do

Generated from the artefacts in this repository. **Neither view is a second source of truth** —
both are projections of the same corpus, and if a view and the CSVs ever disagree, the CSVs are
right and the view is a bug.

## What is here

```
viewer/
  explorer.py        HTTP client over the Parquet substrate
  build_site.py      generates the static per-entity site
  layout.py          computes the layout relation
  layout/            the layout relation itself (14.6 MB, derived)
  site_sample/       400 entity pages + index, so the shape is visible
answers/
  questions.json     the four canonical questions, their answers and their claim strengths
  slice_report.json  the end-to-end run that produced them
```

**The full 1M-node site is not committed — it is 35,347 pages and 348 MB, and it is regenerable in
84.5 seconds from the CSVs already in this repository.** The generator is here; the sample is proof,
not a substitute.

## Two views, two very different shapes of problem

### The explorer — query latency is not the problem

Over the Parquet substrate: estate frame **15.1 ms**, drill **7.8 / 83.0 / 221.6 ms** at increasing
fan-out. It renders a node with its own type's columns, a neighbourhood through the pinned depth-6
traversal template, and all twelve registered questions.

**It cannot read GraphML, and that is deliberate** — a tripwire on `open` raises if you try. The
estate graph is 1.61 GB of GraphML at 1M nodes and GraphML has no partial-read protocol, so a graph
too large to load cannot be traversed out of GraphML at all. Parquet plus DuckDB is the substrate;
GraphML is an export format for other tools.

**It has no global picture at all.** That is structural, not a budget decision.

### The static site — coverage is excellent, structure is the wall

At 1M over 30 days: **35,347 pages in 84.5 s, all 35,336 entities covered, 790,258 links, 0 broken,
0 orphans.** `--scope all` is refused by name, with its measured cost printed.

The site's wall is that **77% of its links are `data-outside`**, and its window is the only way to
address anything in it.

## The two clocks, printed side by side because they differ by 100x

| | time |
|---|---|
| explorer drill, over Parquet | 7.8 – 221.6 ms |
| twelve questions, over **1.10 GB of CSV** | **61.1 s** (4.31 s to open, 3.8–7.2 s each) |

The question path is slow **by decision**: `schema/query` is deliberately not a fold consumer, so a
question is answered against the corpus rather than against a pre-folded projection that might be
stale. That is a correctness choice with a latency cost, and it is the right one.

## What you will hit within five minutes

**The explorer: the hub.** `organization` has **372,093 out-edges in one hop** and 690,641 at depth
2. **Depth is not a scale control at 1M — degree is.** The facet that works is the *target type*
(26-way), taken from the schema's own declared spine, which is why that spine being size-invariant
turns out to matter in practice and not only in principle.

**The site: the 77% wall**, and the window as its only address.

## Why the layout is not a node attribute

A shipped check asserts it, and the reason is not tidiness: **a node's position is not a function of
the node.** The same `compute_node` sits at different coordinates in the `estate` and `neighbourhood`
scopes, and the scope is a property of the *query* — exactly as `claim_strength` is. Putting a
position on the node would make it a second source of truth, break byte-identical folds, and mean the
estate graph said something the estate graph cannot know.

Two radial instruments, both on *declared* trees: `spine_radial` over the schema's 38-row spine, and
`neighbourhood_radial` over the traversal's own `depth_reached`.

## The answers, and how far to trust them

| | claim strength | result | met? |
|---|---|---|---|
| Q1 exploitable-and-unpatched, who owns | `unknown` | 134 reachable hosts | **No** — the estate records **no edge** from a product to a vulnerability. A data gap, not a query gap. |
| Q2 what a service account can reach | `unbounded` / `observed_within_declared_gap` | 13 privileges, 8 services, 10 datastores, 210-service blast radius | **Partly** — the legs, yes; "this service account" is estate-wide. An implementation shortcut. |
| Q3 departed administrators still active | `unbounded` | **3 departed authorisers, 5 system grants, longest 635 days** | **Yes**, for the people. |
| Q4 PII unencrypted behind a user subnet | `unknown` | 38 tables, 137 user-facing hosts | **No** — the conjunction *is* the question, and the query language has no join operator, by decision. |

**The Q3 finding is the reason this repository is worth having:** one account is
`account_type=person`, still enabled, holding a system-privileged role **294 days after its authoriser
left**.

**`q3_as_thought_then` is registered beside its twin on purpose.** Asked as known in March it returns
**0 at rung `unbounded` with `estate_state: read`** — a confidently wrong "nobody". That is why the
as-thought-then question is a separate registration and not a parameter.

## Three defects found while building this, none of them the viewer's

1. **`check_versioning.estate_diff` returns 38 rows for 19 types** — every type doubled — **and
   both diffs are functions of the reader's timezone.** Neither is runnable on a shipped corpus at
   any size, so the schema-stability diff has only ever run on a fixture.
2. **The per-type Parquet files hold only `present` nodes.** A type-resolving read therefore loses
   every dead entity *while the count stays right* — **11.9% of the estate cannot have its attributes
   read at all, and no count reveals it.**
3. **Retracted during the work:** `certificate` was first reported as a divergence between two
   published artefacts. It is not — the estate is complete, and the error was **reading a missing
   file as a missing population.** Two different failures that look identical from the outside.

Source of truth for all of this is the `digital-twin` project; the paths in the code are relative to
that repository, not to this one.
