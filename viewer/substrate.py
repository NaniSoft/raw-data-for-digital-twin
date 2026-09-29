"""The one place the substrate is opened.

Why this module exists
======================

The estate is 1.61 GB of GraphML at 995,727 nodes and 1.10 GB of CSV.  ``GraphML`` has no
shard manifest, no index and no partial-read protocol, so **a graph too large to load cannot be
traversed out of GraphML at all** -- which is ``schema/graph/traverse.py``'s first documented way
to traverse a too-large graph, and the reason ``GraphML`` stays an *export format for other
tools* while the Parquet substrate stays the *substrate*.  Every number this package prints is
therefore read from Parquet, and :data:`GRAPHML_IS_NOT_READ` is a **tripwire on the file-open
path**, not a claim in a docstring.

The second thing this module owns is the projection rule, and it is a real trap
=========================================================================

``read_parquet('<substrate>/nodes/*.parquet')`` is *not* a node relation.  The substrate stores
one Parquet file per entity type with a four-column lead block and then that type's own
attributes, so the glob's schema is **whichever file sorts first** -- ``access_rule`` -- and:

* ``DESCRIBE SELECT * FROM <glob>`` reports ``access_rule``'s ten columns for a 995,727-row
  table, so a client that *introspects* to decide what to render renders the wrong thing;
* a projection of a fifth column is refused at **bind** time for a column no file has, and
  **accepted at bind time and refused at scan time** for a column exactly one file has.

Measured at 1M on ``artifacts/full/graph_estate`` -- the numbers are in the ticket answer, and
the shape of the trap is that the count is right either way, so a check that only counts sees
nothing.

So: :data:`LEAD_BLOCK` is imported from ``materialize`` rather than restated, the client may
project **only** those four columns over the glob, and anything else **resolves the entity type
first and reads that type's own file**.  ``viewer.check_viewer``'s criterion ``C10`` asserts the
intersection over every node file is exactly the lead block, so the rule is measured rather than
trusted.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Iterable, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "schema", "fold"), os.path.join(ROOT, "schema", "graph"),
           os.path.join(ROOT, "schema", "csv"), os.path.join(ROOT, "schema", "identity"),
           os.path.join(ROOT, "schema", "resolve"), os.path.join(ROOT, "schema", "versioning")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import as_of          # noqa: E402
import materialize    # noqa: E402
import traverse       # noqa: E402

__all__ = [
    "ViewerRefused", "Substrate", "LEAD_BLOCK", "GRAPHML_IS_NOT_READ",
    "entity_type_from_id", "install_graphml_tripwire", "opened_paths",
]

#: The four columns the whole substrate can answer, imported from the materialiser rather than
#: restated.  ``materialize.NODE_LEAD_BLOCK`` is the declaration; this is a binding to it, and
#: ``check_viewer``'s C10 fails if a fifth column ever appears on every node file.
LEAD_BLOCK = materialize.NODE_LEAD_BLOCK

#: The refusal vocabulary.  Closed, because a client that invents a reason is a client whose
#: refusals a reader cannot enumerate.  ``viewer.layout`` and ``viewer.explorer`` extend it with
#: their own reasons and nothing else may.
REFUSAL_REASONS: dict[str, str] = {
    "graphml_is_not_read": (
        "The estate GraphML is an EXPORT FORMAT for other tools and this package never opens it. "
        "GraphML has no shard manifest, no index and no partial-read protocol, so a graph too "
        "large to load cannot be traversed out of GraphML at all; the substrate is the Parquet "
        "and the query layer is DuckDB. If a request needs the GraphML, the answer is that the "
        "request should be restated over the substrate -- not that the file was read."),
    "lead_block_is_the_only_cross_type_projection": (
        "The substrate stores one Parquet file per entity type, so a glob over nodes/ takes the "
        "schema of whichever file sorts first and DESCRIBE reports access_rule's columns for the "
        "whole estate. Only the four lead-block columns are present on every file; anything else "
        "resolves the entity type and reads that type's own file."),
    "no_coordinate_was_declared": (
        "A snapshot carries its coordinate in its manifest and in its path, never in a column "
        "(D21), so a client that was not told one cannot invent one. `as_known_now` is a "
        "coordinate this package will accept, and it resolves to the manifest's declared value."),
    "out_of_the_render_budget": (
        "The requested view is larger than the render budget. The estate is not refused for "
        "being large -- it is refused for being unrenderable, and the aggregate views that ARE "
        "renderable are always offered beside the refusal."),
    "unknown_scope": (
        "The named scope is not in the closed scope vocabulary. Scopes are data, never strings a "
        "client composes, because a scope that is a string is a second source of truth about what "
        "a site contains."),
}


class ViewerRefused(Exception):
    """Refused rather than degraded, with the reason in the closed vocabulary.

    Same shape as ``query.Refused`` and ``traverse.TraverseError``, and for the same reason: a
    viewer that answers approximately is a viewer whose answer a bitemporal reader cannot tell
    from an exact one.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in REFUSAL_REASONS:
            raise KeyError(f"{reason!r} is not a refusal reason; the vocabulary is closed: "
                           f"{sorted(REFUSAL_REASONS)}")
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail or REFUSAL_REASONS[reason]}")


# ----------------------------------------------------------------------------------- the tripwire

_OPENED: list[str] = []
_TRIPWIRE_INSTALLED = False
_PRISTINE: dict[str, Any] = {}


def opened_paths() -> list[str]:
    """Every file this process has opened since :func:`install_graphml_tripwire` was called."""
    return list(_OPENED)


def install_graphml_tripwire() -> None:
    """Make opening a ``.graphml`` file RAISE, and record every path opened.

    This is the control, and it is a control rather than a claim because it sits on the actual
    file-open path: ``builtins.open``, ``io.open`` and ``os.open``.  A source-text search for the
    string ``.graphml`` would pass on a client that reached GraphML through DuckDB's HTTP
    filesystem handler, through ``zipfile``, or through a subprocess; this cannot.  It can fail --
    it fires the moment any code path touches one -- and the guillotine watches it fire.

    The **pristine functions are kept**, and :func:`remove_graphml_tripwire` puts them back. That
    is not tidiness. The first version of the guillotine's ``C9`` mutation tried to disarm the
    tripwire by assigning ``builtins.open = io.open`` -- and ``io.open`` had itself been wrapped, so
    the "restoration" reinstated the guard and the criterion passed. **A control that cannot be
    removed cannot be shown to be the thing doing the work**, and an irreversible tripwire is also
    a trap for the next thing that legitimately wants to read the export.
    """
    global _TRIPWIRE_INSTALLED
    if _TRIPWIRE_INSTALLED:
        return
    import builtins
    import io as _io

    real_open = builtins.open
    real_io_open = _io.open
    real_os_open = os.open
    #: **Idempotence, and the guillotine is why.** If the open function already carries this
    #: package's mark, the tripwire is installed and ``_PRISTINE`` is already correct -- so return
    #: without re-wrapping. Without this, a module reload (which the guillotine does between every
    #: mutation, correctly) leaves the wrapper in place with an EMPTY ``_PRISTINE``, the next
    #: install then captures the *wrapper* as the pristine function, and
    #: :func:`remove_graphml_tripwire` quietly "restores" a guard instead of removing one. Three
    #: versions of the C9 mutation failed for exactly that reason, and each time the criterion was
    #: right to pass: the tripwire was still there.
    if getattr(real_open, "viewer_graphml_tripwire", False):
        _TRIPWIRE_INSTALLED = True
        return
    _PRISTINE.update(builtins_open=real_open, io_open=real_io_open, os_open=real_os_open)

    def _guard(path: Any) -> None:
        try:
            text = os.fspath(path)
        except TypeError:
            return
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        if text.endswith(".graphml"):
            raise ViewerRefused(
                "graphml_is_not_read",
                f"the tripwire fired: something tried to open {text!r}. The estate GraphML is an "
                f"export format, not a substrate.")
        _OPENED.append(text)

    def guarded_open(file, *a, **kw):
        _guard(file)
        return real_open(file, *a, **kw)

    def guarded_io_open(file, *a, **kw):
        _guard(file)
        return real_io_open(file, *a, **kw)

    def guarded_os_open(path, *a, **kw):
        _guard(path)
        return real_os_open(path, *a, **kw)

    builtins.open = guarded_open          # type: ignore[assignment]
    _io.open = guarded_io_open             # type: ignore[assignment]
    os.open = guarded_os_open              # type: ignore[assignment]
    for fn in (guarded_open, guarded_io_open, guarded_os_open):
        fn.viewer_graphml_tripwire = True  # type: ignore[attr-defined]
    _TRIPWIRE_INSTALLED = True


def remove_graphml_tripwire() -> None:
    """Put the file-open functions back, and disarm. Reversible on purpose -- see above."""
    global _TRIPWIRE_INSTALLED
    if not _TRIPWIRE_INSTALLED or not _PRISTINE:
        return
    import builtins
    import io as _io
    builtins.open = _PRISTINE["builtins_open"]     # type: ignore[assignment]
    _io.open = _PRISTINE["io_open"]                 # type: ignore[assignment]
    os.open = _PRISTINE["os_open"]                  # type: ignore[assignment]
    _TRIPWIRE_INSTALLED = False


#: Named here so a reader can see the control exists without reading the function.
GRAPHML_IS_NOT_READ = "graphml_is_not_read"


# ----------------------------------------------------------------------------------- the substrate


_ID_RE = re.compile(r"^acme:(?P<type>[a-z0-9_.]+):")


def entity_type_from_id(entity_id: str) -> str:
    """The entity type of an id, read off the id.

    ``materialize.entity_type_from_id`` is the authority and is called, not restated: a second
    parser for D20's id is a second truth about what an id is, which is the defect
    ``schema/identity`` exists to prevent.
    """
    return materialize.entity_type_from_id(entity_id)


class Substrate:
    """One materialised snapshot, opened over Parquet, with the manifest as its authority.

    The coordinate is read from the manifest and nowhere else.  A caller may *ask* for
    ``as_known_now``, which resolves to the manifest's declared ``as_of``; a caller may not
    supply an instant, because the substrate holds exactly one coordinate's estate and a
    different instant is a different fold.
    """

    def __init__(self, graph_dir: str, schema_dir: str | None = None,
                 layout_dir: str | None = None) -> None:
        self.graph_dir = os.path.abspath(graph_dir)
        self.manifest_path = os.path.join(self.graph_dir, "manifest.json")
        if not os.path.exists(self.manifest_path):
            raise ViewerRefused("unknown_scope",
                                f"{self.graph_dir} has no manifest.json; a directory with no "
                                f"manifest is not a snapshot (D21: the coordinate lives in the "
                                f"manifest and in the path)")
        self.manifest: dict[str, Any] = json.loads(
            open(self.manifest_path, encoding="utf-8").read())
        self.schema_dir = os.path.abspath(schema_dir) if schema_dir else None
        #: Where the LAYOUT RELATION lives. It is a separate artefact from the substrate and is
        #: never inside it -- `sync.layout_is_not_a_node_attribute` is the shipped check and a
        #: layout file under nodes/ would be picked up by the glob every read in this package uses.
        #: The default is `viewer/out/<size>_frame` rather than anything under `artifacts/`, because
        #: `artifacts/` is a PUBLISHED tree: a viewer's derived output written into it inflates the
        #: file count in the run report and makes a published artefact depend on whether a viewer
        #: has been run, which is a second source of truth about the tree.
        self.layout_dir = os.path.abspath(
            layout_dir or _default_layout_dir(self.graph_dir))
        self._con = None
        self._columns_by_type: dict[str, list[str]] | None = None
        self._type_schema: dict[str, list[tuple[str, str]]] | None = None
        self._has_type: set[str] | None = None
        self._ghost_types: list[str] | None = None
        self._estate_frame: dict[str, tuple] | None = None
        self._estate_envelope: dict[str, Any] | None = None

    # -- the estate frame: the layout relation's `estate` scope, read once -------------------------
    def estate_frame(self) -> dict[str, Any]:
        """The estate layout scope: a lookup, or an honest ``not_run``.

        The 995,727-row frame is **written once** and read thereafter, because computing it is
        4.5 s of sorting and nearly a million tuples, and no page view should pay that. A client
        that computed it per request would be a client whose "where is this" cost depends on how
        many pages the user has already looked at.
        """
        if self._estate_envelope is not None:
            return {"status": "ok", "envelope": self._estate_envelope,
                    "scope_dir": self.estate_scope_dir()}
        scope_dir = self.estate_scope_dir()
        if not os.path.exists(os.path.join(scope_dir, "positions.parquet")):
            return {
                "status": "not_run",
                "reason": "the estate frame has not been written. `python viewer/explorer.py "
                          "--write-estate-layout` writes it once (995,727 rows, 14.56 MB). This "
                          "page reports not_run rather than an empty frame, because an empty "
                          "frame and an unwritten one look identical in a table and mean opposite "
                          "things.",
                "scope_dir": scope_dir,
            }
        import json as _json
        with open(os.path.join(scope_dir, "envelope.json"), encoding="utf-8") as fh:
            self._estate_envelope = _json.load(fh)
        return {"status": "ok", "envelope": self._estate_envelope, "scope_dir": scope_dir}

    def estate_scope_dir(self) -> str:
        return os.path.join(self.layout_dir, "layout", "estate")

    def estate_positions(self, entity_ids: Sequence[str]) -> dict[str, tuple]:
        """Many nodes' home positions, from ONE read of the frame.

        **The first draft read the 14.56 MB frame once PER ENTITY**: 72 ms a page, and 42 minutes
        for a 35,336-page site. A cost that is a function of the *scope* rather than of the work is
        the shape of the mistake this repository calls "a stage that holds what it does not read",
        and at 1M it is the difference between a site and no site.
        """
        if self._estate_frame is None:
            frame = self.estate_frame()
            if frame["status"] != "ok":
                self._estate_frame = {}
            else:
                import pyarrow.parquet as pq
                table = pq.read_table(os.path.join(frame["scope_dir"], "positions.parquet"),
                                      columns=["entity_id", "x", "y", "ring", "sector"])
                self._estate_frame = {r["entity_id"]: (r["x"], r["y"], r["ring"], r["sector"])
                                      for r in table.to_pylist()}
        if not self._estate_frame:
            return {}
        wanted = set(entity_ids)
        return {k: v for k, v in self._estate_frame.items() if k in wanted}

    # -- the coordinate, from the manifest and nowhere else ----------------------------------
    @property
    def coordinate(self) -> dict[str, str]:
        return dict(self.manifest["as_of"])

    @property
    def organization(self) -> str:
        return self.manifest["organization"]

    @property
    def corpus_fingerprint(self) -> str:
        return self.manifest["corpus_fingerprint"]

    @property
    def valid_time_window(self) -> str:
        """The manifest's ``valid_time_window``, which is the constant ``NOT_DECLARED``.

        Read from the manifest rather than restated, because a client that hardcoded the word
        would be making its own claim about the world window. D52: the world window must never be
        declared, because a valid-time extent is a completeness claim whose denominator is the
        twin's own belief about the world.
        """
        return self.coordinate["valid_time_window"]

    @property
    def estate_state(self) -> str:
        """``read`` or ``empty_belief``, from the manifest.

        A **fact about the twin, not about the world**. Every rendered answer in this package
        carries it, and a rendered "no results" is never allowed to be indistinguishable from
        "nothing exists" -- which is the standing ``KNOWN_GAPS`` failure this repository has paid
        for once already.
        """
        return self.coordinate.get("estate_state", "read")

    # -- relations ----------------------------------------------------------------------------
    def node_relation(self) -> str:
        """The glob, and the four columns it may be asked for."""
        return self.node_glob()

    def node_glob(self) -> str:
        return f"read_parquet('{os.path.join(self.graph_dir, 'nodes', '*.parquet')}')"

    def edges_by_src(self) -> str:
        return f"read_parquet('{os.path.join(self.graph_dir, 'edges_by_src.parquet')}')"

    def edges_by_dst(self) -> str:
        return f"read_parquet('{os.path.join(self.graph_dir, 'edges_by_dst.parquet')}')"

    def type_file(self, entity_type: str) -> str:
        """The one type's own Parquet, named by the type.

        This is the only way to read a per-type attribute, and the reason is the glob's schema
        (see the module docstring).  A type with a ``.`` in its name is a pack type and its file
        is ``nodes/<ns>.<type>.parquet``, which is the same join.

        **A type with no node relation is refused by name, and that refusal carries the reason.**
        On the shipped full-scale artefacts exactly one type is in that state -- ``certificate``,
        whose every selected row is a retract -- and raising ``IOException: No files found that
        match ... certificate.parquet`` at a reader who typed a real entity id would hide a
        published-artefact divergence behind a stack trace. The refusal names it instead.
        """
        return f"read_parquet('{os.path.join(self.graph_dir, 'nodes', entity_type)}.parquet')"

    def has_type(self, entity_type: str) -> bool:
        if self._has_type is None:
            self._has_type = set(self.materialised_types())
        return entity_type in self._has_type

    def ghosts(self) -> str:
        return f"read_parquet('{os.path.join(self.graph_dir, 'nodes', 'ghosts.parquet')}')"

    # -- the two type sets, and the divergence between them ---------------------------------------
    def materialised_types(self) -> list[str]:
        """The entity types that have a node relation. ``ghosts`` is excluded and named.

        ``ghosts`` is a graph concept with no CSV column -- a CSV row is an entity in the estate
        and a node may be a ghost -- so counting it as a materialised type would make the two sets
        the same size by accident and hide a real divergence by one.
        """
        import glob as _glob
        return sorted(os.path.basename(p)[:-len(".parquet")]
                      for p in _glob.glob(os.path.join(self.graph_dir, "nodes", "*.parquet"))
                      if not p.endswith("ghosts.parquet"))

    def exported_types(self) -> list[str]:
        """The entity types the GRAPHML export holds, read from the manifest's own file list.

        **Read as strings from ``manifest["export"]["files"]``, not by opening a ``.graphml``.**
        The manifest already names every shard, so the set of types the export contains is knowable
        without touching the export -- which is what lets the tripwire stay armed while the one
        check that needs to compare the two artefacts still runs. A check that had to open the
        GraphML to compare it would be a check this package cannot have.

        ``model.graphml`` is in that list and is **excluded by name and by shape**: it is the
        schema graph, it is at the top of the directory rather than under ``shards/``, and it
        carries no ``-<shard>`` suffix. Without the exclusion it reads as an entity type called
        ``model`` -- and the site's index duly reported ``types_only_in_the_graphml_export:
        ['model']``, which is a type this repository does not have. **A reader that names a thing
        that does not exist is worse than a reader that names nothing**, and the fix is the shape
        (a shard lives under ``shards/`` and carries a numeric suffix) rather than a special case
        for the one file that broke it.
        """
        files = ((self.manifest.get("export") or {}).get("files")) or []
        out = set()
        for name in files:
            base = os.path.basename(name)
            if not base.endswith(".graphml"):
                continue
            if "/" not in name.replace("\\", "/"):
                continue                       # model.graphml: the schema graph, not a shard
            stem = base[:-len(".graphml")]
            if "-" not in stem:
                continue
            out.add(stem.rsplit("-", 1)[0])
        return sorted(out)

    def types_only_in_the_export(self) -> list[str]:
        """Entity types the GraphML export holds and the Parquet substrate does not, AT ALL.

        **Read from the substrate directory alone, and measured to be EMPTY on both published
        sizes.** An earlier draft of this method reported ``['certificate']`` here, on the reading
        that a missing ``nodes/certificate.parquet`` meant the substrate held no certificates. **That
        was wrong, and the correction is the more interesting fact:**

        ==========================  =========  ===========  =========================
        artefact                    present    expected_dead  certificate entities
        ==========================  =========  ===========  =========================
        the corpus                  14,400 rows  (of which 7,200 are retracts)
        the per-type Parquet files    n/a         n/a        **no file at all**
        ``nodes/ghosts.parquet``       n/a       35,079      **7,200, all of them**
        the glob ``nodes/*.parquet``  960,648    35,079      7,200
        the GraphML export            7,200 nodes            7,200
        ==========================  =========  ===========  =========================

        So the estate is **complete**: the 7,200 certificates are in the substrate, in
        ``nodes/ghosts.parquet``, because every selected row for that type is an
        ``operation='retract'`` and so none of them has a ``present`` node. There is no divergence
        between two published artefacts and no entity is missing. The real finding is the *shape*
        one level up, and it is a false all-clear in the most expensive direction -- see
        :meth:`node`.

        What the manifest's ``declared_but_unpopulated_types: ['certificate']`` is, though, is a
        note whose **wording is false**: it says "a declared type with no rows at this coordinate",
        and there are 7,200 rows at this coordinate. They are all retracts. "No present node" and
        "no row" are different facts, and the note reads as though the corpus has nothing to say
        about certificates at all. That is a defect in a settled artefact and it is not this
        package's to fix; it is named here and in the ticket answer.
        """
        in_substrate = set(self.materialised_types()) | set(self.ghost_types())
        return sorted(set(self.exported_types()) - in_substrate)

    def ghost_types(self) -> list[str]:
        """The entity types the GHOSTS relation carries, read from the relation itself."""
        if self._ghost_types is None:
            rows = self.con.execute(
                f"SELECT DISTINCT entity_type FROM {self.ghosts()} ORDER BY 1").fetchall()
            self._ghost_types = [r[0] for r in rows]
        return list(self._ghost_types)

    def holds_entity(self, entity_id: str) -> bool:
        """Is this id in the substrate at all -- live node or ghost?

        Two relations, one question, and the question a client actually has. ``SELECT * FROM
        nodes/*.parquet`` answers it (the glob includes ``ghosts.parquet``); a per-type read does
        not, and :meth:`node` uses this rather than the per-type file list so that a type with no
        ``present`` node is not reported as absent.
        """
        return bool(self.con.execute(
            f"SELECT 1 FROM {self.node_glob()} WHERE entity_id = ? LIMIT 1",
            [entity_id]).fetchone())

    # -- the connection, under the fold's own knobs -------------------------------------------
    @property
    def con(self):
        if self._con is None:
            import duckdb
            self._con = duckdb.connect(":memory:")
            #: The fold's knobs, through the fold's one function. A viewer is a consumer of the
            #: fold's work, so it runs under the fold's ceilings: 2 threads, 1 GiB, %TEMP% spill.
            #: Measured at 1M these are not conservative -- the fold itself peaked at 5,109.9 MB
            #: and a viewer that raised the ceiling would be a viewer that could OOM the machine.
            as_of.configure_connection(self._con)
            self._con.execute(materialize.PINNED_UTC_SQL)
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    # -- per-type columns, read once, and only by asking the file itself -----------------------
    def columns_of(self, entity_type: str) -> list[str]:
        """This type's columns, in the file's own order.

        Read from ``DESCRIBE`` on **that one file**.  A client that took the column list from the
        glob would be reading ``access_rule``'s; that is measured in the ticket answer and it is
        why the method takes a type.
        """
        if self._columns_by_type is None:
            self._columns_by_type = {}
        if entity_type not in self._columns_by_type:
            rows = self.con.execute(f"DESCRIBE SELECT * FROM {self.type_file(entity_type)}").fetchall()
            self._columns_by_type[entity_type] = [r[0] for r in rows]
        return list(self._columns_by_type[entity_type])

    def _schema_of(self, entity_type: str) -> list[tuple[str, str]]:
        if self._type_schema is None:
            self._type_schema = {}
        if entity_type not in self._type_schema:
            rows = self.con.execute(
                f"DESCRIBE SELECT * FROM {self.type_file(entity_type)}").fetchall()
            self._type_schema[entity_type] = [(r[0], r[1]) for r in rows]
        return list(self._type_schema[entity_type])

    def pinned_projection(self, entity_type: str) -> str:
        """A projection with every timezone-aware timestamp pinned to a NAIVE timestamp.

        **This is the class fix, and it is derived from the file's own schema rather than from a
        list.** RUN-STATE's debt section is explicit that pinning six more columns "closes one
        instance of the same problem waiting for the next column", and this derivation closes the
        class for this package: a column added tomorrow is pinned tomorrow, with no code change and
        no list to fall behind.

        Why it is needed at all, measured on ``artifacts/full/graph_estate``: **4 of 42 node files
        carry a ``TIMESTAMP WITH TIME ZONE`` column -- ``observation.observed_at``,
        ``principal.last_activity_at``, ``vulnerability.published_at`` and both
        ``discovery_run`` columns -- and a bare ``SELECT *`` on any of them raises
        ``InvalidInputException: Required module 'pytz' failed to import``.** That is 118,124 of
        995,727 nodes, **11.9% of the estate**, and it is invisible to a count: ``count(*)`` and a
        projection of ``entity_id`` alone both prune the column and both succeed, so a census is
        green over a type whose attributes cannot be read at all.

        **And the obvious fix is a trap, which is why this says NAIVE rather than "make it
        printable".** ``CAST(col AS VARCHAR)`` also stops the pytz failure, and it is *wrong*:

        ===================  ==========================  ==========================
        session TimeZone    ``CAST(col AS VARCHAR)``   the corpus's own text
        ===================  ==========================  ==========================
        UTC                  ``2027-01-04 10:15:54+00``  ``2027-01-04T10:15:54Z``
        Asia/Kolkata         ``2027-01-04 15:45:54+05:30``  ``2027-01-04T10:15:54Z``
        America/New_York     ``2027-01-04 05:15:54-05``  ``2027-01-04T10:15:54Z``
        ===================  ==========================  ==========================

        The instant is right in all three and **the written value differs in two of them**, so a
        viewer that printed the ``VARCHAR`` rendering would show a different observation time on
        every machine -- D22's timezone bug in a printable costume, and the corpus's own text is
        the authority (D19's canonical UTC text, and ``materialize`` renders node attributes as
        that text verbatim). ``CAST(col AS TIMESTAMP)`` is exact: it returns the corpus's instant
        with no zone to shift it.
        """
        parts = []
        for name, dtype in self._schema_of(entity_type):
            if "TIME ZONE" in dtype:
                parts.append(f'CAST("{name}" AS TIMESTAMP) AS "{name}"')
            else:
                parts.append(f'"{name}"')
        return (f"SELECT {', '.join(parts)} FROM "
                f"{self.type_file(entity_type)}")

    def timezone_columns_of(self, entity_type: str) -> list[str]:
        """The columns of one type that are timezone-aware. Reported, so a reader can see the debt."""
        return [n for n, d in self._schema_of(entity_type) if "TIME ZONE" in d]

    def timezone_aware_types(self) -> dict[str, list[str]]:
        """Every materialised type carrying a timezone-aware timestamp, and which columns.

        At 1M this is the blast radius of the pytz failure, and it is a **census over the files'
        own schemas** rather than a hardcoded four, so a new type is counted the day it appears.
        """
        out: dict[str, list[str]] = {}
        for etype in self.materialised_types():
            cols = self.timezone_columns_of(etype)
            if cols:
                out[etype] = cols
        return out

    def lead_block_intersection(self) -> list[str]:
        """The columns every node file has, measured by reading every file's own schema.

        This is the independent expectation ``check_viewer``'s C10 compares the client's rule
        against -- a checker that imported ``materialize.NODE_LEAD_BLOCK`` and compared it to
        itself would check nothing.
        """
        import glob as _glob
        out: set[str] | None = None
        for path in sorted(_glob.glob(os.path.join(self.graph_dir, "nodes", "*.parquet"))):
            cols = {r[0] for r in self.con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
            out = cols if out is None else (out & cols)
        return sorted(out or set())

    # -- reads ---------------------------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        one = self.con.execute(
            f"SELECT (SELECT count(*) FROM {self.node_glob()}), "
            f"(SELECT count(*) FROM {self.edges_by_src()})").fetchone()
        return {"nodes": one[0], "edges": one[1]}

    def type_table(self) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.con.execute(
            f"SELECT entity_type, count(*) FROM {self.node_glob()} "
            f"GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()]

    def node_state_census(self) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.con.execute(
            f"SELECT node_state, count(*) FROM {self.node_glob()} "
            f"GROUP BY 1 ORDER BY 2 DESC").fetchall()]

    def node(self, entity_id: str) -> dict[str, Any]:
        """One node, with **its own type's** columns, and with the type resolved from the id.

        **THE NODE RELATION IS TWO RELATIONS WEARING ONE NAME, and this method is where it bites.**
        Measured on both published sizes: the per-type Parquet files hold **960,648** rows, every
        one of them ``node_state='present'``, and ``nodes/ghosts.parquet`` holds the other
        **35,079** as ``expected_dead``. The glob ``nodes/*.parquet`` returns all 995,727 -- and a
        client that resolves the type and reads that type's own file, which is the CORRECT thing to
        do for attributes, **silently loses every dead entity of that type while its count stays
        right**, because the count comes from the glob and the list comes from the file.

        That is a false all-clear in the most expensive direction on this map: the number is right
        and the enumeration is short, so nothing downstream can tell. The first draft of the site
        builder had exactly this bug and it produced **1,894 pages of 35,336 that did not exist**,
        with the changelog linking to all of them.

        So the three outcomes are kept apart, and each is a different fact:

        ``{}``
            the substrate has never heard of this id;
        ``{"node_state": "expected_dead", "ghost_columns": {...}}``
            the entity is here and it is dead -- no attributes, because a dead entity has an
            end instant and an end's source and nothing else;
        ``{"node_state": "attributes_absent", ...}``
            the entity is here and ``expected_dead`` and its TYPE has no per-type relation at all,
            which is ``certificate``'s case and is a legal state, not an absence.
        """
        etype = entity_type_from_id(entity_id)
        if self.has_type(etype):
            rows = self.con.execute(
                f"{self.pinned_projection(etype)} WHERE entity_id = ?", [entity_id]).fetchall()
            if rows:
                return dict(zip(self.columns_of(etype), rows[0]))
        gh = self.con.execute(
            f"SELECT * FROM {self.ghosts()} WHERE entity_id = ?", [entity_id]).fetchone()
        if gh:
            ghost = {"entity_id": entity_id, "entity_type": etype, "node_state": "expected_dead",
                     "ghost_columns": dict(zip(self.columns_of("ghosts")[1:], gh[1:]))}
            if not self.has_type(etype):
                ghost["node_state"] = "attributes_absent"
                ghost["attributes_absent_because"] = (
                    f"no `present` node of type {etype!r} exists at this coordinate, so the "
                    f"materialiser wrote no per-type relation for it. The entities are NOT missing: "
                    f"they are in `nodes/ghosts.parquet` and they are in the GraphML export of the "
                    f"same coordinate. The manifest records this as "
                    f"`declared_but_unpopulated_types`, whose note reads 'a declared type with no "
                    f"rows at this coordinate' -- and that wording is false, because there ARE rows "
                    f"at this coordinate and every one of them is a retract. 'No present node' and "
                    f"'no row' are different facts.")
            return ghost
        return {}

    # -- the drill, through the PINNED template -------------------------------------------------
    def neighbourhood_sql(self, seed: str, depth: int) -> str:
        """``traverse.py``'s template, verbatim, bound to this substrate.

        Called, never restated. The cap is a parameter the client never supplies, the recursion
        is ``UNION`` not ``UNION ALL``, and the depth is refused above ``MAX_TRAVERSAL_DEPTH`` by
        ``traverse`` itself. A viewer with its own BFS would be a second truth about what a path
        means, which is the defect ``schema/query`` exists to prevent.
        """
        return traverse.build_traversal(self.graph_dir, seed, depth)

    def neighbourhood(self, seed: str, depth: int = 2) -> list[tuple[str, int]]:
        """``(entity_id, depth_reached)`` for one depth-capped out-traversal."""
        sql = self.neighbourhood_sql(seed, depth)
        return [(r[0], r[1]) for r in self.con.execute(sql).fetchall()]

    # -- the schema graph, which is scale-invariant -------------------------------------------
    def schema_relations(self) -> dict[str, str]:
        if not self.schema_dir:
            raise ViewerRefused("unknown_scope",
                                "no --schema-dir: the schema graph is a SEPARATE artefact and is "
                                "not inside the estate directory. Mixing them is what the "
                                "published two-directory layout exists to undo.")
        d = os.path.join(self.schema_dir, "schema")
        return {name: f"read_parquet('{os.path.join(d, name)}.parquet')" for name in
                ("types", "relationships", "spine")}

    def spine(self) -> list[dict[str, Any]]:
        """The estate's own declared topology: one row per type, naming its parent.

        38 rows, byte-identical at every corpus size, which is the measured fact that lets a
        viewer load the schema at 1M and know it is complete. It is also the **facet list**: the
        only way to narrow a 372,093-neighbour hub is by the types that may hang off it, and
        those types are exactly what the spine declares.
        """
        rel = self.schema_relations()["spine"]
        cols = [r[0] for r in self.con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()]
        return [dict(zip(cols, row)) for row in
                self.con.execute(f"SELECT * FROM {rel} ORDER BY type_name").fetchall()]


def _default_layout_dir(graph_dir: str) -> str:
    """``viewer/out/<size>_frame``, where ``<size>`` is the substrate's own parent directory name.

    A path built by string surgery on the substrate's location would put a viewer's output wherever
    the caller happened to point it, and the first draft's default was ``<graph>/../viewer_out`` --
    which lands **inside ``artifacts/``**, a published tree whose file list is recorded in
    ``run_report.json``. Running a viewer then changed the published tree, so a viewer's existence
    became a fact about the artefacts. Derived from the size directory's own name, and it is
    outside ``artifacts/`` by construction.
    """
    size = os.path.basename(os.path.dirname(os.path.abspath(graph_dir)))
    return os.path.join(ROOT, "viewer", "out", f"{size}_frame")


def open_substrate(graph_dir: str, schema_dir: str | None = None,
                   layout_dir: str | None = None) -> Substrate:
    install_graphml_tripwire()
    return Substrate(graph_dir, schema_dir, layout_dir)


def iter_files(directory: str, suffix: str = "") -> Iterable[str]:
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix):
            yield os.path.join(directory, name)
