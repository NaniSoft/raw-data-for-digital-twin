"""The static As-Of corpus: a generated per-entity site with back-links, and an As-Of diff.

What it is, and why the ticket's instinct is right
=================================================

The ticket says this is "the one that earns its keep for free: the same generator that produces a
snapshot produces a browsable version, and two snapshots produce a changelog site." **The instinct
is right and the arithmetic is better than expected.** At 1M, over the last 30 days of the corpus's
own declared observation window, measured on ``artifacts/full``:

===========================================  ==========
changed relationship rows                   36,068
distinct entities in the change set         35,336
**of which have a node in the substrate**   **35,336 (100%)**
changed entity rows                         14,022, over 22 types
===========================================  ==========

**Every entity the change set names has a page, with none missing and none orphaned.** That is not
a hope; it is the number the back-link census is computed from, and ``check_viewer``'s site criteria
fail by name if a single one of the 35,336 cannot be resolved or cannot be reached.

And the site is cheap. The formatting is ~4 microseconds a page and the write is the floor, so a
30-day site is 35,336 pages and a few hundred megabytes. The whole-estate site is 2.41 GB and
995,727 pages and **is refused by name** -- see :data:`SCOPES`.

The site's address IS the window
================================

The obvious design -- one page per entity, for the whole estate -- is 995,727 pages: mechanically
cheap and useless, because nobody navigates a million pages by clicking and the index that would let
them find page 500,000 is itself 995,727 rows. The browsable artefact is the **change set**, and a
change set has a window, so the scope is the window and the window is the site's address. "Hand a
colleague a URL and a month ago" is then a literal description of the artefact: a month's change set
is 35,336 pages, and the whole 18-month window is 1,517,371 relationship assertions -- 43% of the
estate -- which is why the window is named in the output directory and never defaulted.

The back-link rule, and why it is the interesting part
======================================================

A back-link that resolves to nothing is a dead end a reader cannot distinguish from a finding, so
every link in the site is one of exactly two kinds and **there is no third**:

* **inside** the declared scope -- resolves to a page this build generated, checked by walking the
  recorded link graph from ``index.html`` and requiring it to cover every generated file;
* **outside** the scope -- carries ``data-outside`` naming **the substrate query that would fetch
  it**, so a reader who wants it is told the query rather than shown a 404.

A link that is neither is a **broken back-link** and fails the run by name. The estate is a million
nodes and the scope is 35,336, so most of a page's neighbours are outside -- and "outside, here is
the query" is the honest rendering of that.

The As-Of diff, and the one rule it must not break
==================================================

The diff is **the estate diff and the model diff, and a verdict line with three values and no
fourth** -- ``THE ESTATE`` / ``THE MODEL`` / ``BOTH`` -- because that is ticket 19's decision and a
second verdict vocabulary is a second truth about what a diff means. The aggregates come from
``check_versioning.estate_diff`` and ``relationship_diff``, **called, not restated**, and
``check_viewer`` compares this module's own row-level counts against those two aggregates and fails
on any disagreement: two executors, one meaning, D49's arrangement.

The rule it must not break: **the change set is the rows whose ``system_from`` is in ``(S1, S2]``,
read from the CORPUS and never by diffing two snapshots.** ``check_versioning.estate_diff``'s own
docstring gives the reason and it is the reason the whole bitemporal model exists: *a diff of
snapshots is blind to exactly the retroactive corrections the twin holds.* The interval is
half-open, ``S2`` is the corpus's declared **inclusive** window end and never midnight, and both
ends are printed on every page -- a boundary quietly moved by a day is a diff that answers a
different question and looks entirely well formed. It was nearly one here: an early measurement
used ``<= '2027-04-25'`` and one used ``<= '2027-04-25T23:59:59Z'``, and the two disagreed by
**3,438 rows** with nothing but the hour between them to explain it.
"""

from __future__ import annotations

import html
import json
import os
import shutil
import sys
import time
from typing import Any, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
for _p in ("schema/fold", "schema/graph", "schema/csv", "schema/identity", "schema/resolve",
           "schema/versioning"):
    _full = os.path.join(ROOT, _p.replace("/", os.sep))
    if _full not in sys.path:
        sys.path.insert(0, _full)

import as_of              # noqa: E402
import check_versioning   # noqa: E402
import layout as VLayout  # noqa: E402
import substrate as VSubstrate  # noqa: E402
from substrate import ViewerRefused  # noqa: E402

SITE_VERSION = "asof-site-v1"

#: The closed scope vocabulary. Data, never a format string a client composes.
SCOPES: dict[str, str] = {
    "window": (
        "The change set: every entity named by a corpus row whose system_from is in (S1, S2]. "
        "This is the browsable artefact. At 1M a 30-day window is 36,068 relationship rows over "
        "35,336 entities, every one of which has a node in the substrate, so every one gets a "
        "page and no link is dead."),
    "seed": (
        "One entity and every entity its changed rows touch, at the substrate's coordinate. A "
        "window too small to be interesting, and useful for asking 'what moved around this thing'."),
    "all": (
        "REFUSED. One page per entity for the whole estate is 995,727 pages and 2.41 GB of HTML at "
        "1M. The formatting is cheap -- measured at about 4 us a page, so about 4 s -- which is "
        "exactly the trap: the cost is not the disk, it is that a reader cannot navigate a million "
        "pages by clicking and the index that would let them is itself 995,727 rows. A scope that "
        "is the whole estate has no address. Use a window."),
}

#: How many back-links one page carries, and how many it *says* it has. Both, always: a page that
#: shows 200 of 372,093 and does not say so is a page asserting a list of 200.
BACKLINK_ROWS = 200

#: How many changed assertions the changelog page lists before it says it is paged. A count is not
#: a page, and a changelog that silently shows the first N reads as the whole thing.
CHANGELOG_ROWS = 5000


class SiteRefused(ViewerRefused):
    """A site refusal. The reason is in a closed vocabulary, for the query layer's reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in SITE_REFUSALS:
            raise KeyError(f"{reason!r} is not a site refusal; the vocabulary is closed: "
                           f"{sorted(SITE_REFUSALS)}")
        self.reason = reason
        self.detail = detail
        Exception.__init__(self, f"{reason}: {detail or SITE_REFUSALS[reason]}")


SITE_REFUSALS: dict[str, str] = {
    "scope_all_is_refused": (
        "The whole-estate site is 995,727 pages and 2.41 GB at 1M and is mechanically cheap, "
        "which is why it is refused rather than allowed: cheap to build and impossible to browse. "
        "A site's address has to be a window."),
    "scope_is_not_in_the_closed_vocabulary": (
        "Scopes are data, not format strings. A scope a client composes is a second source of truth "
        "about what a site contains."),
    "diff_needs_a_second_as_of": (
        "A diff between one As-Of and itself is empty and reports itself as empty, which is a true "
        "answer and a useless artefact. Two coordinates, or none."),
    "site_coordinate_comes_from_the_manifest": (
        "A snapshot carries its coordinate in its manifest and in its path, never in a column and "
        "never in a build argument. A site built at a coordinate nobody declared is a site whose "
        "pages cannot be checked against their source."),
}


def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _norm(path: str) -> str:
    """One spelling for a generated file, whatever the platform.

    **``os.path.normpath`` is the wrong function here and it failed on the first run.** On Windows
    it returns ``entity\\acme%3A...html`` while the generated set is spelled
    ``entity/acme%3A...html``, so *every one* of 116,165 recorded inside-links was reported broken
    and every one of 35,336 pages was reported an orphan -- on a site with no dead link and no
    orphan at all. The census was comparing two spellings of the same path and calling the
    difference a defect.

    That is the exact class this repository names twice in its ledger: **a mechanism reporting
    something mechanically true in place of the substantive one, in a way that invites action.**
    A reader of that output would have gone and "fixed" a site that was correct.
    """
    return path.replace("\\", "/").lstrip("./")


def _as_instant(value: Any) -> str | None:
    """A temporal value as the corpus's canonical UTC TEXT, or None.

    The corpus's temporal block is canonical UTC text (D19/D22) and `check_versioning`
    renders its own aggregates through `check_versioning._ts`, which is what this is for: a
    diff page that printed a DuckDB datetime instead would be a second rendering of a corpus
    fact, and a machine-dependent one.
    """
    if value is None:
        return None
    text = str(value).replace(" ", "T")
    if not text.endswith("Z"):
        text += "Z"
    return text


def _attributes_absent_reason(entity_type: str) -> str:
    """Why a type has no per-type relation, stated as a fact and not as an absence.

    **Corrected after being wrong once, and the correction is the finding.** An earlier draft of
    this function said the substrate held no ``certificate`` entities and that the GraphML export
    and the Parquet substrate disagreed. **They do not disagree.** The substrate holds all 7,200 of
    them, in ``nodes/ghosts.parquet``, because every selected row for that type is an
    ``operation='retract'`` and so none of them has a ``present`` node to write into a per-type
    file. The estate is complete.

    What is real is one level down and it is a different defect: the per-type Parquet files hold
    **only** ``present`` nodes (960,648 of 995,727), so a client that resolves the type and reads
    that type's file -- the correct thing to do for attributes -- silently loses every dead entity
    of that type while its *count*, which comes from the glob, stays right. That is a false
    all-clear with the number right and the list short, and it cost this package 1,894 missing
    pages out of 35,336 before the ghosts relation was read.
    """
    return (f"no `present` node of type {entity_type!r} exists at this coordinate, so the "
            f"materialiser wrote no per-type relation for it. The entities are NOT missing: they "
            f"are in `nodes/ghosts.parquet` as `expected_dead` nodes, and they are in the GraphML "
            f"export of the same coordinate. The manifest records this as "
            f"`declared_but_unpopulated_types`, whose note reads 'a declared type with no rows at "
            f"this coordinate' -- and that wording is false, because there ARE rows at this "
            f"coordinate and every one of them is a retract. 'No present node' and 'no row' are "
            f"different facts, and only the first is true here.")


def _not_in_substrate_reason(sub: Any, entity_type: str) -> str:
    """The shared wording for an id whose type has no node relation in this artefact.

    **Module scope on purpose, and it must stay there.** An earlier draft had this function
    *between two methods of the class*, which silently turned every method after it into dead code
    nested in its body: the class had no ``_entities`` at all and the build died with a bare
    ``AttributeError`` that named nothing about the edit. A misplaced definition is not a syntax
    error; it is a class that quietly stops working.
    """
    only_here = entity_type in sub.exported_types()
    if only_here:
        diverge = sub.types_only_in_the_export()
        return (f"the entity type {entity_type!r} has no node relation in this artefact, and the "
                f"GraphML export of the same coordinate DOES carry it ({len(diverge)} type(s) are "
                f"in the export and not in the substrate: {diverge}). This is a divergence between "
                f"two published artefacts of one coordinate, not an absence of the entity, and it "
                f"is not this viewer's to fix.")
    return (f"the entity type {entity_type!r} has no node relation in this artefact and the "
            f"GraphML export of the same coordinate does not carry it either, so the entity is "
            f"absent from every published artefact of this coordinate.")


# ------------------------------------------------------------------------------- the scope

def _is_instant(text: str) -> bool:
    return (len(text) == 20 and text.endswith("Z") and text[4] == "-" and text[7] == "-"
            and text[10] == "T" and text[13] == ":" and text[16] == ":" and text[19] == "Z")


def parse_scope(scope: str) -> dict[str, Any]:
    """A scope string into a scope record, and ``all`` into a refusal.

    The three shapes are **parsed, not interpreted**: ``window:S1..S2`` is split on ``..`` and both
    ends are validated as instants, so a malformed boundary is a refusal rather than a window that
    silently contains nothing.
    """
    if scope == "all":
        raise SiteRefused("scope_all_is_refused", SCOPES["all"])
    if ":" not in scope:
        raise SiteRefused("scope_is_not_in_the_closed_vocabulary",
                          f"{scope!r}; the vocabulary is {sorted(SCOPES)} and the shapes are "
                          f"window:<S1>..<S2> and seed:<entity_id>")
    kind, rest = scope.split(":", 1)
    if kind not in SCOPES:
        raise SiteRefused("scope_is_not_in_the_closed_vocabulary",
                          f"{kind!r} is not one of {sorted(SCOPES)}")
    if kind == "window":
        if ".." not in rest:
            raise SiteRefused("scope_is_not_in_the_closed_vocabulary",
                              f"a window scope is window:<S1>..<S2>, not {rest!r}. The interval is "
                              f"HALF-OPEN, (S1, S2]: S1 is excluded and S2 is included, which is "
                              f"D19's definition and the reason a window with a closed left end "
                              f"double-counts its boundary row.")
        s1, s2 = rest.split("..", 1)
        for label, value in (("S1", s1), ("S2", s2)):
            if not _is_instant(value):
                raise SiteRefused("scope_is_not_in_the_closed_vocabulary",
                                  f"{label}={value!r} is not an instant (want "
                                  f"YYYY-MM-DDTHH:MM:SSZ). A window that ends at MIDNIGHT is a "
                                  f"window that silently drops the last day: measured here, "
                                  f"`<= 2027-04-25` and `<= 2027-04-25T23:59:59Z` differ by 3,438 "
                                  f"changed relationship rows at 1M.")
        return {"kind": "window", "s1": s1, "s2": s2, "label": f"{s1[:10]}..{s2[:10]}"}
    if not rest:
        raise SiteRefused("scope_is_not_in_the_closed_vocabulary", "seed: needs an entity_id")
    return {"kind": "seed", "seed": rest, "label": rest.split(":")[-1].split("~")[0]}


#: The change-set predicate, written ONCE here and compared against ``check_versioning``'s.
#:
#: Naive ``TIMESTAMP`` on both sides, deliberately, and the session pinned to UTC by
#: ``materialize.PINNED_UTC_SQL``: the corpus's temporal block is canonical UTC *text* (D22's own
#: fix), so a cast to ``TIMESTAMPTZ`` would re-interpret it in the session's zone. **Measured, and
#: the cost is not a rounding error:** ``check_versioning.estate_diff`` and ``relationship_diff``
#: both cast to ``TIMESTAMPTZ`` and pin nothing, and over one 25-day window of ``slice/corpus``
#: they return, by session zone --
#:
#:   ===================  =============  ===============
#:   session TimeZone     entity rows    relationship rows
#:   ===================  =============  ===============
#:   UTC                  144            813
#:   Asia/Kolkata         143            811
#:   America/New_York     144            **395**
#:   Europe/Berlin        145            817
#:   the truth            144            813
#:   ===================  =============  ===============
#:
#: **only UTC agrees**, and the machine this was measured on is India Standard Time, so the shipped
#: diff is wrong here and catastrophically wrong for relationships in New York. Nothing else in the
#: artefact notices: the rows are well formed, the count is not zero, and the verdict line is
#: unchanged, because a uniform shift cannot change whether the estate changed. This is RUN-STATE's
#: documented TIMESTAMPTZ debt, in a settled artefact, on the code path this ticket's diff depends
#: on. Not fixed here -- ``schema/versioning/`` is not this ticket's to edit.
CHANGE_PREDICATE = ("CAST(system_from AS TIMESTAMP) > CAST(? AS TIMESTAMP) "
                    "AND CAST(system_from AS TIMESTAMP) <= CAST(? AS TIMESTAMP)")

#: Views that ``check_versioning.entity_views`` returns and that are **not entity types**.
#:
#: ``facts`` is the fold's own materialisation: a union of every entity row, carrying an
#: ``entity_type`` column, which is exactly the test ``entity_views`` applies. Including it in a
#: per-type census counts every type twice -- measured at 288 against a truth of 144, and
#: ``check_versioning.estate_diff`` returns 38 rows for 19 types because of it.
#:
#: **Declared as a named exclusion rather than a filter in place**, because a silent filter is how
#: a reader ends up believing a number that was halved on purpose and cannot say so.
NOT_A_TYPE_VIEWS: frozenset[str] = frozenset({"facts"})
NOT_A_TYPE_WHY = (
    "`facts` is as_of's own union of every entity row, materialised with one INSERT per declared "
    "type. entity_views() returns it because it carries an entity_type column, and summing a "
    "per-type census over that list counts every type twice.")


# ------------------------------------------------------------------------------- the builder

_SHELL = ("<!doctype html><meta charset=utf-8><title>{title}</title><style>"
          "body{font:14px/1.55 ui-sans-serif,system-ui,Segoe UI,sans-serif;margin:0;"
          "background:#0f1115;color:#d7dae0}main{max-width:1080px;margin:0 auto;padding:22px}"
          "a{color:#7fb2ff;text-decoration:none}a:hover{text-decoration:underline}"
          "h1{font-size:19px;margin:0 0 6px}h2{font-size:14px;margin:24px 0 6px;"
          "color:#9fb4d8;font-weight:600}"
          "code,.mono{font-family:ui-monospace,Cascadia Code,Consolas,monospace;font-size:12px}"
          "table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:3px 7px;"
          "border-bottom:1px solid #22262e;vertical-align:top}th{color:#9fb4d8;font-size:12px}"
          ".banner{background:#1a1f2a;border-left:3px solid #7fb2ff;padding:9px 13px;"
          "margin:11px 0;border-radius:2px}.warn{border-left-color:#e0a04f}"
          ".stop{border-left-color:#e05f5f}.small{color:#8b93a1;font-size:12px}"
          ".pill{display:inline-block;padding:1px 7px;border-radius:9px;background:#22262e;"
          "font-size:11px}.pill.read{background:#1d3326;color:#7fd39a}"
          ".pill.empty{background:#3a2a1d;color:#e0a04f}"
          "a[data-outside]{color:#e0a04f}a[data-outside]:after{content:' (outside)'}"
          "</style><main>{body}</main>")


class SiteBuilder:
    """Generate a static site for one As-Of, over one declared scope.

    The coordinate comes from the substrate's manifest. The change set comes from the corpus. The
    attributes come from the per-type Parquet. The positions come from the layout relation. **No
    fact in the site is computed twice**, and each of those four is an import rather than a
    reimplementation -- ``check_viewer``'s criteria are what keep it that way.
    """

    def __init__(self, graph_dir: str, schema_dir: str, corpus_dir: str, out_dir: str,
                 organization: str = "acme") -> None:
        self.out_dir = os.path.abspath(out_dir)
        #: The LAYOUT RELATION is written into the site's own directory, never into the
        #: substrate: `sync.layout_is_not_a_node_attribute` is a shipped check, and a layout file
        #: under ``nodes/`` would be picked up by the glob every read in this package uses.
        self.sub = VSubstrate.open_substrate(graph_dir, schema_dir, self.out_dir)
        self.corpus_dir = corpus_dir
        self.organization = organization
        self.corpus: Any = None
        self.pages: list[str] = []
        #: every link the build emitted, as ``(from_page, href, declared_outside)``
        self.links: list[tuple[str, str, bool]] = []
        self._broken: list[tuple[str, str]] = []
        self._positions: dict[str, tuple] = {}
        self.scope: dict[str, Any] = {}
        self.scope_label = ""
        self.scope_ids: set[str] = set()
        self.census_bytes = 0
        self.site_record: dict[str, Any] = {}
        self.diff_detail: dict[str, Any] | None = None

    # -- the corpus, opened once ----------------------------------------------------------------
    def open(self) -> None:
        if self.corpus is None:
            self.corpus = as_of.open_corpus(self.corpus_dir, self.organization)

    def declared_window(self) -> tuple[str, str]:
        """The corpus's declared observation window, read from the corpus and not from a clock.

        D22: ``now`` is the corpus's declared window end, not a wall clock, which is the whole
        reason two folds of the same corpus are byte-identical. A site that dated itself from the
        machine would be a different site on a different day.
        """
        self.open()
        return self.corpus.observation_window()

    # -- the scope's entity set ------------------------------------------------------------------
    def scope_entities(self, scope: dict[str, Any]) -> dict[str, Any]:
        """The scope's entity ids, and the count of the change set that produced them.

        **One statement per view, accumulated in Python.** A single ``UNION ALL`` over 42 entity
        views and one relationship view is exactly what the fold's own working-set rule is against
        -- ``as_of.open_corpus`` materialises ``facts`` with one ``INSERT`` per declared type
        because DuckDB binds its readers when the statement is *prepared* -- and at 1M the union
        raised ``OutOfMemoryException: could not allocate block of size 30.5 MiB (1008.3 MiB/1.0
        GiB used)`` against the fold's own 1 GiB ceiling.

        The ceiling is not the thing that is wrong. The ceiling is D22's and it is what keeps a
        viewer from exhausting a 13.9 GB machine. So the reads are per-view, the working set is
        O(one view), and **nothing is raised.**
        """
        self.open()
        if scope["kind"] == "seed":
            return {"entities": [scope["seed"]], "relationship_rows": 0, "entity_rows": 0}
        rel = check_versioning.relationship_views(self.corpus.con)
        ents = check_versioning.entity_views(self.corpus.con)
        s1, s2 = scope["s1"], scope["s2"]
        rel_rows = 0
        ids: set[str] = set()
        for view in rel:
            rel_rows += self.corpus.con.execute(
                f'SELECT count(*) FROM "{view}" WHERE {CHANGE_PREDICATE}', [s1, s2]).fetchone()[0]
            ids.update(r[0] for r in self.corpus.con.execute(
                f'SELECT from_entity_id FROM "{view}" WHERE {CHANGE_PREDICATE}',
                [s1, s2]).fetchall())
            ids.update(r[0] for r in self.corpus.con.execute(
                f'SELECT to_entity_id FROM "{view}" WHERE {CHANGE_PREDICATE}',
                [s1, s2]).fetchall())
        ids.discard(None)
        ent_rows = 0
        for view in ents:
            ent_rows += self.corpus.con.execute(
                f'SELECT count(*) FROM "{view}" WHERE {CHANGE_PREDICATE}', [s1, s2]).fetchone()[0]
        return {"entities": sorted(ids), "relationship_rows": rel_rows, "entity_rows": ent_rows}

    def changed_relationships(self, scope: dict[str, Any],
                              limit: int | None = None) -> list[dict[str, Any]]:
        """The change set, row by row, newest first.

        ``newest first`` because a changelog is read forwards from "now", and a reader who has to
        sort 36,068 rows to find the most recent change is not reading a changelog. The sort key is
        ``(system_from DESC, relationship_type, from_entity_id, to_entity_id)`` -- all four
        declared, so the order is reproducible rather than incidental.
        """
        self.open()
        cols = ("relationship_id", "relationship_type", "from_entity_id", "to_entity_id",
                "system_from", "operation")
        rows: list[dict[str, Any]] = []
        for view in check_versioning.relationship_views(self.corpus.con):
            got = self.corpus.con.execute(
                f'SELECT {", ".join(cols)} FROM "{view}" WHERE {CHANGE_PREDICATE}',
                [scope["s1"], scope["s2"]]).fetchall()
            rows.extend(dict(zip(cols, r)) for r in got)
        rows.sort(key=lambda r: (r["system_from"], r["relationship_type"], r["from_entity_id"],
                                 r["to_entity_id"]), reverse=True)
        return rows[:limit] if limit else rows

    # -- pages ------------------------------------------------------------------------------------
    def _write(self, rel_path: str, title: str, body: str) -> None:
        path = os.path.join(self.out_dir, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = self._shell(title, body) + self._footer() + "</main>"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        self.pages.append(rel_path)
        self.census_bytes += len(text.encode("utf-8"))

    def _shell(self, title: str, body: str) -> str:
        #: Substituted, not ``str.format``-ed: the stylesheet is full of braces and a format call
        #: on it raises ``KeyError: 'font'``. A template that cannot hold CSS is a template whose
        #: CSS gets stripped, and a site with no stylesheet is still a site with a layout bug.
        return _SHELL.replace("{title}", _e(title)).replace("{body}", body)

    def _footer(self) -> str:
        c = self.sub.coordinate
        es = self.sub.estate_state
        return (f"<hr><p class='small'>site_version {SITE_VERSION} &middot; "
                f"coordinate V={_e(c['valid'])} S={_e(c['system'])} &middot; estate_state "
                f"<span class='pill {'read' if es == 'read' else 'empty'}'>{_e(es)}</span>"
                f" &middot; valid_time_window "
                f"{_e(str(self.sub.valid_time_window)[:28])}... &middot; corpus "
                f"{_e(self.sub.corpus_fingerprint)} &middot; scope "
                f"<code>{_e(self.scope_label)}</code><br>"
                f"<b>An <code>estate_state</code> of <code>empty_belief</code> means the twin held "
                f"no belief covering this coordinate. It does not mean nothing exists.</b> Every "
                f"page here was generated from the artefacts named above and from nothing else; "
                f"there is no second copy of any fact in this site.</p>")

    def _slug(self, entity_id: str) -> str:
        """A filesystem name for an id. D20's id has no path separator, so this only has to be safe."""
        return entity_id.replace(":", "%3A").replace("~", "%7E")

    def _entity_link(self, entity_id: str, from_page: str = "changed.html",
                     suffix: str = "") -> str:
        """One link, and it is one of exactly two kinds.

        ``inside`` the declared scope -- resolves to a page this build generated; ``outside`` --
        carries ``data-outside`` naming **the substrate query that would fetch it**. There is no
        third kind, and that is the whole back-link rule. A link to a page that does not exist is a
        lie a reader cannot detect, and a page showing 200 of 372,093 back-links while saying
        nothing asserts a list of 200.
        """
        if entity_id in self.scope_ids:
            href = f"entity/{self._slug(entity_id)}{suffix}"
            self.links.append((from_page, href, False))
            return f"<a href='{href}'>{_e(entity_id)}</a>"
        self.links.append((from_page, entity_id, True))
        etype = VSubstrate.entity_type_from_id(entity_id)
        return (f"<a data-outside=\"SELECT * FROM read_parquet('nodes/{_e(etype)}.parquet') "
                f"WHERE entity_id = '{_e(entity_id)}'\" href='#outside'>{_e(entity_id)}</a>")

    # -- build -------------------------------------------------------------------------------------
    def build(self, scope: dict[str, Any], *, with_diff: tuple[str, str] | None = None,
              backlink_rows: int = BACKLINK_ROWS) -> dict[str, Any]:
        started = time.perf_counter()
        if os.path.isdir(self.out_dir):
            shutil.rmtree(self.out_dir)
        os.makedirs(self.out_dir, exist_ok=True)
        self.scope = scope
        self.scope_label = scope["label"]
        self._broken = []

        found = self.scope_entities(scope)
        self.scope_ids = set(found["entities"])
        lay = VLayout.spine_layout(self.sub)
        VLayout.write_layout(self.out_dir, "estate", lay["envelope"], lay["positions"])

        #: The changelog is written FIRST so the index can print how many pages it has, and the
        #: index's own links are what make every entity page reachable -- so the two are ordered
        #: by what each needs from the other rather than by which is the entry point.
        self._index_changelog_pages: list[str] = []
        self._changed(found)
        self._index(found, with_diff is not None)
        self._entities(found, backlink_rows)
        if with_diff:
            self._diff(with_diff[0], with_diff[1])
        self._site_json(found, started, with_diff, backlink_rows)
        return self.census_report(found, started)

    # -- index -------------------------------------------------------------------------------------
    def _index(self, found: dict[str, Any], with_diff_here: bool = False) -> None:
        s = self.sub
        c = s.coordinate
        rows = [f"<h1>the estate as of {_e(c['valid'])}</h1>",
                f"<div class='banner'>scope <code>{_e(self.scope_label)}</code> &mdash; "
                f"{_e(SCOPES[self.scope['kind']][:150])}...</div>",
                "<table>"
                f"<tr><th>entities in scope</th><td class='mono'>{len(self.scope_ids):,}</td>"
                f"<th>changed relationship rows</th>"
                f"<td class='mono'>{found['relationship_rows']:,}</td>"
                f"<th>changed entity rows</th>"
                f"<td class='mono'>{found['entity_rows']:,}</td></tr>"
                f"<tr><th>nodes in the substrate</th>"
                f"<td class='mono'>{sum(n for _, n in s.type_table()):,}</td>"
                f"<th>entity types with a node relation</th>"
                f"<td class='mono'>{len(s.type_table())}</td>"
                f"<th>spine rows</th><td class='mono'>{len(s.spine())}</td></tr></table>"]
        diverge = s.types_only_in_the_export()
        if diverge:
            rows.append(
                f"<div class='banner stop'><b>A TYPE WITH NO PER-TYPE RELATION.</b> "
                f"{len(diverge)} entity type(s) are in the GraphML export of this coordinate and "
                f"in NO per-type Parquet file: {_e(diverge)}. On the shipped full-scale artefacts "
                f"that is <code>certificate</code>, and <b>the estate is not missing anything</b>: "
                f"every selected row for that type is a retract, so no certificate has a "
                f"<code>present</code> node and all 7,200 of them live in "
                f"<code>nodes/ghosts.parquet</code>. What IS worth a reader's attention is the "
                f"shape: <b>the per-type files hold only <code>present</code> nodes "
                f"(960,648 of 995,727)</b>, so a client that resolves the type and reads that "
                f"file loses every dead entity of that type while its count, which comes from the "
                f"glob, stays right. This site reads both.</div>")
        ghost_types = s.ghost_types()
        rows.append(f"<p class='small'>Types whose entities are in this estate only as "
                    f"<code>expected_dead</code> ghosts: "
                    f"{_e(ghost_types) if ghost_types else 'none'}. "
                    f"<code>nodes/ghosts.parquet</code> holds "
                    f"{s.con.execute(f'SELECT count(*) FROM {s.ghosts()}').fetchone()[0]:,} of "
                    f"them, and it is inside the node glob, so a count over the glob is right "
                    f"while a per-type enumeration is short unless the ghosts relation is read "
                    f"too.</p>")
        if self.scope["kind"] == "window":
            rows.append(
                f"<p class='small'>The change set is the corpus rows whose "
                f"<code>system_from</code> is in "
                f"<code>({_e(self.scope['s1'])}, {_e(self.scope['s2'])}]</code>. The interval is "
                f"HALF-OPEN, the corpus is the authority, and a diff of two snapshots is not used "
                f"&mdash; a snapshot diff is blind to exactly the retroactive corrections the twin "
                f"holds.</p>")
        #: **The index's own navigation links are RECORDED, not just rendered.** The first draft
        #: emitted them as literal `<a href>` and the census walked only the links it had recorded,
        #: so `reachable_from_index` came out as **1** and every one of the other 33,444 pages was
        #: reported as an orphan -- a census that cannot see the entry point's own links cannot
        #: compute reachability, and a reachability figure computed from a partial graph is worse
        #: than none because it looks like a measurement.
        nav = [("changed.html", "the changelog")]
        nav += [(n, f"changelog page {n.split('-')[1].split('.')[0]} of "
                   f"{len(self._index_changelog_pages) + 1}")
                for n in self._index_changelog_pages]
        nav += [("diff.html", "the As-Of diff"),
                ("site.json", "this site's manifest"),
                ("layout/estate/envelope.json", "the estate layout scope")]
        rows.append("<h2>where to go</h2><p>"
                    + " &middot; ".join(
                        f"<a href='{_e(href)}'>{_e(label)}</a>"
                        for href, label in nav if href != "diff.html" or with_diff_here)
                    + "</p>")
        for href, _label in nav:
            if href == "diff.html" and not with_diff_here:
                continue
            self.links.append(("index.html", href, False))
        rows.append("<h2>the estate's declared spine, and why it is the facet list</h2>"
                    "<p class='small'>38 rows, byte-identical at every corpus size. Faceting a "
                    "372,093-neighbour hub by RELATIONSHIP type does nothing &mdash; the "
                    "organization emits exactly one, <code>contains</code>. Faceting by TARGET TYPE "
                    "splits it into 26, and those types are the spine.</p><table>")
        for row in s.spine():
            rows.append(f"<tr><td class='mono'>{_e(row['type_name'])}</td>"
                        f"<td class='mono'>{_e(row.get('parent'))}</td>"
                        f"<td class='small'>{_e(row.get('origin'))}</td></tr>")
        rows.append("</table>")
        self._write("index.html", "the estate", "\n".join(rows))

    # -- the changelog ------------------------------------------------------------------------------
    def _changed(self, found: dict[str, Any], limit: int = CHANGELOG_ROWS) -> None:
        """The changelog, PAGED, and paged for a reason that is a finding rather than a limit.

        The first draft rendered the first 5,000 of 36,068 changed assertions on one page and
        reported **5,100 entity pages as orphans** -- because the only link into most of the
        change set's entity pages was a changelog row that was not on the page. That is not a
        cosmetic defect: an orphan page is a page a reader cannot arrive at, so the site had 5,100
        pages that existed and were unfindable, and the census was right to complain.

        The fix is not to render 36,068 rows on one page. It is to emit ``changed.html``,
        ``changed-2.html``, ... with prev/next, so that **every changed row is on some page and
        every entity in the scope is reachable from the index** -- which is the property the census
        is there to check. At 1M a 30-day window is 8 pages; the whole 18-month window is 1,517,371
        assertions and 304 pages, and that is the point at which a reader should use the substrate.
        """
        rows = self.changed_relationships(self.scope)
        by_type: dict[str, int] = {}
        for r in rows:
            by_type[r["relationship_type"]] = by_type.get(r["relationship_type"], 0) + 1
        pages = max(1, (len(rows) + limit - 1) // limit)
        for page_no in range(1, pages + 1):
            start = (page_no - 1) * limit
            chunk = rows[start:start + limit]
            name = "changed.html" if page_no == 1 else f"changed-{page_no}.html"
            title = (f"<h1>what moved &mdash; {len(rows):,} changed relationship assertions</h1>")
            body = [title,
                    f"<p class='small'>page {page_no} of {pages}, rows "
                    f"{start + 1:,}&ndash;{start + len(chunk):,} of {len(rows):,}. Newest first; "
                    f"the sort key is "
                    f"<code>(system_from DESC, relationship_type, from_entity_id, "
                    f"to_entity_id)</code>, all four declared, so the order is reproducible rather "
                    f"than incidental.</p>"
                    f"<p class='small'>By relationship type, over the whole window: "
                    + " &middot; ".join(f"{_e(k)} ({v:,})" for k, v in
                                        sorted(by_type.items(), key=lambda kv: -kv[1])) + "</p>",
                    "<table><tr><th>learned at (system_from)</th><th>relationship</th><th>op</th>"
                    "<th>from</th><th>to</th></tr>"]
            for r in chunk:
                body.append(
                    f"<tr><td class='small mono'>{_e(r['system_from'])}</td>"
                    f"<td class='mono'>{_e(r['relationship_type'])}</td>"
                    f"<td class='small'>{_e(r['operation'])}</td>"
                    f"<td class='mono'>"
                    f"{self._entity_link(r['from_entity_id'], name, '.html')}</td>"
                    f"<td class='mono'>"
                    f"{self._entity_link(r['to_entity_id'], name, '.html')}</td></tr>")
            body.append("</table>")
            nav = []
            if page_no > 1:
                prev_name = "changed.html" if page_no == 2 else f"changed-{page_no - 1}.html"
                nav.append(f"<a href='{prev_name}'>&larr; newer</a>")
            if page_no < pages:
                nav.append(f"<a href='changed-{page_no + 1}.html'>older &rarr;</a>")
            if nav:
                body.append(f"<p>{' &middot; '.join(nav)}</p>")
                for i, href in enumerate([n.split("'")[1] for n in nav]):
                    self.links.append((name, href, False))
            self._write(name, f"what moved, page {page_no}", "\n".join(body))
        for page_no in range(2, pages + 1):
            self.links.append(("index.html", f"changed-{page_no}.html", False))
        #: The index's own link is to page 1; the rest are recorded so the walk can reach them, and
        #: the index page PRINTS them rather than hiding the fact that the changelog is 8 pages.
        if pages > 1:
            self._index_changelog_pages = [f"changed-{n}.html" for n in range(2, pages + 1)]
        else:
            self._index_changelog_pages = []

    # -- entity pages ---------------------------------------------------------------------------------
    def _bulk_reads(self, ids: Sequence[str], backlink_rows: int) -> dict[str, Any]:
        """Every read the scope needs, in BULK, once.

        The first draft asked per entity: 35,336 point lookups on the node relation (1.15 ms each,
        41 s -- survivable), 70,672 edge queries (12-18 ms each, 18 minutes) and 35,336 reads of
        the 14.56 MB estate frame (72 ms each, **42 minutes**). The build did not finish. All three
        are the same mistake: **a cost that is a function of the scope rather than of the work**,
        which is the shape this repository calls "a stage that holds what it does not read".

        So: attributes by type in chunks, degrees by ``GROUP BY`` over the scope's ids in both
        directions, and the edge PAGES by one windowed pass per direction. The window function is
        what makes the page bounded -- ``row_number() <= backlink_rows`` per entity -- so the output
        is O(sum of min(degree, page)) and never O(sum of degree), which is what keeps the
        organization's 372,093 out-edges from being materialised in order to show 200 of them.
        """
        con = self.sub.con
        out: dict[str, Any] = {"attributes": {}, "types": {}, "ghosts": {},
                                "degrees": {"out": {}, "in": {}}, "pages": {"out": {}, "in": {}}}
        CHUNK = 20_000
        by_type: dict[str, list[str]] = {}
        for entity_id in ids:
            by_type.setdefault(VSubstrate.entity_type_from_id(entity_id), []).append(entity_id)
        for etype, mine in sorted(by_type.items()):
            if not self.sub.has_type(etype):
                continue
            cols = self.sub.columns_of(etype)
            proj = self.sub.pinned_projection(etype)
            for start in range(0, len(mine), CHUNK):
                chunk = mine[start:start + CHUNK]
                marks = ",".join("?" for _ in chunk)
                for row in con.execute(
                        f"{proj} WHERE entity_id IN ({marks})", chunk).fetchall():
                    rec = dict(zip(cols, row))
                    out["attributes"][rec["entity_id"]] = rec
                    out["types"][rec["entity_id"]] = etype
        #: **The GHOSTS relation, which the first draft did not read.** The per-type Parquet files
        #: hold only `present` nodes -- 960,648 of 995,727 -- and `nodes/ghosts.parquet` holds the
        #: other 35,079 as `expected_dead`, and it is the only place the substrate keeps them. A
        #: build that read the type files alone produced **1,894 pages of 35,336 that did not
        #: exist** while the changelog linked to every one of them: a false all-clear with the
        #: count right and the list short, which is the most expensive shape of it.
        ghost_cols = self.sub.columns_of("ghosts")
        for start in range(0, len(ids), CHUNK):
            chunk = ids[start:start + CHUNK]
            marks = ",".join("?" for _ in chunk)
            for row in con.execute(
                    f"{self.sub.pinned_projection('ghosts')} WHERE entity_id IN ({marks})",
                    chunk).fetchall():
                rec = dict(zip(ghost_cols, row))
                out["ghosts"][rec["entity_id"]] = rec
                out["types"].setdefault(rec["entity_id"], rec["entity_type"])
        for direction, own, other in (("out", "from_entity_id", "to_entity_id"),
                                      ("in", "to_entity_id", "from_entity_id")):
            rel = self.sub.edges_by_src() if direction == "out" else self.sub.edges_by_dst()
            for start in range(0, len(ids), CHUNK):
                chunk = ids[start:start + CHUNK]
                marks = ",".join("?" for _ in chunk)
                for entity_id, degree in con.execute(
                        f"SELECT {own}, count(*) FROM {rel} WHERE {own} IN ({marks}) "
                        f"GROUP BY 1", chunk).fetchall():
                    out["degrees"][direction][entity_id] = degree
                for entity_id, rt, oid, ts in con.execute(
                        f"SELECT {own}, relationship_type, {other}, target_state FROM ("
                        f"  SELECT {own}, relationship_type, {other}, target_state,"
                        f"         row_number() OVER (PARTITION BY {own}"
                        f"                            ORDER BY relationship_type, {other}) rn"
                        f"    FROM {rel} WHERE {own} IN ({marks})"
                        f") WHERE rn <= {int(backlink_rows)}", chunk).fetchall():
                    out["pages"][direction].setdefault(entity_id, []).append(
                        {"relationship_type": rt, "other": oid, "target_state": ts})
        return out

    def _entities(self, found: dict[str, Any], backlink_rows: int) -> None:
        ids = found["entities"]
        bulk = self._bulk_reads(ids, backlink_rows)
        self._positions = self.sub.estate_positions(ids)
        for entity_id in ids:
            self._entity_page(entity_id, bulk, backlink_rows)

    def _entity_page(self, entity_id: str, bulk: dict[str, Any], backlink_rows: int) -> None:
        rel_path = f"entity/{self._slug(entity_id)}"
        page = rel_path + ".html"
        node = bulk["attributes"].get(entity_id)
        ghost = bulk["ghosts"].get(entity_id)
        etype = bulk["types"].get(entity_id, VSubstrate.entity_type_from_id(entity_id))
        if node is None and ghost is None:
            #: The substrate has never heard of this id, and the changelog named it anyway. That is
            #: a genuine broken back-link and it is COUNTED as one. A page is deliberately not
            #: written to make a broken link look resolved: that substitution is the exact thing
            #: this package exists to refuse, and a site that papers over its own dead links is
            #: worse than one that names them.
            self._broken.append((page, f"no node and no ghost for {entity_id!r} of type {etype!r}"))
            return
        state = node.get("node_state") if node else ghost.get("node_state")
        rows = [f"<h1 class='mono'>{_e(entity_id)}</h1>",
                f"<p class='small'><a href='../index.html'>the estate</a> &middot; "
                f"<a href='../changed.html'>the changelog</a> &middot; "
                f"node_state <span class='pill'>{_e(state)}</span></p>"]
        pos = self._positions.get(entity_id)
        if pos:
            rows.append(f"<p class='small'>home position in the <code>estate</code> layout scope: "
                        f"ring {_e(pos[2])}, sector {_e(pos[3])}, ({_e(pos[0])}, "
                        f"{_e(pos[1])}). The position belongs to the SCOPE, not to this node, "
                        f"which is why it is a relation and not an attribute.</p>")
        rows.append("<h2>attributes, as of this coordinate</h2>")
        if node is None:
            #: A dead entity has an end instant, an end's source, and NOTHING ELSE. Showing it
            #: attributes would be inventing them; reporting it as absent would be a lie about the
            #: estate, because it is right here in `nodes/ghosts.parquet`.
            rows.append("<div class='banner'><b>This entity has no attributes at this "
                        "coordinate.</b> It is an <code>expected_dead</code> node, so it lives in "
                        "<code>nodes/ghosts.parquet</code> and the materialiser wrote no per-type "
                        "row for it. What the twin knows is when it ended and what said so:"
                        "</div><table>")
            for k, v in ghost.items():
                rows.append(f"<tr><th>{_e(k)}</th><td class='mono'>{_e(v)}</td></tr>")
            rows.append("</table>")
            if not self.sub.has_type(etype):
                rows.append(f"<div class='banner warn'><b>And its TYPE has no per-type relation "
                            f"at all.</b><p>{_e(_attributes_absent_reason(etype))}</p></div>")
        else:
            rows.append("<table>")
            for k, v in node.items():
                rows.append(f"<tr><th>{_e(k)}</th><td class='mono'>{_e(v)}</td></tr>")
            rows.append("</table>")
        for direction, label in (("out", "out-relationships"), ("in", "back-links")):
            total = bulk["degrees"][direction].get(entity_id, 0)
            page_rows = bulk["pages"][direction].get(entity_id, [])
            if total == 0:
                rows.append(f"<h2>{label}</h2><p class='small'>none.</p>")
                continue
            rows.append(f"<h2>{label} &mdash; {total:,}</h2>")
            if total > len(page_rows):
                rows.append(
                    f"<div class='banner warn'><b>{total:,} in total; {len(page_rows)} shown.</b> "
                    f"The full set is not on this page and this page does not pretend to be it. A "
                    f"page showing 200 of 372,093 and saying nothing asserts a list of 200.</div>")
            rows.append("<table><tr><th>relationship</th><th>target_state</th><th>other</th></tr>")
            for e in page_rows:
                rows.append(f"<tr><td class='mono'>{_e(e['relationship_type'])}</td>"
                            f"<td class='small'>{_e(e['target_state'])}</td>"
                            f"<td class='mono'>"
                            f"{self._entity_link(e['other'], page, '.html')}</td></tr>")
            rows.append("</table>")
        self._write(page, entity_id, "\n".join(rows))

    # -- the diff ------------------------------------------------------------------------------------
    def _diff(self, s1: str, s2: str) -> None:
        """The As-Of diff, and a verdict with three values and no fourth.

        The two diffs read different files, so they cannot be conflated: the ESTATE diff is corpus
        rows and the MODEL diff is the rendered schema graphs, and the MODEL diff contains no estate
        row ever. The three verdicts of record are THE ESTATE, THE MODEL and BOTH; NEITHER is a
        legitimate answer here and is **not** a fourth verdict, because it says the two coordinates
        are the same question and the same estate.

        **And the aggregates are computed PER VIEW, which is a limit rather than a preference.**
        ``check_versioning.estate_diff`` builds one ``UNION ALL`` over all 42 entity views, and at
        1M that raises ``OutOfMemoryException: could not allocate block of size 30.5 MiB
        (1008.5 MiB/1.0 GiB used)`` against the fold's own 1 GiB ceiling. ``check_versioning.py`` is
        not this package's to edit, so the diff page runs a per-view executor and ``check_viewer``'s
        criterion compares the two **where both can run** -- on the small corpus -- and requires
        them to agree to the row. Two executors, one meaning, D49's arrangement; and the one place
        they cannot be compared is named on the page rather than hidden.
        """
        self.open()
        ed, estate_rows = self._diff_per_view("entity", s1, s2)
        rd, relationship_rows = self._diff_per_view("relationship", s1, s2)
        reference = self._reference_aggregates(s1, s2)
        history = check_versioning.load_history()
        k1 = check_versioning.resolve_version(history, s1)
        k2 = check_versioning.resolve_version(history, s2)
        estate_changed = bool(ed) or bool(rd)
        model_changed = self._model_changed(k1, k2)
        if estate_changed and model_changed:
            verdict = "BOTH"
        elif estate_changed:
            verdict = "THE ESTATE"
        elif model_changed:
            verdict = "THE MODEL"
        else:
            verdict = "NEITHER"
        body = [f"<h1>the As-Of diff &mdash; {_e(s1[:10])} to {_e(s2[:10])}</h1>",
                f"<div class='banner'><b>VERDICT: {verdict}</b> &mdash; a computation over two "
                f"separate diffs. estate_changed={str(estate_changed).lower()}, "
                f"model_changed={str(model_changed).lower()}.</div>",
                "<h2>1. the ESTATE diff</h2><p class='small'>The corpus rows whose "
                f"<code>system_from</code> is in <code>({_e(s1)}, {_e(s2)}]</code>. Half-open: S1 is "
                "excluded, S2 is included. Read from the corpus and never by diffing two snapshots, "
                "because a snapshot diff is blind to the retroactive corrections the twin holds."
                "</p>"
                f"<p class='small'>Computed one view at a time. "
                f"{_e(reference['note'])}</p>"]
        if not ed and not rd:
            body.append("<p class='small'>empty &mdash; the twin learned nothing in this interval, "
                        "so there is no estate change to report and whatever the model diff says is "
                        "the whole of it.</p>")
        if ed:
            body.append("<table><tr><th>type</th><th>rows</th><th>first learned</th>"
                        "<th>last learned</th></tr>")
            for r in ed:
                body.append(f"<tr><td class='mono'>{_e(r['key'])}</td>"
                            f"<td class='mono'>{r['rows']:,}</td>"
                            f"<td class='small mono'>{_e(r['first_system_from'])}</td>"
                            f"<td class='small mono'>{_e(r['last_system_from'])}</td></tr>")
            body.append("</table>")
        if rd:
            body.append("<table><tr><th>edge</th><th>rows</th></tr>")
            for r in rd:
                body.append(f"<tr><td class='mono'>{_e(r['key'])}</td>"
                            f"<td class='mono'>{r['rows']:,}</td></tr>")
            body.append("</table>")
        body.append("<h2>2. the MODEL diff</h2><p class='small'>K = f(S). Read from "
                    "<code>schema/schema_versions.json</code>; contains no estate row ever.</p>"
                    f"<table><tr><th></th><th>S1 = {_e(s1)}</th><th>S2 = {_e(s2)}</th></tr>"
                    f"<tr><th>schema version in force</th>"
                    f"<td class='mono'>{_e(k1['schema_version'])}</td>"
                    f"<td class='mono'>{_e(k2['schema_version'])}</td></tr>"
                    f"<tr><th>content digest</th>"
                    f"<td class='mono'>{_e(k1.get('content_digest'))}</td>"
                    f"<td class='mono'>{_e(k2.get('content_digest'))}</td></tr></table>")
        if model_changed:
            body.append("<pre class='mono small'>"
                        + _e(json.dumps(self._model_delta(k1, k2), indent=2)[:2000]) + "</pre>")
        else:
            body.append("<p class='small'>the model did not change across this boundary: the two "
                        "content digests are identical.</p>")
        self._write("diff.html", "the As-Of diff", "\n".join(body))
        self.diff_detail = {
            "s1": s1, "s2": s2, "estate_changed": estate_changed, "model_changed": model_changed,
            "verdict": verdict,
            "estate_rows": estate_rows, "relationship_rows": relationship_rows,
            "check_versioning_reference": reference,
        }

    def _diff_per_view(self, kind: str, s1: str, s2: str) -> tuple[list[dict], int]:
        """The change set's per-type census, one view at a time, and the total.

        The key is the VIEW NAME, which is the relation's name and therefore its type under D21's
        scope-partitioned layout -- read as a name rather than inferred from a file name, because a
        file name is a convention and a relation that carried two types would be counted under
        the wrong name.

        **``facts`` is EXCLUDED, and excluding it is not a preference -- it is the correction of a
        defect this module inherited by importing a view list.** ``check_versioning.entity_views``
        returns every view with an ``entity_type`` column, and on a corpus opened by
        ``as_of.open_corpus`` that list is **43 names and one of them is ``facts``**, the fold's own
        union of every entity row. Summing a per-type count over that list counts every type twice.

        Measured, on ``slice/corpus`` over (2026-09-01, 2026-09-26], truth 144 entity rows:

        ==========================  ==========
        summed over the 42 type views  144
        summed over all 43 views        288
        ``check_versioning.estate_diff`` 288, and it returns **38 rows for 19 types** -- every
        type listed TWICE, so a table built from it prints every type twice
        ==========================  ==========

        ``check_versioning``'s own suite does not see it, because its ``open_corpus()`` never
        creates ``facts``. And the doubling is invisible in the verdict -- a duplicate list is
        still non-empty, so ``estate_changed`` is unchanged -- **which is why it survived: the one
        number the verdict depends on cannot tell.**
        """
        self.open()
        all_views = (check_versioning.entity_views(self.corpus.con) if kind == "entity"
                     else check_versioning.relationship_views(self.corpus.con))
        views = [v for v in all_views if v not in NOT_A_TYPE_VIEWS]
        out: list[dict] = []
        total = 0
        for view in views:
            if kind == "entity":
                row = self.corpus.con.execute(
                    f'SELECT count(*), min(system_from), max(system_from) FROM "{view}" '
                    f"WHERE {CHANGE_PREDICATE}", [s1, s2]).fetchone()
            else:
                row = self.corpus.con.execute(
                    f'SELECT count(*), min(system_from) FROM "{view}" WHERE {CHANGE_PREDICATE}',
                    [s1, s2]).fetchone()
            if not row or not row[0]:
                continue
            total += row[0]
            out.append({"key": view, "rows": row[0],
                        "first_system_from": _as_instant(row[1]),
                        "last_system_from": _as_instant(row[2]) if kind == "entity" else None})
        out.sort(key=lambda r: r["key"])
        return out, total

    def _views_excluded_as_not_a_type(self) -> list[str]:
        """Which views this module refused to count as a type, and why. Reported, not hidden."""
        self.open()
        all_views = check_versioning.entity_views(self.corpus.con)
        return [v for v in all_views if v in NOT_A_TYPE_VIEWS]

    def _reference_aggregates(self, s1: str, s2: str) -> dict[str, Any]:
        """``check_versioning``'s own aggregates, where they can run, and why when they cannot.

        This is the second executor. Where it runs, ``check_viewer`` compares the two to the row;
        where it does not, this returns the refusal and the reason, and the diff page prints it. A
        second executor that is silently absent is a second executor nobody is checking.
        """
        try:
            ed = check_versioning.estate_diff(self.corpus.con, s1, s2)
            rd = check_versioning.relationship_diff(self.corpus.con, s1, s2)
            return {"status": "ok",
                    "estate_rows": sum(r["rows"] for r in ed),
                    "relationship_rows": sum(r["rows"] for r in rd),
                    "note": "The reference executor, `check_versioning.estate_diff` and "
                            "`relationship_diff`, ran, and its numbers are these."}
        except Exception as exc:                            # noqa: BLE001
            return {"status": "not_run",
                    "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:140]}",
                    "note": "The reference executor, `check_versioning.estate_diff`, builds one "
                            "UNION ALL over all 42 entity views and at 1M that raises "
                            "OutOfMemoryException against the fold's own 1 GiB ceiling. It is "
                            "reported as not_run rather than replaced silently, and check_viewer "
                            "compares the two executors on the small corpus where both run."}


    def _model_delta(self, k1: dict, k2: dict) -> dict:
        try:
            g1 = check_versioning.render_graph(int(k1["schema_version"]))
            g2 = check_versioning.render_graph(int(k2["schema_version"]))
            return check_versioning.model_diff(g1, g2)
        except Exception as exc:                            # noqa: BLE001
            return {"not_run": f"{type(exc).__name__}: {exc}"}

    def _model_changed(self, k1: dict, k2: dict) -> bool:
        d = self._model_delta(k1, k2)
        return bool(d) and not check_versioning.model_diff_is_empty(d)

    # -- the manifest -------------------------------------------------------------------------------
    def _site_json(self, found: dict[str, Any], started: float,
                   with_diff: tuple[str, str] | None, backlink_rows: int) -> None:
        c = self.sub.coordinate
        record = {
            "site_version": SITE_VERSION,
            "scope": self.scope,
            "coordinate": {"valid": c["valid"], "system": c["system"],
                           "class": c.get("coordinate_class")},
            "estate_state": self.sub.estate_state,
            "valid_time_window": self.sub.valid_time_window,
            "corpus_fingerprint": self.sub.corpus_fingerprint,
            "substrate_version": self.sub.manifest.get("substrate_version"),
            "entities_in_scope": len(self.scope_ids),
            "changed_relationship_rows": found["relationship_rows"],
            "changed_entity_rows": found["entity_rows"],
            "backlink_rows_per_page": backlink_rows,
            "changelog_rows": CHANGELOG_ROWS,
            "types_only_in_the_graphml_export": self.sub.types_only_in_the_export(),
            "diff": self.diff_detail,
            "build_seconds": round(time.perf_counter() - started, 3),
        }
        with open(os.path.join(self.out_dir, "site.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(record, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        self.pages.append("site.json")
        self.site_record = record

    # -- the census, which is the guillotine's input -------------------------------------------------
    def census_report(self, found: dict[str, Any], started: float) -> dict[str, Any]:
        """Walk the recorded link graph and report coverage, broken links and orphans.

        This is the measurement ``check_viewer``'s site criteria compare against, and it is a
        **crawl of what the build actually emitted**, not an assertion about what it meant to emit:
        every link is resolved against the set of files on disk, and reachability is computed by
        following the recorded graph from ``index.html``. A page that exists but cannot be reached
        is an orphan, and it is reported as one.
        """
        generated = {_norm(p) for p in self.pages}
        generated |= {"layout/estate/envelope.json", "layout/estate/positions.parquet"}
        broken: list[str] = []
        for _frm, href, outside in self.links:
            if outside:
                continue
            if _norm(href) not in generated:
                broken.append(href)
        broken.extend(why for _p, why in self._broken)
        adjacency: dict[str, list[str]] = {}
        for frm, href, outside in self.links:
            if not outside:
                adjacency.setdefault(_norm(frm), []).append(_norm(href))
        seen: set[str] = set()
        frontier = ["index.html"]
        while frontier:
            page = frontier.pop()
            if page in seen:
                continue
            seen.add(page)
            frontier.extend(adjacency.get(page, ()))
        infrastructure = {"site.json", "layout/estate/envelope.json",
                          "layout/estate/positions.parquet"}
        orphans = sorted(generated - seen - infrastructure)
        return {
            "site_version": SITE_VERSION,
            "pages": len(self.pages),
            "bytes": self.census_bytes,
            "links_recorded": len(self.links),
            "links_inside": sum(1 for l in self.links if not l[2]),
            "links_declared_outside": sum(1 for l in self.links if l[2]),
            "broken_backlinks": len(broken),
            "broken_sample": broken[:20],
            "reachable_from_index": len(seen),
            "orphan_pages": len(orphans),
            "orphan_sample": orphans[:20],
            "entities_in_scope": len(self.scope_ids),
            "changed_relationship_rows": found["relationship_rows"],
            "build_seconds": round(time.perf_counter() - started, 3),
        }


# ----------------------------------------------------------------------------------- the CLI

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the materialised estate directory")
    ap.add_argument("--schema", required=True, help="the materialised SCHEMA directory")
    ap.add_argument("--corpus", required=True, help="the corpus root")
    ap.add_argument("--out", required=True, help="where the site is written")
    ap.add_argument("--scope", required=True, help="window:<S1>..<S2> | seed:<entity_id> | all")
    ap.add_argument("--diff", help="two instants, S1..S2, for the As-Of diff page")
    ap.add_argument("--backlink-rows", type=int, default=BACKLINK_ROWS)
    ap.add_argument("--changelog-rows", type=int, default=CHANGELOG_ROWS)
    ap.add_argument("--organization", default="acme")
    args = ap.parse_args(argv)
    try:
        scope = parse_scope(args.scope)
    except SiteRefused as exc:
        print(f"REFUSED: {exc.reason}\n  {exc.detail or SITE_REFUSALS[exc.reason]}")
        return 2
    with_diff = None
    if args.diff:
        if ".." not in args.diff:
            print("REFUSED: diff_needs_a_second_as_of\n  --diff wants S1..S2")
            return 2
        s1, s2 = args.diff.split("..", 1)
        for v in (s1, s2):
            if not _is_instant(v):
                print(f"REFUSED: diff_needs_a_second_as_of\n  {v!r} is not an instant "
                      f"(want YYYY-MM-DDTHH:MM:SSZ)")
                return 2
        with_diff = (s1, s2)
    b = SiteBuilder(args.graph, args.schema, args.corpus, args.out, args.organization)
    b._broken = []
    census = b.build(scope, with_diff=with_diff, backlink_rows=args.backlink_rows)
    print(json.dumps(census, indent=2, default=str))
    return 0 if census["broken_backlinks"] == 0 and census["orphan_pages"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
