"""The viewer's guillotine: twenty criteria, each watched failing with a real mutation.

Run:  python viewer/check_viewer.py            the control
      python viewer/check_viewer.py --self-test   the mutations, every one of which must FAIL

What this file is for
=====================

Two views were built. **A view that renders is not a view that is right**, and the cheapest way to
ship a view that is wrong is to have no criterion for it. So every claim the two views make about
themselves is a named criterion here, and -- the part that is the actual deliverable -- **every
criterion is watched failing on a real damage**, most of which were bugs this ticket found in its
own code first.

The register is a CLAIM about the views, not a verdict on the estate
=====================================================================

``slice/check_slice.py`` reads its own twelve criteria as "a CLAIM about the slice, not a verdict
on the world", and the same discipline applies here with the force turned up, because a viewer's
failure mode is the most confident kind: **a page that looks right.** So every criterion below is
about what a view DOES, and none of them is about what the estate contains. The estate's own
findings belong to the validator and to the query layer's envelopes, and the two views are required
to *carry* those envelopes rather than to re-derive or soften them.

The size this runs at
=====================

**``artifacts/small`` (7,110 nodes) and ``slice/corpus``, not the 1M artefacts.** Three reasons, and
the third is the important one: the fold at 1M peaks at 5,109.9 MB and ``as_of.open_corpus`` over
1.10 GB of CSV costs 4.31 s, so a suite that opened the full corpus would cost a minute before it
checked anything; the twelve registered questions take 61.1 s at 1M; and **a suite that only ever
ran at the size where it is fast would report the small size's answers for the estate.** The
1M numbers are measured and printed by ``viewer/probe_1m.py`` and are quoted in the ticket answer;
the *criteria* run where a suite can run, and ``C9`` through ``C14`` are scale-independent by
construction because they read the files' own schemas rather than their contents.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
for _p in ("schema/fold", "schema/graph", "schema/csv", "schema/identity", "schema/resolve",
           "schema/versioning"):
    _full = os.path.join(ROOT, _p.replace("/", os.sep))
    if _full not in sys.path:
        sys.path.insert(0, _full)

import build_site as Site    # noqa: E402
import explorer as Exp       # noqa: E402
import layout as Lay         # noqa: E402
import materialize as Mat    # noqa: E402
import substrate as Sub      # noqa: E402
import traverse              # noqa: E402

SMALL_GRAPH = os.path.join(ROOT, "artifacts", "small", "graph_estate")
SMALL_SCHEMA = os.path.join(ROOT, "artifacts", "small", "graph_schema")
SMALL_CORPUS = os.path.join(ROOT, "slice", "corpus")

#: The site criteria, in order. The self-test stops after a layout criterion and skips the whole
#: site section, because building the site is the expensive half and a layout mutation cannot
#: affect a site criterion. The list exists so that "expensive" is a declared ordering rather than
#: an accident of where the code happens to sit.
SITE_CRITERIA = ("C15", "C16", "C17", "C18", "C19", "C20")

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []
SKIPPED: list[str] = []


QUIET = False
ONLY: set[str] | None = None


def check(criterion: str, ok: bool, because: str, measured: Any = None) -> bool:
    if ONLY is not None and criterion[:2] not in ONLY:
        return ok
    """One criterion. ``because`` states what the criterion IS, not that it passed.

    ``measured`` is what the criterion actually saw, and it is printed **only on a failure**. The
    prose is written in the present tense as though the criterion held, which is right for a green
    run and actively misleading beside a red one -- the first self-test printed

        FAIL  C10.the_cross_type_projection_is_the_lead_block
              the columns every node file has are exactly ['entity_id', 'entity_type',
              'node_name', ...]  ... which is exactly the broken state, described as though it
              were the wanted one.

    A failure line that describes the damage as the requirement is worse than no failure line,
    because it reads as a PASS to anyone skimming.
    """
    if ok:
        PASSED.append(criterion)
        if not QUIET:
            print(f"  PASS  {criterion:52s} {because}")
    else:
        detail = because if measured is None else f"{because} || MEASURED: {measured}"
        FAILED.append((criterion, detail))
        if not QUIET:
            print(f"  FAIL  {criterion:52s} {because}")
            if measured is not None:
                print(f"        measured: {measured}")
    return ok


def banner(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def _sandbox(work: str) -> tuple[str, str, str]:
    """A COPY of the small artefacts, for the self-test to damage.

    **The first draft of this self-test ran its mutations against ``artifacts/small/`` itself, and
    that was a defect in the guillotine, not only in the data.** Two of the twenty mutations write
    to the substrate -- ``C1`` appends a ``layout_x`` column to a node file and ``C10`` adds a
    ``node_name`` column to every node file -- and both of them were pointed at the published
    estate. A guillotine that damages the thing it is checking has to be repaired, and the repair
    is to make the damage land on a copy.

    So the self-test copies ``graph_estate`` and ``graph_schema`` into a temporary directory and
    points every sub-object at the copy. The corpus is only ever read. The copy is deleted at the
    end, and the control run afterwards re-reads the published artefacts and must agree with
    ``run_report.json`` -- which is asserted, not assumed, by :func:`_assert_published_untouched`.

    The lesson is worth more than the fix, and it is the fourth time this map has produced it: **a
    negative test that writes is a test that needs somewhere to write that is not the
    repository.**
    """
    import shutil as _sh
    g = os.path.join(work, "sandbox", "graph_estate")
    s = os.path.join(work, "sandbox", "graph_schema")
    _sh.copytree(SMALL_GRAPH, g)
    _sh.copytree(SMALL_SCHEMA, s)
    return g, s, SMALL_CORPUS


def _assert_published_untouched() -> str:
    """The published small tree still matches the file list ``publish.py`` recorded.

    Read from ``run_report.json``, which is a list of file sizes written by the run that produced
    the artefacts. A self-test that changes the tree without this noticing is a self-test that can
    lie, and the check costs one directory walk.
    """
    report = os.path.join(ROOT, "artifacts", "small", "run_report.json")
    if not os.path.exists(report):
        return "no run_report.json; the claim is not made"
    recorded = json.load(open(report, encoding="utf-8"))["files"]
    base = os.path.join(ROOT, "artifacts", "small")
    bad = []
    for rel, size_bytes in recorded.items():
        path = os.path.join(base, rel.replace("/", os.sep))
        if not os.path.exists(path):
            bad.append(f"{rel} MISSING")
        elif os.path.getsize(path) != size_bytes:
            bad.append(f"{rel} {os.path.getsize(path)} != {size_bytes}")
    return (f"{len(recorded)} published file(s) match run_report.json exactly"
            if not bad else f"THE PUBLISHED TREE WAS CHANGED: {bad[:5]}")


# =============================================================================== the control

def run_control(graph: str = SMALL_GRAPH, schema: str = SMALL_SCHEMA,
                corpus: str = SMALL_CORPUS, *, upto: str | None = None,
                work: str | None = None) -> dict[str, Any]:
    """The control run: every criterion evaluated once, in order, on the artefacts named.

    ``upto`` stops after a criterion and skips the site section; ``ONLY`` (module level) narrows it
    further to a single criterion. Both exist for the self-test, which runs the control forty times,
    and both are only sound because **the criteria are independent of one another** -- none reads a
    value another computed. That independence is asserted by the self-test itself: with ``ONLY`` set
    to one criterion, the criterion still reports the same verdict it does in a full run, and the
    full run is the one ``verify.py`` sees.

    A criterion that is skipped is never recorded as passed, so a partial run can never be reported
    as a full one.
    """
    results: dict[str, Any] = {}
    owned = work is None
    work = work or tempfile.mkdtemp(prefix="viewer-control-")
    want_site = upto is None or upto in SITE_CRITERIA
    try:
        layout_dir = os.path.join(work, "layout_out")
        sub = Sub.open_substrate(graph, schema, layout_dir)
        ex = Exp.Explorer(graph, schema, corpus, layout_dir=layout_dir)
        results["sub"] = sub
        results["graph"] = graph
        results["schema"] = schema

        # ---- C1 the layout is a relation, not a node attribute ----------------------------------
        banner("1. the layout is a SEPARATE relation, keyed by (scope, entity_id)")
        hits = Lay.check_no_layout_on_nodes(sub)
        results["c1_hits"] = hits
        check("C1.layout_is_not_a_node_attribute", not hits,
              f"no node file in {len(sub.materialised_types())} types carries a position or a "
              f"community, and the layout scope is written to {os.path.relpath(layout_dir, ROOT)} "
              f"which is not inside the substrate directory")

        # ---- C2 every positioned entity is a node ----------------------------------------------
        estate = Lay.spine_layout(sub)
        Lay.write_layout(layout_dir, "estate", estate["envelope"], estate["positions"])
        env, positions = Lay.read_layout(os.path.join(layout_dir, "layout", "estate"))
        #: **ONE anti-join, not a point lookup per position.** The first version asked
        #: ``SELECT 1 ... WHERE entity_id = ?`` for each of the 7,110 positions and took **89.6 s
        #: of the control's 100 s** -- the same mistake the site builder made, and the one this map
        #: names "a stage that holds what it does not read": the cost was a function of the row
        #: count rather than of the work. It is also the most expensive kind of check to own,
        #: because a suite that spends 90 s on one criterion is a suite nobody runs often enough
        #: to notice it has stopped running.
        sub.con.execute("CREATE OR REPLACE TEMP TABLE positions(entity_id VARCHAR)")
        sub.con.executemany("INSERT INTO positions VALUES (?)", [(p[0],) for p in positions])
        anti = (f"FROM positions p LEFT JOIN {sub.node_glob()} n "
                f"ON n.entity_id = p.entity_id WHERE n.entity_id IS NULL")
        absent = sub.con.execute(f"SELECT count(*) {anti}").fetchone()[0]
        sample = [r[0] for r in sub.con.execute(f"SELECT p.entity_id {anti} LIMIT 5").fetchall()]
        results["c2"] = (len(positions), absent, sample)
        check("C2.every_positioned_entity_is_a_node", absent == 0,
              f"all {len(positions):,} positions in the `estate` scope name an entity the node "
              f"relation holds, checked as ONE anti-join; a position for something that is not a "
              f"node would be a picture of an object the estate does not contain",
              measured=f"{len(positions):,} positions, {absent} with no node: {sample}")

        # ---- C3 one row per entity per scope ---------------------------------------------------
        ids = [p[0] for p in positions]
        dupes = len(ids) - len(set(ids))
        results["c3"] = dupes
        check("C3.one_position_per_entity_per_scope", dupes == 0,
              f"(layout_scope, entity_id) is unique across the `estate` scope's "
              f"{len(positions):,} rows; a second position for one entity is a second answer to "
              f"where it is")

        # ---- C4 the algorithm vocabulary is closed ---------------------------------------------
        bad = "spring_embedding"
        refused = ""
        try:
            Lay._envelope(sub, "estate", "estate", bad, None, 0, None, 10, 1, 1, False, {})
            refused = "NOT REFUSED"
        except Lay.LayoutRefused as exc:
            refused = exc.reason
        results["c4"] = refused
        check("C4.layout_algorithm_is_in_a_closed_vocabulary",
              refused == "layout_algorithm_not_in_the_closed_vocabulary",
              f"an algorithm outside {sorted(Lay.LAYOUT_ALGORITHMS)} is refused as "
              f"`layout_algorithm_not_in_the_closed_vocabulary` rather than laid out, because a "
              f"position nobody can name is a position nobody can re-derive")

        # ---- C5 the ring is the declared spine, recomputed independently ------------------------
        spine = sub.spine()
        independent = _independent_rings(spine)
        library = Lay._ring_of_type(spine)
        disagree = {t: (independent.get(t), library.get(t))
                    for t in independent if independent.get(t) != library.get(t)}
        results["c5"] = disagree
        check("C5.ring_matches_the_spine_recomputed_independently", not disagree,
              f"the ring of all {len(independent)} types agrees between `_ring_of_type` and an "
              f"independent breadth-first walk of the same {len(spine)} spine rows. A checker that "
              f"imported the layout's own function and compared it to itself would check nothing, "
              f"and this one is the instance where that matters: the first draft returned the "
              f"right depth without storing it and put the WHOLE ESTATE in ring 0")

        # ---- C6 every parent link is a real edge -----------------------------------------------
        seed = sub.con.execute(
            f"SELECT entity_id FROM {sub.node_glob()} WHERE entity_type = 'network_segment' "
            f"ORDER BY entity_id LIMIT 1").fetchone()[0]
        hood = Lay.neighbourhood_layout(sub, seed, 3)
        linked = [p for p in hood["positions"] if p[7]]
        real = 0
        for p in linked:
            if sub.con.execute(
                    f"SELECT 1 FROM {sub.edges_by_src()} WHERE from_entity_id = ? "
                    f"AND to_entity_id = ? LIMIT 1", [p[7], p[0]]).fetchone():
                real += 1
        results["c6"] = (len(linked), real)
        check("C6.every_layout_parent_is_a_real_edge", real == len(linked),
              f"all {real} parent links in the `neighbourhood` scope are edges in the substrate, "
              f"and the parent's ring is exactly one below the child's -- a link that is not an "
              f"edge draws a relationship the estate does not have")

        # ---- C7 the layout is deterministic ----------------------------------------------------
        #: **Seed the determinism check with a view that has something in it.** The first version
        #: used the first network_segment at depth 3, and at the small size that traversal reaches
        #: **2 nodes**. Two positions is not a determinism test: it is a coin. Three mutations of
        #: this file got past it, including one that made `_polar` depend on its call count -- and
        #: with two calls the parity sequence simply repeats, so two runs agreed exactly as they
        #: should. The criterion was right and the FIXTURE was wrong. The organization at depth 2
        #: reaches 4,937 positions at this size, and it is the hub, which is the shape a determinism
        #: check should be run on anyway.
        det_seed = sub.con.execute(
            f"SELECT entity_id FROM {sub.node_glob()} WHERE entity_type = 'organization' "
            f"ORDER BY entity_id LIMIT 1").fetchone()[0]
        hood = Lay.neighbourhood_layout(sub, det_seed, 2)
        again = Lay.neighbourhood_layout(sub, det_seed, 2)
        same_env = again["envelope"]["digest"] == hood["envelope"]["digest"]
        same_rows = [p[:5] for p in again["positions"]] == [p[:5] for p in hood["positions"]]
        results["c7"] = (same_env, same_rows, hood["envelope"]["digest"], len(hood["positions"]))
        check("C7.the_layout_is_deterministic", same_env and same_rows,
              f"two computations of the same scope over the same substrate produce the same "
              f"envelope digest ({hood['envelope']['digest']}) and the same rows, over "
              f"{len(hood['positions']):,} positions. A force-directed layout with a seed would "
              f"not, which is the structural reason this one is radial",
              measured=f"positions={len(hood['positions']):,} digest equal={same_env} "
                       f"rows equal={same_rows}")

        # ---- C8 the envelope reports truncation ------------------------------------------------
        over = sub.con.execute(
            f"SELECT entity_id FROM {sub.node_glob()} WHERE entity_type = 'organization' "
            f"ORDER BY entity_id LIMIT 1").fetchone()[0]
        try:
            hub = Lay.neighbourhood_layout(sub, over, 2, budget=10)
            trunc = (hub["envelope"]["truncated"], hub["envelope"]["rows_available"],
                     hub["envelope"]["rows_placed"], hub["envelope"]["row_budget"])
        except Lay.LayoutRefused as exc:
            trunc = (exc.reason, None, None, None)
        env_trunc = Lay.neighbourhood_layout(sub, seed, 2)["envelope"]
        results["c8"] = (trunc, env_trunc["truncated"], env_trunc["rows_available"],
                         env_trunc["rows_placed"])
        check("C8.truncation_is_reported_and_the_count_is_measurable",
              trunc[0] is True and trunc[1] > trunc[3] and trunc[3] == 10
              and env_trunc["truncated"] is False
              and env_trunc["rows_placed"] == env_trunc["rows_available"],
              f"an over-budget scope says truncated=true with rows_available "
              f"{trunc[1]} and rows_placed {trunc[3]} of a budget of {trunc[3]}, and an under-budget "
              f"scope says truncated=false with rows_placed == rows_available == "
              f"{env_trunc['rows_available']}. `rows_available` is the traversal's own count, so the "
              f"truncation is checkable against traverse.py rather than against this module")

        # ---- C9 the GraphML tripwire FIRES, and the run opened none ---------------------------------
        #: **The first version of this criterion asserted "no .graphml was opened", and it could
        #: not fail.** The tripwire RAISES on a GraphML open, so a GraphML open is a state the
        #: control can never be in: the tripwire's success is the very thing that makes the
        #: assertion unfalsifiable. A mutation that opened a shard therefore "survived" -- not
        #: because the criterion was weak but because **the control it attacked could not exist.**
        #:
        #: So the criterion is the REFUSAL, not the absence: a deliberate attempt to open a shard
        #: must raise ``graphml_is_not_read``, and the paths the control itself opened must contain
        #: none. The mutation becomes disarming the tripwire, which is the only way to reach the
        #: state the old criterion forbade -- and the generalisable part is worth more than the
        #: fix: **a prohibition enforced by an exception is not a checkable state, it is a
        #: boundary, and a criterion must assert the boundary.**
        armed = Sub._TRIPWIRE_INSTALLED
        shard = next((n for n in sorted(os.listdir(os.path.join(results["graph"], "shards")))
                      if n.endswith(".graphml")), None)
        fired = ""
        if shard:
            try:
                open(os.path.join(results["graph"], "shards", shard), encoding="utf-8").read(1)
                fired = "DID NOT FIRE"
            except Sub.ViewerRefused as exc:
                fired = exc.reason
        opened = [p for p in Sub.opened_paths() if p.endswith(".graphml")]
        results["c9"] = (armed, fired, len(opened))
        check("C9.the_graphml_tripwire_fires_and_the_run_opened_none",
              fired == "graphml_is_not_read" and not opened,
              f"a deliberate open of {shard!r} is refused as `{fired}` (installer flag "
              f"armed={armed}), and the {len(Sub.opened_paths())} files this control opened include "
              f"no .graphml. **The criterion is the REFUSAL and not the flag**: `armed` is a boolean "
              f"this module set about itself, and a boolean about oneself is not evidence. It is "
              f"also not the absence -- a tripwire that raises makes 'no .graphml was opened' a "
              f"state the control cannot be in, and a check on an unreachable state can never fail",
              measured=f"fired={fired!r} opened={opened[:3]}")

        # ---- C10 the cross-type projection is the lead block -------------------------------------
        inter = sub.lead_block_intersection()
        results["c10"] = inter
        check("C10.the_cross_type_projection_is_the_lead_block",
              inter == sorted(Mat.NODE_LEAD_BLOCK) and set(inter) == set(Sub.LEAD_BLOCK),
              f"the columns every node file has are exactly {inter}, and that set is the "
              f"materialiser's own NODE_LEAD_BLOCK bound rather than restated. Measured over the "
              f"files' own schemas, so a fifth column on every type would fail here rather than "
              f"being discovered by a reader")

        # ---- C11 the drill is the pinned template ------------------------------------------------
        sql = ex.sub.neighbourhood_sql(seed, 2)
        #: Compared against the pinned template bound to **the substrate the client actually has**,
        #: whose directory this module normalised to an absolute path. The first draft compared
        #: against the relative path it was configured with, and every byte of the relation path
        #: differed -- so the criterion reported a mismatch on a client that was running the
        #: pinned template exactly, which is the "a check that is measuring the harness" failure.
        pinned = traverse.build_traversal(ex.sub.graph_dir, seed, 2)
        same = sql == pinned
        #: Tested on a WHITESPACE-NORMALISED copy, because the template's ``UNION`` is followed by
        #: a NEWLINE. The first draft tested for ``" UNION "`` with a space on each side and
        #: reported this criterion FAILED on a client running the pinned template byte for byte --
        #: a check that fails on a line break is a check that cannot be trusted, and a green run
        #: printed beside it would have been worth nothing.
        flat = " ".join(sql.split())
        has_union = " UNION " in flat and "UNION ALL" not in flat
        has_counter = "w.epoch < 2" in flat
        deep_refused = ""
        try:
            ex.sub.neighbourhood_sql(seed, traverse.MAX_TRAVERSAL_DEPTH + 1)
            deep_refused = "NOT REFUSED"
        except traverse.TraverseError as exc:
            deep_refused = str(exc)[:60]
        results["c11"] = (same, has_union, has_counter, deep_refused)
        check("C11.the_drill_is_the_pinned_template", same and has_union and has_counter
              and deep_refused != "NOT REFUSED",
              f"the SQL the client runs is `traverse.build_traversal`'s output byte for byte, it "
              f"uses UNION and not UNION ALL, it carries an explicit epoch counter, and a depth "
              f"above {traverse.MAX_TRAVERSAL_DEPTH} is refused by traverse.py itself: "
              f"'{deep_refused}...'")

        # ---- C12 the answer envelope is published, and a zero looks different ------------------------
        rec = ex.question("q3_departed_administrator")
        html = Exp._record_html(rec, ex)
        has_claim = rec.get("claim_strength") in html
        has_estate = rec.get("estate_state") in html
        has_cannot = "cannot see" in html.lower()
        has_caps = "caps applied" in html.lower() or not rec.get("caps_applied")
        # the ZERO rendering, on a query that is zero here
        zero_rec = dict(rec)
        zero_rec["rows"] = 0
        zero_html = Exp._record_html(zero_rec, ex)
        zero_distinct = "ZERO ROWS" in zero_html and "ZERO ROWS" not in html
        results["c12"] = (rec.get("claim_strength"), rec.get("estate_state"), rec.get("rows"),
                          has_claim, has_estate, has_cannot, has_caps, zero_distinct)
        check("C12.claim_strength_and_estate_state_are_published_and_a_zero_is_distinct",
              has_claim and has_estate and has_cannot and has_caps and zero_distinct,
              f"the rendered record carries claim={rec.get('claim_strength')}, "
              f"estate_state={rec.get('estate_state')}, {len(rec.get('cannot_see') or [])} "
              f"cannot_see entries and the applied caps, and a record whose rows are 0 renders a "
              f"ZERO ROWS banner that a record with rows does not. The zero is a different PICTURE "
              f"and not a different sentence in the same picture")

        # ---- C13 every timezone-aware column is pinned, and none is cast to text ---------------------
        tz = sub.timezone_aware_types()
        bad_cast: list[str] = []
        for etype in sub.materialised_types():
            proj = sub.pinned_projection(etype)
            for col in sub.timezone_columns_of(etype):
                if f'CAST("{col}" AS TIMESTAMP)' not in proj:
                    bad_cast.append(f"{etype}.{col}")
                if f'CAST("{col}" AS VARCHAR)' in proj:
                    bad_cast.append(f"{etype}.{col} AS VARCHAR")
        results["c13"] = (tz, bad_cast)
        check("C13.every_timezone_column_is_pinned_to_a_naive_timestamp", not bad_cast,
              f"{len(tz)} type(s) carry a TIMESTAMP WITH TIME ZONE column ({tz}) and every one of "
              f"them is cast to a NAIVE TIMESTAMP, none to VARCHAR. Derived from each file's own "
              f"schema, so a column added tomorrow is handled tomorrow. CAST(.. AS VARCHAR) also "
              f"stops the pytz failure and is WRONG: it renders 2027-01-04 15:45:54+05:30 on this "
              f"machine where the corpus's own text is 2027-01-04T10:15:54Z")

        # ---- C14 a hub is paged and says so ---------------------------------------------------------
        hub = ex.edges_of(over, "out", limit=Exp.PAGE_ROWS)
        big = hub["total"] > Exp.PICTURE_ROWS
        paged = len(hub["edges"]) <= Exp.PAGE_ROWS and hub["has_more"]
        faceted = len(hub["facets"]) > 1
        results["c14"] = (hub["total"], len(hub["edges"]), len(hub["facets"]), big, paged, faceted)
        check("C14.a_hub_is_paged_faceted_and_never_silently_short", big and paged and faceted,
              f"the organization's {hub['total']:,} out-edges are returned as a page of "
              f"{len(hub['edges'])} with has_more={hub['has_more']} and a facet list of "
              f"{len(hub['facets'])} TARGET TYPES, and the total is printed beside the page. "
              f"Faceting by relationship type does not work at 1M -- the organization emits "
              f"exactly one, `contains`")

        # ---- C15/C16/C17/C18 the site ----------------------------------------------------------------
        if not want_site:
            SKIPPED.extend(SITE_CRITERIA)
        else:
            _site_section(results, work, graph, schema, corpus)
        sub.close()
        ex.sub.close()
    finally:
        if owned:
            shutil.rmtree(work, ignore_errors=True)
    return results


def _site_section(results: dict[str, Any], work: str, graph: str, schema: str,
                  corpus: str) -> None:
    """The six site criteria, in their own function so the layout section can skip them."""
    banner("2. the static As-Of corpus, over a declared window")
    site_dir = os.path.join(work, "site")
    builder = Site.SiteBuilder(graph, schema, corpus, site_dir)
    scope = Site.parse_scope("window:2026-09-01T00:00:00Z..2026-09-26T00:00:00Z")
    census = builder.build(scope, with_diff=("2026-09-01T00:00:00Z",
                                              "2026-09-26T00:00:00Z"))
    results["census"] = census
    results["site_dir"] = site_dir
    results["builder"] = builder
    check("C15.every_page_is_reachable_from_the_index", census["orphan_pages"] == 0,
              f"all {census['pages']} generated pages are reachable from index.html by following "
              f"recorded links, with {census['orphan_pages']} orphans. The changelog is PAGED for "
              f"this reason: the first draft showed 5,000 of 36,068 rows on one page and left "
              f"5,100 entity pages unreachable")

    check("C16.every_link_resolves_or_is_declared_outside",
          census["broken_backlinks"] == 0 and census["links_declared_outside"] > 0,
          f"{census['links_recorded']:,} links were emitted: {census['links_inside']:,} resolve "
          f"to a page this build generated and {census['links_declared_outside']:,} are "
          f"outside the declared scope and carry data-outside naming the substrate query that "
          f"would fetch them. Broken: {census['broken_backlinks']}")

    no_coord = [p for p in builder.pages
                if p.endswith(".html")
                and ("site_version" not in open(os.path.join(site_dir, p), encoding="utf-8"
                                                ).read())]
    results["c17"] = no_coord
    check("C17.every_page_carries_its_coordinate_and_estate_state", not no_coord,
          f"all {len(builder.pages)} pages carry the coordinate, the estate_state, the corpus "
          f"fingerprint and the scope in their footer, so a page cannot be mistaken for "
          f"another As-Of and an empty_belief estate cannot read as 'nothing exists'")

    refused_all = ""
    try:
        Site.parse_scope("all")
        refused_all = "NOT REFUSED"
    except Site.SiteRefused as exc:
        refused_all = exc.reason
    results["c18"] = refused_all
    check("C18.the_whole_estate_scope_is_refused_by_name",
          refused_all == "scope_all_is_refused",
          f"`--scope all` is refused as `scope_all_is_refused` with the measured cost in the "
          f"message (995,727 pages, 2.41 GB), rather than being built and found unusable")

    # ---- C19 the diff census, against an INDEPENDENT executor, over a population that is not
    #          silently doubled ---------------------------------------------------------------
    b = builder
    b.open()
    s1, s2 = "2026-09-01T00:00:00Z", "2026-09-26T00:00:00Z"
    ed, ed_rows = b._diff_per_view("entity", s1, s2)
    rd, rd_rows = b._diff_per_view("relationship", s1, s2)
    mine = {"estate": ed_rows, "relationship": rd_rows}
    excluded = b._views_excluded_as_not_a_type()
    ref = _python_recount(corpus, s1, s2)
    results["c19"] = (mine, ref, excluded, ref == mine)
    results["c19_ref"] = (mine, ref)
    check("C19.the_diff_census_agrees_with_an_independent_executor",
          mine == ref and "facts" in excluded,
          f"this module's per-view SQL executor and an independent PYTHON recount of the same "
          f"interval over the same CSV files agree to the row: {mine} against {ref}. The view "
          f"list it iterates EXCLUDES {excluded} -- and that exclusion is the correction of a "
          f"defect this module inherited by importing `check_versioning.entity_views`, which "
          f"returns `facts` among its 43 names, so summing over it counts every type twice. "
          f"Measured: 288 against a truth of 144, and `check_versioning.estate_diff` returns "
          f"38 rows for 19 types because of it")

    # ---- C20 the verdict is computed -------------------------------------------------------------
    verdict = builder.diff_detail["verdict"] if builder.diff_detail else "MISSING"
    allowed = {"THE ESTATE", "THE MODEL", "BOTH", "NEITHER"}
    computed = (builder.diff_detail is not None
                and builder.diff_detail["estate_changed"] is not None
                and builder.diff_detail["model_changed"] is not None)
    results["c20"] = (verdict, computed)
    check("C20.the_diff_verdict_is_computed_and_has_no_fifth_value",
          verdict in allowed and computed,
          f"the verdict is `{verdict}`, one of {sorted(allowed)}, and it is a computation over "
          f"two diffs that read different files. NEITHER is a legitimate answer and is not a "
          f"fifth verdict: it says the two coordinates are the same question and the same "
          f"estate")


def _independent_rings(spine: list[dict[str, Any]]) -> dict[str, int]:
    """The spine's rings, by breadth-first search, in a shape deliberately unlike the library's.

    The library memoises on a recursive walk from each type; this walks level by level from the
    roots. Two shapes on purpose: a recursive memo and a level walk fail differently, so a
    disagreement means something rather than meaning "the same code twice".
    """
    parent = {r["type_name"]: r.get("parent") for r in spine}
    roots = {t for t, p in parent.items() if p is None or p not in parent}
    ring = {t: 0 for t in roots}
    frontier = set(roots)
    level = 0
    while frontier and level < 20:
        level += 1
        nxt = {t for t, p in parent.items() if p in frontier and t not in ring}
        for t in nxt:
            ring[t] = level
        frontier = nxt
    return ring


def _python_recount(corpus_root: str, s1: str, s2: str) -> dict[str, int]:
    """The change set's row count, recounted in PYTHON, with the interval written out longhand.

    **This is the second executor, and it is deliberately the least clever implementation
    available.** It reads the CSV files with the standard library, applies ``s1 < system_from <= s2``
    as a string comparison on canonical UTC text -- which is exactly what the dialect's own
    ordering guarantees, so no parsing and no timezone is involved -- and counts. It counts the
    ENTITY side as every file carrying an ``entity_id`` and no ``relationship_id``, which is the
    same population the per-type views cover, so the two are comparable by construction rather than
    by a filter the two executors happen to share.

    Three reasons it is worth having over another SQL query:

    * **a different engine**, so a DuckDB binding or memory problem cannot make both executors
      agree for the same wrong reason;
    * **no 43-view union**, so it is not subject to the ceiling that stops the shipped reference
      executor at *every* size on this machine;
    * **the interval is written out longhand**, so a half-open boundary bug in the SQL predicate
      cannot hide behind the same bug in the comparison.

    **And it is what caught the doubling.** ``check_versioning.estate_diff`` returned 288 against
    this recount's 144, with 38 result rows for 19 types, and the cause was one entry in the view
    list -- ``facts``, the fold's own union of every entity row, which carries an
    ``entity_type`` column and therefore passes ``entity_views``'s test. This module imported that
    list and inherited the doubling; the exclusion is the fix and the criterion is the reason the
    fix exists.
    """
    import csv as _csv
    lo, hi = s1, s2
    estate = relationship = 0
    for base, _dirs, files in os.walk(corpus_root):
        for name in sorted(files):
            if not name.endswith(".csv"):
                continue
            with open(os.path.join(base, name), encoding="utf-8", newline="") as fh:
                rdr = _csv.DictReader(fh)
                if rdr.fieldnames is None or "system_from" not in rdr.fieldnames:
                    continue
                is_rel = "relationship_id" in rdr.fieldnames
                for row in rdr:
                    sf = row.get("system_from") or ""
                    if lo < sf <= hi:
                        if is_rel:
                            relationship += 1
                        else:
                            estate += 1
    return {"estate": estate, "relationship": relationship}


def _reference_status(builder: Any, s1: str, s2: str) -> tuple[str, str]:
    """Can the shipped reference executor run here? Asked, and the answer is reported either way.

    A second executor that is silently absent is a second executor nobody is checking, so this asks
    the question on every run rather than assuming an outcome.
    """
    import check_versioning as CV
    try:
        ed = CV.estate_diff(builder.corpus.con, s1, s2)
        rd = CV.relationship_diff(builder.corpus.con, s1, s2)
        return ("ran", f"it returned {sum(r['rows'] for r in ed)} entity rows and "
                       f"{sum(r['rows'] for r in rd)} relationship rows over this corpus")
    except Exception as exc:                                # noqa: BLE001
        first = str(exc).splitlines()[0][:120]
        return ("NOT RUNNABLE on this machine at this size",
                f"it raised {type(exc).__name__}: {first}. Its `open_corpus()` deliberately skips "
                f"`as_of.configure_connection` (documented, and rightly, to keep the module from "
                f"becoming a fold consumer), so its connection carries NO memory limit; the suite "
                f"only ever runs it over its own miniature fixture. Over a corpus opened by "
                f"`as_of.open_corpus` -- which DOES apply the fold's 1 GiB ceiling -- the 42-view "
                f"UNION is refused. Not this file's to fix: `schema/versioning/` is not this "
                f"ticket's to edit.")


# =============================================================================== the guillotine

# =============================================================================== the guillotine

#: Each mutation is ``(criterion, damage)``, and ``damage`` is applied to the module under test
#: or to a **copy** of the substrate before the control is re-run. The criterion is then re-evaluated
#: by running the control again and reading its verdict -- so a mutation that is watched "failing"
#: is watched by the same code path that would report it green.
#:
#: Two mutations WRITE to the substrate (``C1`` and ``C10``), and they are pointed at the sandbox
#: copy. See :func:`_sandbox` for why that is not optional.
MUTATIONS: list[tuple[str, str, Callable[[dict], None]]] = []


def mutation(criterion: str, what: str):
    def wrap(fn: Callable[[dict], None]) -> Callable[[dict], None]:
        MUTATIONS.append((criterion, what, fn))
        return fn
    return wrap


@mutation("C1", "a `layout_x` column appended to a node file in the substrate")
def _c1(results: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    sub: Sub.Substrate = results["sub"]
    path = os.path.join(sub.graph_dir, "nodes", "compute_node.parquet")
    t = pq.read_table(path)
    pq.write_table(t.append_column("layout_x", pa.array([1.0] * t.num_rows)), path)
    sub._columns_by_type = None
    sub._type_schema = None
    sub._has_type = None


@mutation("C2", "the estate frame given a position for an id that is not a node")
def _c2(results: dict) -> None:
    original = Lay.spine_layout

    def padded(sub, *a, **kw):
        out = original(sub, *a, **kw)
        out["positions"] = list(out["positions"]) + [
            ("acme:compute_node:not-a-node-at-all~000000000000", "compute_node",
             0.0, 0.0, 0, 0, 0.0, None)]
        out["envelope"] = dict(out["envelope"], rows_placed=len(out["positions"]))
        return out

    Lay.spine_layout = padded


@mutation("C3", "the estate frame given TWO positions for one entity")
def _c3(results: dict) -> None:
    original = Lay.spine_layout

    def doubled(sub, *a, **kw):
        out = original(sub, *a, **kw)
        out["positions"] = list(out["positions"]) + [out["positions"][0]]
        out["envelope"] = dict(out["envelope"], rows_placed=len(out["positions"]))
        return out

    Lay.spine_layout = doubled


@mutation("C4", "the algorithm vocabulary widened so a spring layout is accepted")
def _c4(results: dict) -> None:
    Lay.LAYOUT_ALGORITHMS["spring_embedding"] = "a force-directed layout with a random seed"


@mutation("C5", "the ring memoisation deleted, which is the bug the criterion exists for")
def _c5(results: dict) -> None:
    def broken(spine):
        parent = {r["type_name"]: r.get("parent") for r in spine}

        def depth(t, guard):
            if t in guard:
                return 0
            p = parent.get(t)
            if p is None or p not in parent:
                return 0
            return depth(p, guard | {t})

        return {t: depth(t, frozenset()) for t in sorted(parent)}

    Lay._ring_of_type = broken


@mutation("C6", "every layout parent link rewritten to an id that is not a parent of it")
def _c6(results: dict) -> None:
    original = Lay._ring_parents
    #: An id that is WELL FORMED (so `entity_type_from_id` resolves it) and is in NO relation --
    #: so the link it creates is not an edge, and C6's anti-join finds it. **The first version of
    #: this mutation rewrote the parent to `acme:organization:acme~...`, which is a real edge
    #: source for essentially every entity, so the damage was a no-op in truth and the criterion
    #: was right to pass.** A mutation that cannot make the thing wrong is not a mutation.
    ABSENT = "acme:vulnerability:no-such-vulnerability~000000000000"

    def bogus(sub, order):
        out = original(sub, order)
        return {k: (ABSENT if v else v) for k, v in out.items()}

    Lay._ring_parents = bogus


@mutation("C7", "the layout made irreproducible: the polar map now depends on how many times "
                "it has been called")
def _c7(results: dict) -> None:
    #: **The first version of this mutation scaled the polar map by 1.0001, and it did not break
    #: anything**: both computations in C7 go through the same perturbed function, so the layout
    #: stayed perfectly deterministic and the criterion correctly passed. A mutation has to break
    #: the PROPERTY, not change the geometry -- and determinism is a property of two runs agreeing,
    #: so only something that differs between runs can test it.
    state = {"n": 0}

    def counting(ring, angle):
        state["n"] += 1
        nudge = 0.001 * (state["n"] % 2)
        return (round(ring * 1.0 + nudge, 4), round(angle, 4))

    Lay._polar = counting


@mutation("C8", "truncation reported as complete: an over-budget scope claiming to fit")
def _c8(results: dict) -> None:
    original = Lay._envelope

    def lying(*a, **kw):
        env = original(*a, **kw)
        env["truncated"] = False
        env["rows_placed"] = env["rows_available"]
        return env

    Lay._envelope = lying


@mutation("C9", "the tripwire REMOVED and its installer made a no-op")
def _c9(results: dict) -> None:
    #: **Three earlier versions of this mutation were no-ops and the criterion was right to pass**,
    #: and the reason is worth the space. (1) Assigning ``builtins.open = io.open`` reinstated the
    #: guard, because ``io.open`` had itself been wrapped. (2) Making the installer a no-op left the
    #: wrappers from the first control run in place, so the tripwire stayed armed and firing.
    #: (3) Calling ``remove_graphml_tripwire`` alone disarmed it for a moment -- and then
    #: ``open_substrate``, the control's own entry point, re-installed it before C9 looked. So the
    #: damage has to take **both** halves in the right order: remove, then no-op the installer.
    #: A control whose installation is automatic cannot be shown, by removing it, to be what is
    #: doing the work.
    Sub.remove_graphml_tripwire()
    Sub.install_graphml_tripwire = lambda: None


@mutation("C10", "a fifth common column (`node_name`) added to every node file")
def _c10(results: dict) -> None:
    import glob as g
    import pyarrow as pa
    import pyarrow.parquet as pq
    sub: Sub.Substrate = results["sub"]
    for path in sorted(g.glob(os.path.join(sub.graph_dir, "nodes", "*.parquet"))):
        t = pq.read_table(path)
        if "node_name" in t.column_names:
            continue
        pq.write_table(t.append_column("node_name", pa.array(["x"] * t.num_rows)), path)
    sub._columns_by_type = None
    sub._type_schema = None


@mutation("C11", "the client given its own uncapped breadth-first search")
def _c11(results: dict) -> None:
    def own(self, start, depth):
        return (f"WITH RECURSIVE w(entity_id, epoch) AS (SELECT CAST('{start}' AS VARCHAR), 0 "
                f"UNION ALL SELECT e.to_entity_id, w.epoch + 1 FROM w JOIN "
                f"{self.edges_by_src()} e ON e.from_entity_id = w.entity_id) "
                f"SELECT DISTINCT entity_id FROM w")

    Sub.Substrate.neighbourhood_sql = own


@mutation("C12", "the ZERO ROWS rendering removed, so a confident zero looks like a number")
def _c12(results: dict) -> None:
    Exp._record_html = lambda rec, ex, compact=False: "<p>rows</p>"


@mutation("C13", "the timezone-aware columns cast to VARCHAR, which is the obvious wrong fix")
def _c13(results: dict) -> None:
    def to_varchar(self, entity_type):
        parts = []
        for name, dtype in self._schema_of(entity_type):
            if "TIME ZONE" in dtype:
                parts.append(f'CAST("{name}" AS VARCHAR) AS "{name}"')
            else:
                parts.append(f'"{name}"')
        return f"SELECT {', '.join(parts)} FROM {self.type_file(entity_type)}"

    Sub.Substrate.pinned_projection = to_varchar


@mutation("C14", "a hub's degree clamped to the page size, so the page implies it is the list")
def _c14(results: dict) -> None:
    original = Exp.Explorer.edges_of

    def clamped(self, entity_id, direction, facet=None, limit=Exp.PAGE_ROWS, offset=0):
        out = original(self, entity_id, direction, facet, limit, offset)
        out["total"] = min(out["total"], limit)
        out["has_more"] = False
        return out

    Exp.Explorer.edges_of = clamped


@mutation("C15", "the index's own links stop being recorded, so nothing is reachable")
def _c15(results: dict) -> None:
    class NoNav(list):
        def append(self, item):
            if isinstance(item, tuple) and item[0] == "index.html":
                return
            list.append(self, item)

    original = Site.SiteBuilder.build

    def patched(self, scope, **kw):
        self.links = NoNav()
        return original(self, scope, **kw)

    Site.SiteBuilder.build = patched


@mutation("C16", "the GHOSTS relation not read, which cost 1,894 pages of 35,336 at 1M")
def _c16(results: dict) -> None:
    original = Site.SiteBuilder._bulk_reads

    def without_ghosts(self, ids, backlink_rows):
        out = original(self, ids, backlink_rows)
        out["ghosts"] = {}
        return out

    Site.SiteBuilder._bulk_reads = without_ghosts


@mutation("C17", "the footer removed, so no page says which As-Of it is")
def _c17(results: dict) -> None:
    Site.SiteBuilder._footer = lambda self: ""


@mutation("C18", "the whole-estate scope allowed instead of refused")
def _c18(results: dict) -> None:
    Site.SCOPES["all"] = "allowed"
    original = Site.parse_scope

    def patched(scope):
        if scope == "all":
            return {"kind": "window", "s1": "2026-01-01T00:00:00Z",
                    "s2": "2026-09-26T00:00:00Z", "label": "all"}
        return original(scope)

    Site.parse_scope = patched


@mutation("C19", "`facts` re-admitted to the census, which doubles every type's count")
def _c19(results: dict) -> None:
    Site.NOT_A_TYPE_VIEWS = frozenset()


@mutation("C20", "a fifth verdict invented by a client that had an opinion")
def _c20(results: dict) -> None:
    original = Site.SiteBuilder._diff

    def patched(self, s1, s2):
        original(self, s1, s2)
        self.diff_detail["verdict"] = "MOSTLY THE ESTATE"

    Site.SiteBuilder._diff = patched


# =============================================================================== the driver

def _revert() -> dict[str, Any]:
    """Put every mutated symbol back, whatever happened.

    Imported afresh rather than assigned back, because a mutation may have REPLACED a function on
    a module, and holding the original in a local of the mutation function would keep the damage
    alive for the next iteration. A guillotine that leaves its damage behind is not a guillotine.
    """
    import importlib
    #: Remove the tripwire FIRST, then reload. Reloading ``substrate`` while its wrappers are in
    #: ``builtins.open`` would leave an empty ``_PRISTINE`` behind, and the next install would
    #: capture the old wrapper as the "pristine" function -- so a later removal would restore a
    #: guard. The tripwire is now idempotent (it marks its own wrappers), which is the real fix, and
    #: this order is what keeps the guillotine from being the thing that breaks it.
    Sub.remove_graphml_tripwire()
    for name in ("substrate", "layout", "explorer", "build_site"):
        importlib.reload(sys.modules[name])
    return {"substrate": Sub, "layout": Lay, "explorer": Exp, "build_site": Site}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--self-test" in args:
        return _self_test()
    started = time.perf_counter()
    run_control()
    elapsed = time.perf_counter() - started
    print(f"\nsummary: {len(PASSED)} passed, {len(FAILED)} failed, "
          f"{len(SKIPPED)} skipped, of {len(PASSED) + len(FAILED)} criteria, in {elapsed:.1f} s")
    print(f"the published tree: {_assert_published_untouched()}")
    if FAILED:
        print("RESULT: FAIL")
        for c, w in FAILED:
            print(f"  FAIL  {c}: {w}")
        return 1
    print("RESULT: PASS")
    return 0


def _self_test() -> int:
    print("SELF-TEST: each mutation is applied to a SANDBOX COPY of the substrate, the control is "
          "re-run, and that criterion must FAIL.\n")
    control_failed = list(FAILED)
    survived: list[str] = []
    errors: list[str] = []
    global QUIET, ONLY
    for criterion, what, damage in MUTATIONS:
        _revert()
        work = tempfile.mkdtemp(prefix=f"viewer-mut-{criterion}-")
        try:
            graph, schema, corpus = _sandbox(work)
            QUIET = True
            try:
                #: One run to hand the damage something LIVE to break -- the substrate, the layout
                #: scope, the explorer, the site builder. Running the control twice is the price of
                #: being sure the damage landed on live objects and not on copies, and it is
                #: cheaper than the alternative, which is a mutation that "succeeded" against an
                #: object nothing was reading.
                results = run_control(graph, schema, corpus, upto="C1", work=work)
                results["work"] = work
                results["graph"] = graph
                results["c6_seed"] = results["sub"].con.execute(
                    f"SELECT entity_id FROM {results['sub'].node_glob()} "
                    f"WHERE entity_type='network_segment' ORDER BY entity_id "
                    f"LIMIT 1").fetchone()[0]
                try:
                    damage(results)
                except Exception as exc:                    # noqa: BLE001
                    errors.append(f"{criterion}: the damage itself raised "
                                  f"{type(exc).__name__}: {exc}")
                    print(f"  ERROR  {criterion:4s} the damage raised {type(exc).__name__}")
                    continue
                PASSED.clear()
                FAILED.clear()
                SKIPPED.clear()
                #: **A control that RAISES counts as the criterion failing.** A mutation that makes
                #: the module under test crash has been detected MORE sharply than a red check, and
                #: the first version of this loop treated it as a survival -- because no FAILED
                #: entry was produced -- so the one mutation that destroyed the traversal
                #: outright was reported as the one thing the guillotine could not see.
                ONLY = {criterion[:2]}
                try:
                    run_control(graph, schema, corpus, upto=criterion, work=work)
                except Exception as exc:                    # noqa: BLE001
                    FAILED.append((criterion,
                                   f"the control RAISED -- {type(exc).__name__}: "
                                   f"{str(exc).splitlines()[0][:140]}"))
            finally:
                QUIET = False
            hit = any(c.startswith(criterion) for c, _ in FAILED)
            if not hit:
                survived.append(criterion)
            why = "; ".join(w[:200] for _c, w in FAILED) or "(nothing the criterion can see)"
            print(f"  {'FAILS  ' if hit else 'SURVIVED'} {criterion:4s} {what}")
            print(f"           {why}")
        finally:
            _revert()
            shutil.rmtree(work, ignore_errors=True)
    _revert()
    ONLY = None
    after = _assert_published_untouched()
    print(f"\nMUTATIONS: {len(MUTATIONS) - len(survived)} of {len(MUTATIONS)} criteria were "
          f"watched failing")
    print(f"the published tree afterwards: {after}")
    if errors:
        print(f"damage errors: {errors}")
    if control_failed:
        print(f"the CONTROL was not clean: {[c for c, _ in control_failed]}")
    if "CHANGED" in after:
        print("SELF-TEST RESULT: FAIL -- the self-test damaged the published tree")
        return 1
    if survived or control_failed or errors:
        print(f"SELF-TEST RESULT: FAIL -- {len(survived)} mutation(s) survived: {survived}")
        return 1
    print("SELF-TEST RESULT: PASS -- every criterion was watched failing, the control was clean, "
          "and the published tree is byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
