# `viewer/` — can a human actually see this?

Two views over the published artefacts. Neither is a second source of truth: the coordinate comes
from the snapshot's manifest, the change set from the corpus, the attributes from the per-type
Parquet, and the positions from a layout relation keyed by scope. Every number below was measured on
`artifacts/full` (995,727 nodes / 3,501,949 edges) and is reproduced in
`.scratch/digital-twin/issues/14-viewer-explorer-and-static-corpus.md`.

## The four files

| file | what it is |
|---|---|
| `substrate.py` | the ONE place the substrate is opened. The lead-block rule, the per-type resolution rule, the timezone pin, and the GraphML tripwire. |
| `layout.py` | the layout relation: two instruments in a closed vocabulary, keyed by `(layout_scope, entity_id)`, with an envelope that reports truncation. |
| `explorer.py` | the HTTP client. Renders the estate frame, a node, a neighbourhood, and the twelve registered questions. |
| `build_site.py` | the static As-Of corpus: a per-entity site with back-links, a paged changelog, and the As-Of diff. |
| `check_viewer.py` | twenty criteria, each watched failing on a real mutation applied to a **sandbox copy**. |

## The explorer

```
python viewer/explorer.py --graph artifacts/full/graph_estate --schema artifacts/full/graph_schema \
                          --corpus artifacts/full/csv --port 8731
python viewer/explorer.py --graph ... --schema ... --write-estate-layout   # once
```

It never opens the estate GraphML, and that is a control rather than a promise:
`substrate.install_graphml_tripwire()` wraps `builtins.open`, `io.open` and `os.open` and raises on
any `.graphml` path. The guillotine watches it fire.

Routes: `/`, `/types`, `/type/<entity_type>`, `/node/<entity_id>`,
`/neighbourhood?seed=&depth=`, `/questions`, `/question/<id>`, `/graphml`, `/timings`, `/health`.

**It has two clocks and prints both.** A drill reads the Parquet substrate: 7.8 ms for one hop out
of a segment, 83.0 ms for depth 2, 221.6 ms for depth 3. A registered question reads the whole
1.10 GB corpus — because `schema/query` is deliberately not a fold consumer — at 3.8–7.2 s, and
all twelve cost 61.1 s. The first question also pays 4.31 s to open the corpus.

**The first thing you hit is the hub.** The `organization` node has 372,093 out-edges in one hop and
690,641 nodes at depth 2. Faceting by relationship type does nothing (it emits exactly one,
`contains`); faceting by **target type** splits it into 26, and that facet list is the schema's own
declared spine.

## The static As-Of corpus

```
python viewer/build_site.py --graph artifacts/full/graph_estate --schema artifacts/full/graph_schema \
                            --corpus artifacts/full/csv --out viewer/out/site_30d \
                            --scope "window:2027-03-26T00:00:00Z..2027-04-25T23:59:59Z" \
                            --diff  "2027-03-26T00:00:00Z..2027-04-25T23:59:59Z"
```

A 30-day window at 1M builds in **88.7 s**: **35,347 pages, 350 MB, 790,258 links, 0 broken
back-links, 0 orphan pages.** Every one of the 35,336 entities the change set names has a page.

`--scope all` is **refused by name** (`scope_all_is_refused`) with the measured cost in the message.
The site's address is its window.

Every link is one of exactly two kinds and there is no third: **inside** the scope, resolving to a
page this build generated; or **outside** it, carrying `data-outside` naming the substrate query
that would fetch it. A link that is neither is a broken back-link and fails the run.

## The layout relation, and why it is not a node attribute

`check_sync.py` already reserved the shape: `LAYOUT_ATTRIBUTE_NAMES` is refused on any node, and
`sync.layout_is_not_a_node_attribute` is the shipped check. Computing it was this ticket's job.

**Three reasons, and the third is the one only a viewer can measure:**

1. a position on the node is a second source of truth, so two folds of one corpus stop being
   byte-identical;
2. it puts a presentation decision inside the estate;
3. **a node's position is not a function of the node.** The same `compute_node` sits at one
   `(x, y)` in the `estate` scope and a different one in `neighbourhood:<its data store>@d2`,
   because the two scopes are two pictures of two different sets. There is nothing for a node
   attribute to hold, and one of the two scopes would be rendering a lie. The scope is a property of
   the query that produced the view, exactly as `claim_strength` is a property of the query and not
   of the entity — which is why the layout has an envelope and the envelope can refuse.

**Force-directed layout is not the answer and the reason is structural.** Not CPU: the estate is
laid out in **4.5 s**, one sort, no simulation, by `spine_radial` — a radial arrangement on the
schema's own 38-row declared spine, with equal angular sweep per type so a type's arc density *is*
its size. And `neighbourhood_radial` lays a traversal out on **its own `depth_reached`**, read from
`traverse.py`'s pinned template rather than recomputed, so this package holds no breadth-first
search to disagree with the shipped one. Both are deterministic with no RNG and no force iteration,
which is why `C7` is a criterion at all: a layout that cannot be reproduced is a picture, not an
artefact.

## The guillotine

```
python viewer/check_viewer.py               # the control: 20 criteria, ~13 s
python viewer/check_viewer.py --self-test   # 20 mutations, each must fail
```

The self-test copies the substrate into a temporary directory, damages the copy, re-runs the
control, and requires that criterion to fail. It then asserts the **published** tree still matches
`run_report.json` byte for byte. That assertion is there because the first version of this self-test
damaged `artifacts/small` and `artifacts/full` directly; both were restored with
`publish.py --reuse-corpus` and verified against every recorded file size.

Five of the twenty mutations are worth reading, because four of them were no-ops on the first
attempt and the criterion was right to pass each time:

- `C6` first rewrote every parent link to `acme:organization:acme~...`, which **is** a real edge
  source for nearly every entity — a mutation that cannot make the thing wrong is not a mutation;
- `C7` first scaled the polar map by 1.0001, which changes the geometry and leaves determinism
  intact, because both runs go through the same perturbed function;
- `C7`'s fixture was also too small to test: the first `network_segment` at depth 3 reaches **2
  nodes** at the small size, so a determinism criterion over it is a coin;
- `C9` asserted "no `.graphml` was opened", which is a state the control can never be in, because
  the tripwire raises. **A prohibition enforced by an exception is a boundary, not a checkable
  state** — the criterion now asserts the refusal;
- `C9`'s first three mutations were all no-ops, and the last one only worked after
  `install_graphml_tripwire` was made idempotent and `remove_graphml_tripwire` was added. **A
  control that cannot be removed cannot be shown to be the thing doing the work.**
