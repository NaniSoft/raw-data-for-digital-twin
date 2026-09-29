"""The layout relation, computed. Keyed by ``(layout_scope, entity_id)``, never a node attribute.

What this module decides, and why
==================================

``schema/graph/check_sync.py`` already reserves the shape: ``LAYOUT_ATTRIBUTE_NAMES`` is
``{x, y, z, pos, position, layout_x, layout_y, layout_z, layout, community, cluster, force_x,
force_y, radius}`` and ``sync.layout_is_not_a_node_attribute`` fails if any node in any artefact
carries one. The reservation was made by ticket 09; computing it is this ticket's job.

**Why a position cannot be an attribute of the node**, in three reasons, the third of which is
the one only this ticket can measure:

1. It is a **second source of truth** about the node. Two folds of the same corpus stop being
   byte-identical, and byte-identical folds are what the whole fold is for.
2. It puts a **presentation decision inside the estate**, so a client that reads positions out of
   the estate is reading a picture and thinks it is reading the estate.
3. **A node's position is not a function of the node.** The same ``compute_node`` sits at
   ``(x, y)`` in the ``estate`` scope and at a different ``(x', y')`` in the
   ``neighbourhood:<its data store>`` scope, because the two scopes are two different pictures of
   two different sets. There is no single correct position, so there is nothing for a node
   attribute to hold -- and one of the two scopes would be rendering a lie. **The scope is a
   property of the query that produced the view**, exactly as ``claim_strength`` is a property of
   the query and not of the entity.

What is the answer at 1M, and what is not
==========================================

**Force-directed layout is not the answer, and the reason is structural rather than a matter of
taste or of CPU time.** Three measurements, all at 1M on ``artifacts/full/graph_estate``:

* The traversal is depth-capped at 6 by contract, and a hub defeats depth anyway. The
  ``organization`` node has **372,093 out-edges in one hop** (186x a 2,000-node render budget) and
  **690,641 nodes at depth 2**. Faceting by *relationship type* does not help: the organization
  emits exactly one, ``contains``.
* Faceting by **target type** does help, and the facet list is the schema's own declared spine --
  38 rows, byte-identical at every corpus size, which is the measured invariance that lets a
  viewer load the schema at 1M and know it is complete. Even so, faceted, the organization's fan
  is 26 facets of which only 1.0% of the edges fall under budget, because the organization *is*
  the estate.
* So **depth is not a scale control at 1M; degree is**, and no single picture contains the
  estate. The estate is rendered as an **aggregate** (42 types, 15.1 ms) and every picture is
  **local**.

So the layout relation ships **two instruments in one closed vocabulary**, both radial, both on a
*declared tree*, both deterministic with no RNG and no force iteration:

``spine_radial``
    The whole-estate frame. The tree is the schema's declared **spine**; a type's ring is its
    distance from the nearest spine root, and its entities are spread along that ring's arc in
    ``entity_id`` order. 995,727 rows, one sort, no simulation. It is what answers *"where in the
    estate is this thing"*, which is the question a person asks when a query returns an id they
    have never seen -- and it is a lookup, not a rendering.

``neighbourhood_radial``
    The local frame. The rings are **the traversal's own ``depth_reached``**, read from
    ``schema/graph/traverse.py``'s pinned template rather than recomputed, so this module keeps no
    breadth-first search of its own. The parent link is a **declared tie-break** over the edges
    into a node from the ring below, not a second traversal; ``check_viewer``'s C6 proves every
    such link is a real edge in the substrate.

Both instruments agree on which angle a type gets, because the sector order is one constant,
:data:`TYPE_SECTOR_ORDER`, and it is the schema's spine breadth-first order. One vocabulary, two
instruments.

The envelope
============

Every scope carries an envelope, and the two fields that are load-bearing are
``rows_available`` and ``truncated``. A scope over the render budget **truncates and says so**
(D23's ``closure.depth_cap``: "truncates rather than stops, and the cap is part of the answer, not
a setting"), and a scope under it says ``truncated: false`` with a row count that a reader can
compare against the traversal's own count -- which is the independent expectation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any, Iterable, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in __import__("sys").path:
    __import__("sys").path.insert(0, HERE)

from substrate import LEAD_BLOCK, Substrate, ViewerRefused  # noqa: E402

LAYOUT_VERSION = "layout-v1"

#: The closed algorithm vocabulary. Closed because a position a client cannot name is a position
#: a client cannot re-derive, and a layout nobody can re-derive is a picture, not an artefact.
LAYOUT_ALGORITHMS: dict[str, str] = {
    "spine_radial": (
        "The whole-estate frame. The tree is the schema's declared SPINE: a type's ring is its "
        "distance from the nearest spine root, and a type's entities are spread along that ring's "
        "arc in entity_id order. Deterministic, one sort, no simulation, and identical for a "
        "substrate of any size because the spine is byte-identical at every size."),
    "neighbourhood_radial": (
        "The local frame. The rings are traverse.py's OWN depth_reached, read from the pinned "
        "template rather than recomputed, so this module holds no breadth-first search. The "
        "parent link is a declared tie-break over the edges into a node from the ring below, and "
        "check_viewer's C6 proves every such link is a real edge in the substrate."),
}

#: How many nodes one view may place. 2,000 is not a taste: it is the same operating point
#: ``traverse.py``'s own docstring reaches for ("a couple of thousand nodes" is where a reachable
#: set stops being readable), and the budget is a PARAMETER a client may lower and never raise.
RENDER_BUDGET = 2000

#: The scope vocabulary. Data, never a string a client composes: a scope that is a format string
#: is a second source of truth about what a view contains.
SCOPE_KINDS: dict[str, str] = {
    "estate": "the whole estate, laid out on the declared spine. One row per node.",
    "neighbourhood": "one depth-capped traversal from one seed, laid out on its own depths.",
}


class LayoutRefused(ViewerRefused):
    """A layout refusal. Same closed-reason discipline; its reasons live below."""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in LAYOUT_REFUSALS:
            raise KeyError(f"{reason!r} is not a layout refusal; the vocabulary is closed: "
                           f"{sorted(LAYOUT_REFUSALS)}")
        self.reason = reason
        self.detail = detail
        Exception.__init__(self, f"{reason}: {detail or LAYOUT_REFUSALS[reason]}")


LAYOUT_REFUSALS: dict[str, str] = {
    "layout_algorithm_not_in_the_closed_vocabulary": (
        "A layout that names an instrument outside the closed vocabulary is a position nobody can "
        "re-derive. Two instruments ship, both radial, both on a declared tree."),
    "layout_is_a_relation_not_a_node_attribute": (
        "A position on a node is a second source of truth about the node and it puts a "
        "presentation decision inside the estate. `sync.layout_is_not_a_node_attribute` is the "
        "shipped check; the layout is a separate relation keyed by (scope, entity_id)."),
    "layout_scope_over_the_budget_is_refused_when_asked_to_place_it_all": (
        "A scope may be TRUNCATED and say so, and that is the normal case. It may not be asked to "
        "place every node of a 372,093-neighbour fan-out silently: `truncate=false` on a scope "
        "whose rows_available exceeds the budget is a refusal, not a layout."),
    "layout_needs_a_schema_dir": (
        "The estate frame is laid out on the schema's declared spine, and the spine is a separate "
        "artefact. Without it there is no tree, and a radial layout on no tree is a scatter plot."),
}

#: The four-column lead block, re-exported so a consumer of a layout does not have to know that
#: a layout joins back to a four-column node relation and not to a per-type one.
NODE_LEAD_BLOCK = LEAD_BLOCK

POSITION_COLUMNS = ("entity_id", "entity_type", "x", "y", "ring", "sector", "angle_deg",
                    "parent_entity_id")

ENVELOPE_COLUMNS = ("layout_scope", "layout_scope_kind", "layout_algorithm", "layout_version",
                    "seed_entity_id", "depth_requested", "depth_cap", "direction",
                    "row_budget", "rows_available", "rows_placed", "truncated",
                    "truncation_rule", "estate_state", "valid_time_window",
                    "coordinate_valid", "coordinate_system", "corpus_fingerprint",
                    "substrate_version", "digest")

_TRUNCATION_RULE = (
    "closure.depth_cap -- truncates rather than stops, and the cap is part of the answer, not a "
    "setting (D23). A scope under the budget says truncated=false with rows_placed == "
    "rows_available; a scope over it says truncated=true and rows_available is the number the "
    "traversal itself returned, so a reader can check the truncation against the traversal rather "
    "than against this module.")


# ------------------------------------------------------------------------------- the sector order

def type_sector_order(spine: Sequence[dict[str, Any]]) -> list[str]:
    """Types, in the spine's own breadth-first order, and that order is the ANGULAR order.

    One constant, two instruments. A ``network_segment`` and the ``organization`` it hangs off
    are adjacent on the wheel in both the estate frame and the neighbourhood frame, which is what
    makes the two pictures comparable rather than two unrelated pictures.
    """
    parent: dict[str, str | None] = {}
    for row in spine:
        p = row.get("parent")
        parent[row["type_name"]] = p if (p and p in parent or p is None) else None
    roots = sorted(t for t, p in parent.items() if p is None)
    order: list[str] = []
    seen: set[str] = set()
    frontier = list(roots)
    while frontier:
        nxt: list[str] = []
        for t in sorted(frontier):
            if t in seen:
                continue
            seen.add(t)
            order.append(t)
            for child in sorted(c for c, p in parent.items() if p == t and c not in seen):
                nxt.append(child)
        frontier = nxt
    for t in sorted(parent):           # a type the walk missed, e.g. a guarded override
        if t not in seen:
            seen.add(t)
            order.append(t)
    return order


def _ring_of_type(spine: Sequence[dict[str, Any]]) -> dict[str, int]:
    """A type's ring: its distance from the NEAREST spine root.

    The spine has seven roots (six core types with no parent, plus the four pack types it records
    as ``undeclared``), so this is a forest and the ring is a minimum, not a path length. A type
    with a guarded override (``site``'s parent moves under ``aws.aws_account`` but the override
    keeps ``organization``) is laid out on its DECLARED parent, because the spine is the
    authority and a viewer that re-derived the override would be a second topology.
    """
    parent: dict[str, str | None] = {r["type_name"]: r.get("parent") for r in spine}
    ring: dict[str, int] = {}

    def depth(t: str, guard: frozenset[str]) -> int:
        if t in ring:
            return ring[t]
        if t in guard:                 # a cycle in a declared parent chain: ring 0, and named
            return 0
        p = parent.get(t)
        if p is None or p not in parent:
            ring[t] = 0
            return 0
        got = depth(p, guard | {t})
        #: Memoised on the way OUT, which is the whole point. The spine is a forest of 38 types
        #: with NINE roots (measured, not assumed: affected_product, the four aws.* pack types,
        #: organization, product_model, vendor, vulnerability), so without the memo every type
        #: re-walks its own chain to a root and `ring` is 0 for all of them -- an estate frame in
        #: which the entire estate is ONE CIRCLE. It rendered, and it was wrong, which is the
        #: worst of the three ways a layout can fail. An earlier draft computed the right depth
        #: and returned it without storing it.
        ring[t] = got + 1
        return ring[t]

    for t in sorted(parent):
        #: The guard starts EMPTY, not holding ``t``. A guard seeded with ``t`` would return 0 on
        #: the first line for every type -- which is a second way for the whole estate to become
        #: one circle, and the reason the first draft of this function was wrong twice rather
        #: than once. The cycle check is the guard's job on the way DOWN, not the seed.
        depth(t, frozenset())
    return ring


# ------------------------------------------------------------------------------- the two algorithms

def _polar(ring: int, angle_deg: float) -> tuple[float, float]:
    """Ring radius and angle to a point. A pure function, rounded to 4 places.

    Rounded because a Parquet file of 995,727 float64s whose last bits differ between two runs is
    not byte-identical, and byte-identical is the standard this repository holds everything to.
    The rounding is 1e-4 of a unit on a 100-unit canvas, which is 1/100 of a pixel at any
    rendering size a person can read.
    """
    r = 100.0 * ring
    a = math.radians(angle_deg)
    return round(r * math.cos(a), 4), round(r * math.sin(a), 4)


def spine_layout(sub: Substrate, scope: str = "estate", *,
                 budget: int = RENDER_BUDGET) -> dict[str, Any]:
    """The whole-estate frame: one row per node, laid out on the schema's declared spine.

    995,727 rows at 1M, one sort, no force iteration. Every node gets a **stable home
    position**, so a person who is handed an ``entity_id`` by a query can be told where it sits in
    the estate without the estate being drawn.

    The scope is **not truncated by default and must not be**: this is the frame every local view
    is a window onto, so a truncated estate frame would leave most of the estate unplaceable. The
    budget therefore applies to *rendering*, and the check that the estate frame exceeds it is the
    honest statement that the estate has no picture -- see the module docstring.
    """
    spine = sub.spine()
    sectors = type_sector_order(spine)
    sector_of = {t: i for i, t in enumerate(sectors)}
    ring_of = _ring_of_type(spine)
    max_ring = max(ring_of.values()) if ring_of else 0

    rows = sub.con.execute(
        f"SELECT entity_id, entity_type FROM {sub.node_glob()} ORDER BY entity_id").fetchall()
    available = len(rows)
    sector_span = 360.0 / max(1, len(sectors))

    placed: list[tuple[str, str, float, float, int, int, float, str | None]] = []
    per_type: dict[str, int] = {}
    per_type_total: dict[str, int] = {}
    for etype, n in sub.type_table():
        per_type_total[etype] = n
    for entity_id, etype in rows:
        idx = per_type.get(etype, 0)
        per_type[etype] = idx + 1
        sector = sector_of.get(etype, len(sectors) - 1)
        #: Equal sweep per TYPE, so a type with one row and a type with 212,000 rows occupy the
        #: same angle and the density of the arc IS the type's size. A layout that gave each type
        #: a sweep proportional to its size would hide the very fact the picture is for.
        frac = 0.0 if per_type_total.get(etype, 0) <= 1 else idx / (per_type_total[etype] - 1)
        angle = (sector + frac * 0.92) * sector_span
        x, y = _polar(ring_of.get(etype, 0), angle)
        parent_type = next((r.get("parent") for r in spine if r["type_name"] == etype), None)
        placed.append((entity_id, etype, x, y, ring_of.get(etype, 0), sector,
                       round(angle % 360.0, 4), parent_type))

    return {
        "envelope": _envelope(sub, scope, "estate", "spine_radial", None, 0, None,
                              budget, available, len(placed), False,
                              {"sectors": len(sectors), "max_ring": max_ring,
                               "sector_span_deg": round(sector_span, 4)}),
        "positions": placed,
    }


def neighbourhood_layout(sub: Substrate, seed: str, depth: int = 2, *,
                         direction: str = "out", budget: int = RENDER_BUDGET) -> dict[str, Any]:
    """The local frame: one depth-capped traversal, laid out on its OWN depths.

    Two rules are load-bearing and both are about not keeping a second traversal:

    * the rings are ``traverse.py``'s ``depth_reached``, read from the pinned template's own
      output, so there is no breadth-first search in this module to disagree with it;
    * the parent link is a **declared tie-break** -- among the edges into a node from the ring
      below, the first by ``(relationship_type, entity_id)`` -- computed with one join per ring
      against the substrate, not by a search.
    """
    if direction not in ("out", "in"):
        raise LayoutRefused("layout_algorithm_not_in_the_closed_vocabulary",
                            f"direction {direction!r} is not 'out' or 'in'; the pinned template "
                            f"is an OUT traversal and this module does not invent an IN one by "
                            f"rewriting its text.")
    if direction == "in":
        raise LayoutRefused("layout_algorithm_not_in_the_closed_vocabulary",
                            "The pinned template is an OUT traversal. The in-neighbourhood is the "
                            "to-clustered edge relation queried directly, which is what "
                            "traverse.py's own docstring measures at 6.3 ms -- and it is not a "
                            "second template, it is the same edge relation read the other way. A "
                            "layout for it would need the same treatment, so this module refuses "
                            "rather than shipping an in-template that is not the pinned one.")
    reached = sub.neighbourhood(seed, depth)
    available = len(reached)
    order = {eid: d for eid, d in reached}

    sectors = type_sector_order(sub.spine())
    sector_of = {t: i for i, t in enumerate(sectors)}
    span = 360.0 / max(1, len(sectors))
    types = _types_of(sub, list(order))

    parents = _ring_parents(sub, order)
    placed: list[tuple[str, str, float, float, int, int, float, str | None]] = []
    per_ring: dict[int, list[str]] = {}
    for eid, d in order.items():
        per_ring.setdefault(d, []).append(eid)
    angle_of: dict[str, float] = {}
    for d, members in per_ring.items():
        members.sort()
        for i, eid in enumerate(members):
            frac = 0.0 if len(members) <= 1 else i / (len(members) - 1)
            sector = sector_of.get(types.get(eid, ""), len(sectors) - 1)
            angle_of[eid] = (sector + frac * 0.92) * span
    for eid in sorted(order, key=lambda e: (order[e], angle_of.get(e, 0.0), e)):
        d = order[eid]
        etype = types.get(eid, "")
        sector = sector_of.get(etype, len(sectors) - 1)
        angle = angle_of.get(eid, 0.0)
        x, y = _polar(d, angle)
        placed.append((eid, etype, x, y, d, sector, round(angle % 360.0, 4), parents.get(eid)))

    kept = placed[:budget]
    scope = f"neighbourhood:{seed}@d{depth}"
    return {
        "envelope": _envelope(sub, scope, "neighbourhood", "neighbourhood_radial", seed, depth,
                              "out", budget, available, len(kept), available > budget,
                              {"rings": len(per_ring)}),
        "positions": kept,
        "all_positions": placed,
    }


def _types_of(sub: Substrate, ids: Sequence[str]) -> dict[str, str]:
    """``entity_id -> entity_type`` for a bounded id list, by the four-column lead block.

    The lead block is the only cross-type projection (see ``substrate``'s docstring), and this is
    exactly the query it exists for. A list parameter, so the cost is O(ids) and not O(estate).
    """
    if not ids:
        return {}
    con = sub.con
    out: dict[str, str] = {}
    for i in range(0, len(ids), 20000):
        chunk = ids[i:i + 20000]
        marks = ",".join("?" for _ in chunk)
        rows = con.execute(
            f"SELECT entity_id, entity_type FROM {sub.node_glob()} "
            f"WHERE entity_id IN ({marks})", list(chunk)).fetchall()
        out.update(dict(rows))
    return out


def _ring_parents(sub: Substrate, order: dict[str, int]) -> dict[str, str | None]:
    """Each node's parent: the declared tie-break, and never a traversal.

    For every node at ring ``k > 0``, among the edges **into** it whose source is at ring ``k-1``,
    the first by ``(relationship_type, entity_id)``. One query per ring, against the to-clustered
    edge relation, so the cost is O(nodes in the view) and the source set is *given* by the
    traversal's own depths rather than searched for.
    """
    con = sub.con
    parents: dict[str, str | None] = {}
    rings = sorted({d for d in order.values() if d > 0})
    at_k_by_ring: dict[int, list[str]] = {}
    for eid, d in order.items():
        at_k_by_ring.setdefault(d, []).append(eid)
    for k in rings:
        at_k = sorted(at_k_by_ring.get(k, []))
        #: The ring BELOW is ring k-1's own membership, read out of the same table. The first
        #: draft built a second dict called ``below_by_ring`` and added each node to bucket
        #: ``d - 1``, which is bucket d's members -- so "the ring below" held the ring above, no
        #: parent ever matched, and 7 of 480 nodes were placed with a parent. It rendered, and
        #: every parent link in it was wrong or absent, which is the shape of a defect no count
        #: would have found.
        below = set(at_k_by_ring.get(k - 1, ()))
        if not at_k or not below:
            continue
        marks = ",".join("?" for _ in at_k)
        rows = con.execute(
            f"SELECT e.to_entity_id, e.from_entity_id FROM {sub.edges_by_dst()} e "
            f"WHERE e.to_entity_id IN ({marks}) ORDER BY e.to_entity_id, "
            f"e.relationship_type, e.from_entity_id", at_k).fetchall()
        best: dict[str, str] = {}
        for child, parent in rows:
            if child in best or parent not in below:
                continue
            best[child] = parent
        parents.update(best)
    for eid, d in order.items():
        parents.setdefault(eid, None)
    return parents


# ------------------------------------------------------------------------------- the envelope

def _envelope(sub: Substrate, scope: str, kind: str, algorithm: str, seed: str | None,
              depth: int, direction: str | None, budget: int, available: int, placed: int,
              truncated: bool, extra: dict[str, Any]) -> dict[str, Any]:
    if algorithm not in LAYOUT_ALGORITHMS:
        raise LayoutRefused("layout_algorithm_not_in_the_closed_vocabulary",
                            f"{algorithm!r} is not one of {sorted(LAYOUT_ALGORITHMS)}")
    env = {
        "layout_scope": scope,
        "layout_scope_kind": kind,
        "layout_algorithm": algorithm,
        "layout_version": LAYOUT_VERSION,
        "seed_entity_id": seed,
        "depth_requested": depth,
        "depth_cap": None,
        "direction": direction,
        "row_budget": budget,
        "rows_available": available,
        "rows_placed": placed,
        "truncated": bool(truncated),
        "truncation_rule": _TRUNCATION_RULE,
        "estate_state": sub.estate_state,
        "valid_time_window": sub.valid_time_window,
        "coordinate_valid": sub.coordinate["valid"],
        "coordinate_system": sub.coordinate["system"],
        "corpus_fingerprint": sub.corpus_fingerprint,
        "substrate_version": sub.manifest.get("substrate_version", "unknown"),
    }
    env.update(extra)
    env["digest"] = digest_of(env)
    return env


def digest_of(envelope: dict[str, Any]) -> str:
    """The envelope's own digest, over the envelope with the digest field removed.

    Twelve hex characters, matching the shape of a D20 id's hash12, and computed the same way --
    a fold of one canonical text. **A layout is reproducible or it is a picture**, so the digest is
    not decoration: ``check_viewer``'s C7 recomputes a scope twice and compares.
    """
    body = {k: v for k, v in envelope.items() if k != "digest"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------------------- the relation on disk

def write_layout(out_dir: str, scope: str, envelope: dict[str, Any],
                 positions: Iterable[Sequence[Any]]) -> dict[str, str]:
    """Write one scope: ``<scope>/envelope.json`` and ``<scope>/positions.parquet``.

    **Not under ``nodes/`` and not into the manifest's ``substrate.files``**, which is the shipped
    check's whole point. The layout is a *derived view* artefact beside the substrate, and
    ``check_viewer``'s C1 fails if a layout file appears inside the substrate directory.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    scope_dir = os.path.join(out_dir, "layout", _safe(scope))
    os.makedirs(scope_dir, exist_ok=True)
    env_path = os.path.join(scope_dir, "envelope.json")
    with open(env_path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, ensure_ascii=False, sort_keys=True)
    pos_path = os.path.join(scope_dir, "positions.parquet")
    rows = list(positions)
    table = pa.table({c: [r[i] for r in rows] for i, c in enumerate(POSITION_COLUMNS)})
    pq.write_table(table, pos_path, compression="zstd")
    return {"envelope": env_path, "positions": pos_path,
            "scope_dir": scope_dir, "rows": str(len(rows))}


def read_layout(scope_dir: str) -> tuple[dict[str, Any], list[tuple]]:
    import pyarrow.parquet as pq
    with open(os.path.join(scope_dir, "envelope.json"), encoding="utf-8") as fh:
        env = json.load(fh)
    table = pq.read_table(os.path.join(scope_dir, "positions.parquet"))
    return env, [tuple(r[c] for c in POSITION_COLUMNS) for r in
                 table.to_pylist()]


def layout_scopes(out_dir: str) -> list[str]:
    root = os.path.join(out_dir, "layout")
    if not os.path.isdir(root):
        return []
    return sorted(os.listdir(root))


def _safe(scope: str) -> str:
    """A directory name for a scope id. A D20 id has no path separator and neither does this."""
    return "".join(c if (c.isalnum() or c in "-_.@:~") else "_" for c in scope)


def check_no_layout_on_nodes(sub: Substrate) -> list[str]:
    """Independently: does any node file carry a layout column? Read from the files themselves.

    This is ``sync.layout_is_not_a_node_attribute`` re-derived by the module that has to obey it,
    and it reads each file's own schema rather than the glob's -- because the glob's schema is the
    first file's, which is the whole trap.
    """
    import glob as _glob
    from check_sync import LAYOUT_ATTRIBUTE_NAMES  # noqa: PLC0415 -- the shipped constant

    hits: list[str] = []
    for path in sorted(_glob.glob(os.path.join(sub.graph_dir, "nodes", "*.parquet"))):
        cols = {r[0] for r in sub.con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
        found = sorted(cols & LAYOUT_ATTRIBUTE_NAMES)
        if found:
            hits.append(f"{os.path.basename(path)}: {found}")
    return hits
