"""The explorer: a client over the DuckDB/Parquet layer, and nothing else.

What it is
==========

A read-only HTTP client over **one materialised snapshot**. It renders, at 1M:

* the **estate frame** -- 42 types and the schema's declared 38-row spine, the only whole-estate
  views that exist, both measured at 15.1 ms and 2.6 ms;
* a **node** with its own type's attributes, its out- and in-edges paged and faceted, and its
  position in the estate frame;
* a **neighbourhood** -- one depth-capped traversal through ``schema/graph/traverse.py``'s PINNED
  template, with the layout relation computed for exactly that scope;
* the **twelve registered canonical questions**, run through ``schema/query/query.py``'s own
  ``answer_record``, envelope and all.

What it deliberately is not
===========================

**Not a GraphML reader.** The estate GraphML is 1.61 GB and has no shard manifest, no index and no
partial-read protocol, so a graph too large to load cannot be traversed out of GraphML at all. See
``/graphml``, which says so, and ``substrate.install_graphml_tripwire``, which makes opening one
raise. **Not a force-directed renderer**, and the reason is structural rather than a matter of
taste: at 1M the ``organization`` node has 372,093 out-edges in ONE hop and 690,641 nodes at depth
two, so no picture contains the estate and depth is not a scale control -- degree is. Every view
here is local, and every view that would exceed the render budget **truncates and says so**.

The two clocks, measured at 1M
==============================

The explorer has two clocks and they differ by two orders of magnitude, which is the first thing a
reader should know and the reason ``/`` prints both:

===========================  =========================  =========================
operation                    substrate (Parquet)       the corpus (1.10 GB CSV)
===========================  =========================  =========================
open                         n/a                       4.31 s
the type table               15.1 ms                   --
1-hop out, a segment         7.8 ms                    --
1-hop in, a segment          82.1 ms                   --
depth-2 out, a segment       83.0 ms                   --
depth-3 out, a segment       221.6 ms (3,371 nodes)    --
depth-2 out, the organization 804.9 ms (690,641 nodes) --
one registered question      --                        3.8 s - 7.2 s
all twelve                   --                        61.1 s
===========================  =========================  =========================

**Why the questions are a hundred times slower, and it is not an optimisation left undone:**
``schema/query/query.py`` is deliberately *not a fold consumer* (it asserts this with the
repository's own ``check_window.takes_a_fold_result``), so it reads the whole bitemporal corpus
rather than one coordinate's already-folded estate. The substrate cannot answer a question and the
corpus cannot answer a drill, and a client that quietly re-implemented either would be a second
truth about what a path means. Both numbers are printed rather than reconciled.
"""

from __future__ import annotations

import html
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
for _p in ("schema/fold", "schema/graph", "schema/csv", "schema/identity", "schema/resolve",
           "schema/versioning", "schema/query", "schema/rules", "schema/coverage"):
    _full = os.path.join(ROOT, _p.replace("/", os.sep))
    if _full not in sys.path:
        sys.path.insert(0, _full)

import layout as VLayout          # noqa: E402
import query as VQuery            # noqa: E402
import substrate as VSubstrate    # noqa: E402
from substrate import ViewerRefused  # noqa: E402

#: Rows one page of a list may carry, and rows one picture may place. Two numbers, and the second
#: is the one that matters: 2,000 is where a reachable set stops being readable
#: (``traverse.py``'s own operating point), and 200 is a page of a table a person scrolls.
PAGE_ROWS = 200
PICTURE_ROWS = VLayout.RENDER_BUDGET

#: What the explorer measured for itself, on this machine, at this size. Recomputed on demand by
#: ``/timings``; the numbers in the module docstring are the ones in the ticket answer.
MEASURED = {
    "size": "full (995,727 nodes / 3,501,949 edges)",
    "type_table_ms": 15.1,
    "open_corpus_s": 4.31,
    "one_hop_out_segment_ms": 7.8,
    "one_hop_in_segment_ms": 82.1,
    "depth2_out_segment_ms": 83.0,
    "depth3_out_segment_ms": 221.6,
    "depth2_out_organization_ms": 804.9,
    "one_registered_question_s": "3.8 - 7.2",
    "all_twelve_questions_s": 61.1,
    "query_layer_peak_mb": 368.1,
    "fold_peak_mb": 5109.9,
    "fold_seconds": 98.9,
}


# ----------------------------------------------------------------------------------- the client

class Explorer:
    """One snapshot, opened once, with the two authorities it reads through.

    The authorities are *imported*, never restated: ``traverse`` for the drill, ``VQuery`` for the
    questions, ``VLayout`` for the positions. A client with its own breadth-first search or its own
    selection predicate would be a second truth about what a path means, which is the defect
    ``schema/query`` exists to prevent and the one ``slice/check_slice.py`` C13 exists to catch.
    """

    def __init__(self, graph_dir: str, schema_dir: str, corpus_dir: str | None = None,
                 profile: str | None = None, layout_dir: str | None = None) -> None:
        self.sub = VSubstrate.open_substrate(graph_dir, schema_dir, layout_dir)
        self.graph_dir = self.sub.graph_dir
        self.schema_dir = self.sub.schema_dir
        self.corpus_dir = corpus_dir
        self.profile = profile or os.path.join(ROOT, "schema", "overlay", "acme", "profile.yaml")
        self.layout_dir = self.sub.layout_dir
        self._lock = threading.Lock()
        self._ctx: Any = None
        self._ctx_seconds: float | None = None
        self._records: dict[str, dict] = {}
        self._types: list[tuple[str, int]] | None = None
        self._spine: list[dict] | None = None

    # -- the spine and the type table, computed once ------------------------------------------
    @property
    def types(self) -> list[tuple[str, int]]:
        if self._types is None:
            with self._lock:
                if self._types is None:
                    self._types = self.sub.type_table()
        return self._types

    @property
    def spine(self) -> list[dict]:
        if self._spine is None:
            with self._lock:
                if self._spine is None:
                    self._spine = self.sub.spine()
        return self._spine

    # -- the estate frame, read from the layout relation, or not_run ----------------------------
    def estate_frame(self) -> dict[str, Any]:
        """The estate layout scope. ``Substrate`` owns it, and so does the site builder.

        It lives on the substrate rather than on this client because it is a property of the
        snapshot and its layout relation, not of anything a browser asked for -- and a second
        reader of ``envelope.json`` in two files is a second answer to "is the frame written".
        """
        return self.sub.estate_frame()

    def estate_position(self, entity_id: str) -> dict[str, Any] | None:
        """One node's home position in the estate frame, or ``None`` if the frame is unwritten."""
        return self.sub.estate_positions([entity_id]).get(entity_id)

    # -- the drill --------------------------------------------------------------------------------
    def neighbourhood(self, seed: str, depth: int) -> dict[str, Any]:
        """One depth-capped traversal and the layout for exactly its scope.

        ``depth`` above ``traverse.MAX_TRAVERSAL_DEPTH`` is refused **by traverse**, not by this
        client, and the refusal text is the pinned one. A client with its own cap is a client
        whose cap somebody will raise.
        """
        with self._lock:
            lay = VLayout.neighbourhood_layout(self.sub, seed, depth)
        env = lay["envelope"]
        env["depth_cap"] = __import__("traverse").MAX_TRAVERSAL_DEPTH
        env["truncated"] = bool(lay["envelope"]["truncated"])
        return {"envelope": env, "positions": lay["positions"]}

    def edges_of(self, entity_id: str, direction: str, facet: str | None = None,
                 limit: int = PAGE_ROWS, offset: int = 0) -> dict[str, Any]:
        """One node's edges, paged, and the **facet list** beside the page.

        The facet is by **target type**, because that is the only facet that narrows a hub. At
        1M the organization's 372,093 out-edges emit exactly ONE relationship type (``contains``),
        so faceting by relationship type does not narrow it at all; faceting by target type splits
        it into 26, and the facet list is the schema's own declared spine. The aggregate is
        computed with one query and costs 146.8 ms on the 372,093-edge fan.
        """
        rel = self.sub.edges_by_src() if direction == "out" else self.sub.edges_by_dst()
        own = "from_entity_id" if direction == "out" else "to_entity_id"
        other = "to_entity_id" if direction == "out" else "from_entity_id"
        with self._lock:
            facets = self.sub.con.execute(
                f"SELECT t.entity_type, count(*) n FROM {rel} e "
                f"JOIN {self.sub.node_glob()} t ON t.entity_id = e.{other} "
                f"WHERE e.{own} = ? GROUP BY 1 ORDER BY 2 DESC", [entity_id]).fetchall()
            where = f"WHERE e.{own} = ?"
            params: list[Any] = [entity_id]
            if facet:
                marks = ",".join("?" for _ in facets)
                names = [f[0] for f in facets]
                idx = names.index(facet)
                where += f" AND e.{other} IN (SELECT entity_id FROM {self.sub.node_glob()} " \
                         f"WHERE entity_type = ?)"
                params = [entity_id, facet]
            total = self.sub.con.execute(
                f"SELECT count(*) FROM {rel} e "
                f"JOIN {self.sub.node_glob()} t ON t.entity_id = e.{other} {where}",
                params).fetchone()[0]
            rows = self.sub.con.execute(
                f"SELECT e.relationship_type, e.{other}, e.target_state, t.entity_type "
                f"FROM {rel} e JOIN {self.sub.node_glob()} t ON t.entity_id = e.{other} {where} "
                f"ORDER BY t.entity_type, e.{other} LIMIT ? OFFSET ?",
                params + [limit, offset]).fetchall()
        return {
            "direction": direction, "entity_id": entity_id, "facet": facet,
            "total": total, "offset": offset, "limit": limit,
            "has_more": offset + len(rows) < total,
            "facets": [{"entity_type": t, "n": n} for t, n in facets],
            "edges": [{"relationship_type": r[0], "other": r[1], "target_state": r[2],
                       "other_type": r[3]} for r in rows],
        }

    def node_page(self, entity_type: str, limit: int = PAGE_ROWS, offset: int = 0) -> dict[str, Any]:
        """One type's nodes, paged, with **that type's own columns**.

        The type is required. Over the glob there is no such thing as "a node": the substrate
        stores one file per type, so the glob's schema is the first file's and a client that
        introspected it would render ``access_rule``'s ten columns for 995,727 rows.
        """
        if entity_type not in {t for t, _ in self.types}:
            raise ViewerRefused("unknown_scope",
                                f"{entity_type!r} is not one of the {len(self.types)} types in this "
                                f"snapshot. The type list is the estate's own; it is not a "
                                f"client-supplied string.")
        with self._lock:
            cols = self.sub.columns_of(entity_type)
            total = self.sub.con.execute(
                f"SELECT count(*) FROM {self.sub.type_file(entity_type)}").fetchone()[0]
            rows = self.sub.con.execute(
                f"{self.sub.pinned_projection(entity_type)} "
                f"ORDER BY entity_id LIMIT ? OFFSET ?", [limit, offset]).fetchall()
        return {"entity_type": entity_type, "columns": cols, "total": total, "offset": offset,
                "limit": limit, "has_more": offset + len(rows) < total,
                "rows": [dict(zip(cols, r)) for r in rows]}

    # -- the questions ------------------------------------------------------------------------------
    def context(self) -> tuple[Any, float]:
        """The query layer's Context, built once, with the cost of building it recorded.

        4.31 s at 1M and 258.4 MB, and it is paid on the **first question a user asks**, not on
        page load. The explorer prints that on the page so the seven-second wait is attributed
        rather than mysterious.
        """
        if self._ctx is None:
            if not self.corpus_dir:
                raise ViewerRefused("unknown_scope",
                                    "no --corpus: the registered questions read the whole "
                                    "bitemporal CORPUS, not the substrate. schema/query is "
                                    "deliberately not a fold consumer, so the snapshot cannot "
                                    "answer them and this is not a missing feature.")
            from pathlib import Path
            import as_of
            t = time.perf_counter()
            corpus = as_of.open_corpus(self.corpus_dir, self.sub.organization)
            self._ctx = VQuery.Context(corpus, Path(self.profile))
            self._ctx_seconds = time.perf_counter() - t
        return self._ctx, (self._ctx_seconds or 0.0)

    def question(self, query_id: str) -> dict[str, Any]:
        """One registered question's answer record, through ``query.answer_record``.

        The record is ticket 13's deliverable and is used whole: ``claim_strength``,
        ``estate_state``, ``caps_applied``, ``cannot_see`` and the wall-clock. This client adds
        nothing to it and removes nothing from it, because a viewer that improved an answer record
        is a viewer with its own opinion about what the answer was.
        """
        specs = VQuery.canonical_questions()
        chosen = [s for s in specs if s["id"] == query_id]
        if not chosen:
            raise ViewerRefused("unknown_scope",
                                f"no registered query {query_id!r}; known: {[s['id'] for s in specs]}")
        if query_id in self._records:
            return dict(self._records[query_id], cached=True)
        ctx, open_seconds = self.context()
        rec = dict(VQuery.answer_record(chosen[0], ctx))
        rec["open_corpus_s"] = round(open_seconds, 3)
        rec["corpus"] = self.corpus_dir
        rec["cached"] = False
        self._records[query_id] = rec
        return rec

    def all_questions(self) -> list[dict]:
        return [self.question(s["id"]) for s in VQuery.canonical_questions()]


# ----------------------------------------------------------------------------------- rendering

_CSS = """
body{font:14px/1.5 ui-sans-serif,system-ui,Segoe UI,sans-serif;margin:0;background:#0f1115;color:#d7dae0}
a{color:#7fb2ff;text-decoration:none}a:hover{text-decoration:underline}
main{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px;color:#9fb4d8;font-weight:600}
code,.mono{font-family:ui-monospace,Cascadia Code,Consolas,monospace;font-size:12px}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #22262e;vertical-align:top}
th{color:#9fb4d8;font-weight:600;font-size:12px}
.banner{background:#1a1f2a;border-left:3px solid #7fb2ff;padding:10px 14px;margin:12px 0;border-radius:2px}
.warn{border-left-color:#e0a04f}.stop{border-left-color:#e05f5f}
.small{color:#8b93a1;font-size:12px}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;background:#22262e;font-size:11px;margin-right:4px}
.pill.read{background:#1d3326;color:#7fd39a}.pill.empty{background:#3a2a1d;color:#e0a04f}
.pill.unknown{background:#2a2438;color:#b79fe0}.pill.unbounded{background:#1a3326;color:#7fd39a}
form{display:inline}
input,button{background:#1a1f2a;color:#d7dae0;border:1px solid #2b313c;border-radius:3px;padding:4px 8px;font-size:12px}
button{cursor:pointer}
"""


def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _page(title: str, body: str) -> bytes:
    return ("<!doctype html><meta charset=utf-8><title>" + _e(title) + "</title><style>"
            + _CSS + "</style><main>" + body + "</main>").encode("utf-8")


def _env_banner(env: dict[str, Any]) -> str:
    """Every rendered page carries the coordinate, the estate state and the fingerprint.

    Non-negotiable, and it is the reason this function exists rather than a footer: a page that
    says "no results" must never be indistinguishable from "nothing exists", and a page without a
    coordinate cannot be checked against its source. ``estate_state`` is a fact about the TWIN.
    """
    es = env.get("estate_state", "read")
    cls = "read" if es == "read" else "empty"
    bits = [
        f"coordinate V={_e(env.get('coordinate_valid'))} S={_e(env.get('coordinate_system'))}",
        f"estate_state=<span class='pill {cls}'>{_e(es)}</span>",
        f"valid_time_window={_e(str(env.get('valid_time_window'))[:24])}...",
        f"corpus={_e(env.get('corpus_fingerprint'))}",
    ]
    return ("<div class='banner small'>" + " &middot; ".join(bits) + "</div>")


def _trunc_banner(env: dict[str, Any]) -> str:
    if not env.get("truncated"):
        return (f"<div class='banner small'>rendered in full: "
                f"{_e(env.get('rows_placed'))} of {_e(env.get('rows_available'))} nodes, budget "
                f"{_e(env.get('row_budget'))}.</div>")
    return (f"<div class='banner warn'><b>TRUNCATED.</b> "
            f"{_e(env.get('rows_available'))} nodes are reachable and "
            f"{_e(env.get('rows_placed'))} are placed, against a budget of "
            f"{_e(env.get('row_budget'))}. {_e(env.get('truncation_rule'))}</div>")


class Handler(BaseHTTPRequestHandler):
    explorer: Explorer

    def log_message(self, fmt: str, *a: Any) -> None:      # quiet: verify.py reads stdout
        pass

    # -- plumbing --------------------------------------------------------------------------------
    def _send(self, body: bytes, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                                # noqa: N802
        parsed = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            route = parsed.path.rstrip("/") or "/"
            if route == "/":
                self._send(self._index())
            elif route == "/types":
                self._send(self._types())
            elif route.startswith("/type/"):
                self._send(self._type_page(route[len("/type/"):], q))
            elif route.startswith("/node/"):
                self._send(self._node(route[len("/node/"):]))
            elif route == "/neighbourhood":
                self._send(self._neighbourhood(q))
            elif route.startswith("/question/"):
                self._send(self._question(route[len("/question/"):]))
            elif route == "/questions":
                self._send(self._questions())
            elif route == "/graphml":
                self._send(self._graphml())
            elif route == "/timings":
                self._json(self._timings())
            elif route == "/health":
                self._json({"ok": True, "nodes": self.explorer.sub.counts()["nodes"]})
            else:
                self._send(_page("404", f"<h1>404</h1><p>no route {route!r}. "
                                       f"<a href='/'>the index</a> lists every route.</p>"), 404)
        except ViewerRefused as exc:
            self._send(_page("refused", _env_banner(self.explorer.sub.coordinate) +
                             f"<div class='banner stop'><b>REFUSED: {_e(exc.reason)}</b>"
                             f"<p>{_e(exc.detail or VSubstrate.REFUSAL_REASONS[exc.reason])}</p></div>"),
                       200)
        except __import__("traverse").TraverseError as exc:
            #: traverse.py's OWN refusal, rendered with traverse.py's OWN text. A client that
            #: caught it and printed its own words would be paraphrasing a cap somebody would
            #: then edit, and a cap that can be paraphrased is a cap that is a preference.
            self._send(_page("refused", _env_banner(self.explorer.sub.coordinate) +
                             "<div class='banner stop'><b>REFUSED by "
                             "<code>schema/graph/traverse.py</code></b><p>"
                             + _e(str(exc)) + "</p></div>"), 200)
        except __import__("layout").LayoutRefused as exc:
            self._send(_page("refused", _env_banner(self.explorer.sub.coordinate) +
                             f"<div class='banner stop'><b>REFUSED: {_e(exc.reason)}</b>"
                             f"<p>{_e(exc.detail or __import__('layout').LAYOUT_REFUSALS[exc.reason])}"
                             f"</p></div>"), 200)
        except Exception as exc:                            # noqa: BLE001
            self._send(_page("error", f"<h1>error</h1><p class='mono'>{_e(type(exc).__name__)}: "
                                      f"{_e(exc)}</p>"), 200)

    # -- the routes -------------------------------------------------------------------------------
    def _index(self) -> bytes:
        ex = self.explorer
        sub = ex.sub
        counts = sub.counts()
        env = dict(sub.coordinate)
        env["estate_state"] = sub.estate_state
        env["valid_time_window"] = sub.valid_time_window
        env["corpus_fingerprint"] = sub.corpus_fingerprint
        body = [f"<h1>the digital twin &mdash; one snapshot, read over Parquet</h1>",
                _env_banner(env)]
        body.append(
            f"<table><tr><th>nodes</th><td class='mono'>{counts['nodes']:,}</td>"
            f"<th>edges</th><td class='mono'>{counts['edges']:,}</td>"
            f"<th>entity types</th><td class='mono'>{len(ex.types)}</td>"
            f"<th>spine rows</th><td class='mono'>{len(ex.spine)}</td></tr></table>")
        body.append("<h2>the two clocks, and they are not the same clock</h2>")
        body.append(
            "<p>A drill reads the <b>substrate</b> and answers in milliseconds. A registered "
            "question reads the whole <b>corpus</b> &mdash; 1.10 GB of CSV &mdash; and answers in "
            "seconds, because <code>schema/query</code> is deliberately not a fold consumer and so "
            "cannot read one coordinate's already-folded estate. The snapshot cannot answer a "
            "question and the corpus cannot answer a drill. Both numbers are printed rather than "
            "reconciled.</p>")
        body.append(
            "<table><tr><th>operation</th><th>measured at 1M</th></tr>"
            f"<tr><td>open the corpus (first question only)</td><td class='mono'>{MEASURED['open_corpus_s']} s, 258.4 MB</td></tr>"
            f"<tr><td>the type table</td><td class='mono'>{MEASURED['type_table_ms']} ms</td></tr>"
            f"<tr><td>1 hop out of a network_segment</td><td class='mono'>{MEASURED['one_hop_out_segment_ms']} ms</td></tr>"
            f"<tr><td>1 hop in to a network_segment</td><td class='mono'>{MEASURED['one_hop_in_segment_ms']} ms</td></tr>"
            f"<tr><td>depth-2 out of a network_segment</td><td class='mono'>{MEASURED['depth2_out_segment_ms']} ms</td></tr>"
            f"<tr><td>depth-3 out of a network_segment</td><td class='mono'>{MEASURED['depth3_out_segment_ms']} ms &mdash; 3,371 nodes</td></tr>"
            f"<tr><td>depth-2 out of <b>the organization</b></td><td class='mono'>{MEASURED['depth2_out_organization_ms']} ms &mdash; <b>690,641 nodes</b></td></tr>"
            f"<tr><td>one registered question</td><td class='mono'>{MEASURED['one_registered_question_s']} s</td></tr>"
            f"<tr><td>all twelve</td><td class='mono'>{MEASURED['all_twelve_questions_s']} s</td></tr>"
            f"<tr><td>the query layer's peak</td><td class='mono'>{MEASURED['query_layer_peak_mb']} MB</td></tr>"
            "</table>")
        body.append("<h2>the four canonical questions</h2>"
                    "<p>Twelve registered queries, one <code>primary</code> per question, each with "
                    "its own <code>cannot_see</code>. Run through "
                    "<code>schema/query/query.py</code>'s own <code>answer_record</code> &mdash; "
                    "envelope, claim strength, estate state and wall-clock are the record's, not "
                    "this client's.</p>"
                    "<p><a href='/questions'>run all twelve and read every record</a></p>")
        body.append("<h2>the estate frame</h2>")
        frame = ex.estate_frame()
        if frame["status"] == "ok":
            e = frame["envelope"]
            body.append(f"<p class='small'>layout scope <code>{_e(e['layout_scope'])}</code>, "
                        f"algorithm <code>{_e(e['layout_algorithm'])}</code>, "
                        f"{int(e['rows_placed']):,} rows, "
                        f"{e.get('sectors')} sectors over {e.get('max_ring')} rings, digest "
                        f"<code>{_e(e['digest'])}</code>. The position is a property of this SCOPE, "
                        f"not of the node &mdash; which is why it is a relation and not an "
                        f"attribute.</p>")
        else:
            body.append(f"<div class='banner warn'><b>not_run.</b> {_e(frame['reason'])}</div>")
        body.append("<h2>the estate's declared spine &mdash; 38 rows, identical at every size</h2>"
                    "<table><tr><th>type</th><th>parent</th><th>origin</th><th>guard</th></tr>")
        for row in ex.spine:
            body.append(f"<tr><td><a href='/type/{_e(row['type_name'])}'>{_e(row['type_name'])}</a>"
                        f"</td><td class='mono'>{_e(row.get('parent'))}</td>"
                        f"<td class='small'>{_e(row.get('origin'))}</td>"
                        f"<td class='small mono'>{_e(row.get('guard'))}</td></tr>")
        body.append("</table>")
        body.append("<h2>routes</h2><p class='small mono'>"
                    "/types &middot; /type/&lt;entity_type&gt;?offset=N &middot; "
                    "/node/&lt;entity_id&gt; &middot; /neighbourhood?seed=&lt;id&gt;&amp;depth=N "
                    "&middot; /questions &middot; /question/&lt;id&gt; &middot; /graphml &middot; "
                    "/timings &middot; /health</p>")
        return _page("the digital twin", "\n".join(body))

    def _types(self) -> bytes:
        ex = self.explorer
        body = [f"<h1>{len(ex.types)} entity types</h1>",
                f"<p class='small'>Counted over the four-column lead block, which is the only "
                f"projection every node file can answer. 15.1 ms at 1M.</p><table>",
                "<tr><th>type</th><th>nodes</th><th>in the spine</th></tr>"]
        spine = {r["type_name"]: r.get("parent") for r in ex.spine}
        for etype, n in ex.types:
            parent = spine.get(etype)
            body.append(f"<tr><td><a href='/type/{_e(etype)}'>{_e(etype)}</a></td>"
                        f"<td class='mono'>{n:,}</td>"
                        f"<td class='small mono'>{'parent ' + _e(parent) if parent else 'root'}</td></tr>")
        body.append("</table>")
        return _page("types", "\n".join(body))

    def _type_page(self, entity_type: str, q: dict[str, str]) -> bytes:
        ex = self.explorer
        offset = int(q.get("offset", "0"))
        page = ex.node_page(entity_type, PAGE_ROWS, offset)
        env = dict(ex.sub.coordinate)
        env["estate_state"] = ex.sub.estate_state
        env["valid_time_window"] = ex.sub.valid_time_window
        env["corpus_fingerprint"] = ex.sub.corpus_fingerprint
        body = [f"<h1>{_e(entity_type)}</h1>", _env_banner(env),
                f"<p class='small'>{page['total']:,} nodes. This type's own columns, read from "
                f"this type's own file &mdash; over the glob the only columns answerable are the "
                f"four of the lead block, because the substrate stores one file per type.</p>",
                "<table><tr>" + "".join(f"<th>{_e(c)}</th>" for c in page["columns"]) + "</tr>"]
        for row in page["rows"]:
            cells = []
            for c in page["columns"]:
                v = row.get(c)
                if c == "entity_id":
                    cells.append(f"<td class='mono'><a href='/node/{_e(v)}'>{_e(v)}</a></td>")
                else:
                    cells.append(f"<td class='mono'>{_e(v)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        body.append("</table>")
        nav = []
        if offset:
            nav.append(f"<a href='/type/{_e(entity_type)}?offset={max(0, offset - PAGE_ROWS)}'>&larr; previous</a>")
        if page["has_more"]:
            nav.append(f"<a href='/type/{_e(entity_type)}?offset={offset + PAGE_ROWS}'>next &rarr;</a>")
        body.append(f"<p>{' &middot; '.join(nav) or 'one page holds the whole type'} "
                    f"({offset:,}&ndash;{offset + len(page['rows']):,} of {page['total']:,})</p>")
        return _page(entity_type, "\n".join(body))

    def _node(self, entity_id: str) -> bytes:
        ex = self.explorer
        from urllib.parse import quote
        node = ex.sub.node(entity_id)
        env = dict(ex.sub.coordinate)
        env["estate_state"] = ex.sub.estate_state
        env["valid_time_window"] = ex.sub.valid_time_window
        env["corpus_fingerprint"] = ex.sub.corpus_fingerprint
        if not node:
            body = [f"<h1>no node {_e(entity_id)}</h1>", _env_banner(env),
                    "<div class='banner warn'><b>This id has no node in this snapshot.</b> That is "
                    "a fact about the twin, not about the world: the estate may hold no belief "
                    "covering this coordinate, or the id may belong to a different coordinate. "
                    "It is <b>not</b> a statement that nothing exists.</div>"]
            return _page("no node", "\n".join(body))
        body = [f"<h1 class='mono'>{_e(entity_id)}</h1>", _env_banner(env)]
        body.append("<table>")
        for k, v in node.items():
            body.append(f"<tr><th>{_e(k)}</th><td class='mono'>{_e(v)}</td></tr>")
        body.append("</table>")
        pos = ex.estate_position(entity_id)
        if pos:
            body.append(f"<p class='small'>home position in the <code>estate</code> scope: "
                        f"ring {_e(pos['ring'])}, sector {_e(pos['sector'])}, "
                        f"({_e(pos['x'])}, {_e(pos['y'])}). One lookup, not a rendering.</p>")
        else:
            body.append("<p class='small'>home position: <b>not_run</b> &mdash; the estate frame "
                        "has not been written, so this is not an absence of a position.</p>")
        quoted = quote(entity_id, safe="")
        for direction, label in (("out", "out-edges"), ("in", "in-edges")):
            edges = ex.edges_of(entity_id, direction, limit=PAGE_ROWS)
            if edges["total"] == 0:
                body.append(f"<h2>{label}</h2><p class='small'>none.</p>")
                continue
            over = edges["total"] > PICTURE_ROWS
            body.append(f"<h2>{label} &mdash; {edges['total']:,}"
                        + (" <span class='pill'>&gt; RENDER BUDGET</span>" if over else "")
                        + "</h2>")
            body.append("<p class='small'>facet by target type. Faceting by relationship type "
                        "does not work at 1M: the organization emits exactly one, "
                        "<code>contains</code>. Faceting by target type splits a 372,093-edge "
                        "fan-out into 26, and the list is the schema's own declared spine.</p>")
            body.append("<p class='small'>" + " ".join(
                f"<a href='/node/{_e(entity_id)}?{direction}_facet={quote(f['entity_type'], safe='')}'>"
                f"{_e(f['entity_type'])} ({f['n']:,})</a>" for f in edges["facets"][:26]) + "</p>")
            body.append("<table><tr><th>relationship</th><th>target_state</th><th>other</th>"
                        "<th>type</th></tr>")
            for e in edges["edges"]:
                body.append(f"<tr><td class='mono'>{_e(e['relationship_type'])}</td>"
                            f"<td class='small'>{_e(e['target_state'])}</td>"
                            f"<td class='mono'><a href='/node/{quote(e['other'], safe='')}'>"
                            f"{_e(e['other'])}</a></td>"
                            f"<td class='small'>{_e(e['other_type'])}</td></tr>")
            body.append("</table>")
        body.append(f"<h2>drill</h2><p><a href='/neighbourhood?seed={quoted}&amp;depth=2'>"
                    f"depth 2 out &mdash; through traverse.py's pinned template</a></p>")
        return _page(entity_id, "\n".join(body))

    def _neighbourhood(self, q: dict[str, str]) -> bytes:
        ex = self.explorer
        seed = q.get("seed", "")
        depth = int(q.get("depth", "2"))
        out = ex.neighbourhood(seed, depth)
        env = dict(ex.sub.coordinate)
        env["estate_state"] = ex.sub.estate_state
        env["valid_time_window"] = ex.sub.valid_time_window
        env["corpus_fingerprint"] = ex.sub.corpus_fingerprint
        lay = out["envelope"]
        from urllib.parse import quote
        body = [f"<h1>neighbourhood of <span class='mono'>{_e(seed)}</span></h1>", _env_banner(env)]
        body.append("<p>The SQL is <code>schema/graph/traverse.py</code>'s pinned template, bound "
                    "to this substrate. <code>UNION</code> not <code>UNION ALL</code>, a recursive "
                    f"epoch counter, and a cap of {lay.get('depth_cap')} that the client never "
                    "supplies.</p>")
        body.append(f"<p class='small'>layout scope <code>{_e(lay['layout_scope'])}</code>, "
                    f"algorithm <code>{_e(lay['layout_algorithm'])}</code> "
                    f"({_e(VLayout.LAYOUT_ALGORITHMS[lay['layout_algorithm']][:110])}...), "
                    f"digest <code>{_e(lay['digest'])}</code></p>")
        body.append(_trunc_banner(lay))
        rings: dict[int, int] = {}
        for p in out["positions"]:
            rings[p[4]] = rings.get(p[4], 0) + 1
        body.append("<p class='small'>rings: " + ", ".join(f"{k}: {v:,}" for k, v in
                                                           sorted(rings.items())) + "</p>")
        body.append("<table><tr><th>x</th><th>y</th><th>ring</th><th>sector</th><th>type</th>"
                    "<th>parent</th><th>entity_id</th></tr>")
        for p in out["positions"][:PICTURE_ROWS]:
            body.append(
                f"<tr><td class='mono'>{p[2]}</td><td class='mono'>{p[3]}</td>"
                f"<td>{p[4]}</td><td>{p[5]}</td><td class='small'>{_e(p[1])}</td>"
                f"<td class='small mono'>"
                + (f"<a href='/node/{quote(p[7], safe='')}'>{_e(p[7].split(':')[-1][:18])}</a>"
                   if p[7] else "&mdash;")
                + "</td>"
                f"<td class='mono'><a href='/node/{quote(p[0], safe='')}'>{_e(p[0])}</a></td></tr>")
        body.append("</table>")
        links = " ".join(
            f"<a href='/neighbourhood?seed={quote(seed, safe='')}&amp;depth={d}'>depth {d}</a>"
            for d in (2, 3, 4, 5, 6))
        body.append(f"<p>{links}</p>")
        return _page("neighbourhood", "\n".join(body))

    def _question(self, query_id: str) -> bytes:
        ex = self.explorer
        rec = ex.question(query_id)
        return _page(query_id, _record_html(rec, ex))

    def _questions(self) -> bytes:
        ex = self.explorer
        env = dict(ex.sub.coordinate)
        env["estate_state"] = ex.sub.estate_state
        env["valid_time_window"] = ex.sub.valid_time_window
        env["corpus_fingerprint"] = ex.sub.corpus_fingerprint
        body = ["<h1>the twelve registered questions</h1>", _env_banner(env),
                "<div class='banner warn'><b>This page opens the corpus.</b> "
                f"{MEASURED['open_corpus_s']} s and 258.4 MB on the first question, and 3.8&ndash;"
                f"7.2 s for each of the twelve after that. All twelve at 1M: "
                f"{MEASURED['all_twelve_questions_s']} s.</div>"]
        total = 0.0
        for spec in __import__("query").canonical_questions():
            rec = ex.question(spec["id"])
            total += rec["wall_clock_s"]
            body.append(_record_html(rec, ex, compact=True))
        body.append(f"<p class='small'>total {total:.1f} s for all twelve at "
                    f"{_e(ex.sub.manifest.get('corpus_fingerprint'))}.</p>")
        return _page("questions", "\n".join(body))

    def _graphml(self) -> bytes:
        counts = self.explorer.sub.counts()
        size = "1.61 GB, 46 shards" if counts["nodes"] > 100000 else "small"
        body = [f"<h1>this explorer does not read the estate GraphML</h1>",
                _env_banner(self.explorer.sub.coordinate),
                f"<div class='banner stop'><b>{size}.</b> It is an EXPORT FORMAT for other tools. "
                f"Everything on these pages is read from the Parquet substrate through DuckDB.</div>",
                "<h2>why, in one paragraph</h2>",
                "<p>GraphML is a single serialisation with no shard manifest, no index and no "
                "partial-read protocol, so <b>a graph too large to load cannot be traversed out of "
                "GraphML at all</b>. The only alternatives are to load it anyway, or to "
                "stream-parse it &mdash; which measured at about 29 s at 1M nodes. That is the "
                "reason the Parquet substrate stays the substrate and the GraphML stays an export, "
                "and it is the first documented way to traverse a too-large graph in "
                "<code>schema/graph/traverse.py</code>: <b>do not load it</b>.</p>",
                "<h2>and this is a control, not a promise</h2>",
                "<p><code>substrate.install_graphml_tripwire()</code> wraps "
                "<code>builtins.open</code>, <code>io.open</code> and <code>os.open</code> and "
                "raises on any path ending <code>.graphml</code>. It sits on the real file-open "
                "path, so it fires on a client that reached the GraphML through a filesystem "
                "handler or a subprocess, which a source-text search would not. The explorer's "
                "guillotine watches it fire.</p>"]
        return _page("graphml", "\n".join(body))

    def _timings(self) -> dict[str, Any]:
        ex = self.explorer
        t = time.perf_counter()
        counts = ex.sub.counts()
        t_counts = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        types = ex.types
        t_types = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        spine = ex.spine
        t_spine = (time.perf_counter() - t) * 1000
        return {"measured_now_ms": {"counts": round(t_counts, 2), "type_table": round(t_types, 2),
                                    "spine": round(t_spine, 2)},
                "counts": counts, "types": len(types), "spine_rows": len(spine),
                "recorded_at_1M": MEASURED,
                "estate_frame": ex.estate_frame().get("envelope",
                                                      ex.estate_frame().get("reason")),
                "corpus": ex.corpus_dir}


def _record_html(rec: dict[str, Any], ex: Explorer, compact: bool = False) -> str:
    """An answer record, rendered whole, with a zero rendered differently from a number.

    The distinction is not cosmetic. Ticket 13 measured a query returning a confident top-rung
    <b>zero</b> because the estate held no belief there, and the standing ``KNOWN_GAPS`` failure is
    a rendered "no results" that a reader cannot tell from "nothing exists". So: a zero gets its
    own banner, the estate state is printed on every record whatever the count, and ``cannot_see``
    is never summarised away.
    """
    out = [f"<h2><a href='/question/{_e(rec['id'])}'>{_e(rec['id'])}</a>"
           f" <span class='pill'>{_e(rec.get('question'))}</span>"
           + (" <span class='pill'>&mdash; primary</span>" if rec.get("primary") else "") + "</h2>"]
    if rec["disposition"] != "answered":
        out.append(f"<div class='banner stop'><b>{_e(rec['disposition'].upper())}</b>: "
                   f"{_e(rec.get('prohibitions') or rec.get('reason'))}<br>"
                   f"<span class='small'>{_e(str(rec.get('why'))[:400])}</span></div>")
        return "\n".join(out)
    claim = rec.get("claim_strength", "?")
    rows = rec.get("rows", 0)
    estate = rec.get("estate_state", "?")
    out.append(f"<p class='small'><span class='pill {claim}'>claim {claim}</span>"
               f"<span class='pill {estate}'>estate_state {estate}</span>"
               f"<span class='pill'>{rec['wall_clock_s']} s</span>"
               f"<span class='pill'>V={_e(rec['coordinate']['valid'])}</span>"
               f"<span class='pill'>S={_e(rec['coordinate']['system'])}</span></p>")
    if rows == 0:
        out.append("<div class='banner warn'><b>ZERO ROWS.</b> Read the envelope before reading "
                   "this: <code>claim_strength</code> is <b>" + _e(claim) + "</b> and "
                   "<code>estate_state</code> is <b>" + _e(estate) + "</b>. A zero at a high rung "
                   "is a confident answer and a zero at a low rung is not, and a zero is also "
                   "what a query returns when the twin held no belief here rather than a finding "
                   "about the world. This corpus already contains one: "
                   "<code>q3_as_thought_then</code> returns 0 at rung "
                   "<code>unbounded</code> at V=S=2026-03-15, and the same question at as-known-now "
                   "returns 3. Ask twice.</div>")
    else:
        out.append(f"<p><b>{rows:,}</b> subjects.</p>")
    if not compact:
        out.append("<details><summary>the query as written</summary><pre class='mono'>"
                   + _e(json.dumps(rec.get("query_as_written"), indent=2, default=str))
                   + "</pre></details>")
    caps = rec.get("caps_applied") or []
    if caps:
        out.append("<p class='small'>caps applied: "
                   + ", ".join(f"<span class='pill'>{_e(c)}</span>" for c in caps) + "</p>")
    cannot = rec.get("cannot_see") or []
    if cannot:
        out.append("<p><b>cannot see</b></p><ul class='small'>"
                   + "".join(f"<li>{_e(c)}</li>" for c in cannot) + "</ul>")
    subjects = rec.get("subjects") or []
    if subjects and not compact:
        out.append("<details><summary>the subjects</summary><pre class='mono'>"
                   + _e(json.dumps(subjects[:50], indent=2, default=str))
                   + (f"\n... and {len(subjects) - 50:,} more" if len(subjects) > 50 else "")
                   + "</pre></details>")
    return "\n".join(out)


# ----------------------------------------------------------------------------------- the CLI

def write_estate_layout(ex: Explorer) -> dict[str, Any]:
    """Compute and write the ``estate`` layout scope. Once. Measured at 1M: 4.5 s."""
    with ex._lock:
        lay = VLayout.spine_layout(ex.sub)
    paths = VLayout.write_layout(ex.layout_dir, "estate", lay["envelope"], lay["positions"])
    ex.sub._estate_envelope = None
    ex.sub._estate_frame = None
    return {"envelope": lay["envelope"], **paths}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the materialised estate directory")
    ap.add_argument("--schema", required=True, help="the materialised SCHEMA directory")
    ap.add_argument("--corpus", help="the corpus root, needed only for the questions")
    ap.add_argument("--profile", help="the coverage profile (default schema/overlay/acme)")
    ap.add_argument("--layout-dir", help="where the layout relation is written "
                                         "(default viewer/out/<size>_frame)")
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--write-estate-layout", action="store_true",
                    help="compute and write the estate layout scope, then exit")
    args = ap.parse_args(argv)
    ex = Explorer(args.graph, args.schema, args.corpus, args.profile, args.layout_dir)
    if args.write_estate_layout:
        out = write_estate_layout(ex)
        print(json.dumps(out["envelope"], indent=2, default=str))
        print(f"wrote {out['positions']} ({out['rows']} rows)")
        return 0
    Handler.explorer = ex
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    counts = ex.sub.counts()
    print(f"the explorer, on {ex.sub.graph_dir} @ {ex.sub.coordinate['valid']} "
          f"({counts['nodes']:,} nodes, {counts['edges']:,} edges)")
    print(f"  http://{args.host}:{args.port}/")
    print(f"  corpus for the questions: {args.corpus or 'NOT SUPPLIED -- /questions will refuse'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
