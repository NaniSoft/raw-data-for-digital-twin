# The Anatomy of a CSV File

> **This is a copy.** The source of truth for this document is the **`digital-twin` project
> repository**, which builds the corpus, the schema graph and the estate graph that appear here.
> Every path it names — `schema/…`, `artifacts/…`, `docs/spec.md`, `slice/out/…` — is relative to
> *that* repository, not to this one, and the decision numbers it cites (D19, D21, D30, D42 and the
> rest) are sections of that project's `docs/spec.md`. Where this document quotes a row, a header or
> a measurement, the row came from the corpus published here and the measurement from the project's
> own run reports.

### A reading guide to the digital twin's raw inventory corpus

---

Open `artifacts/small/csv/` and you will find forty-six files. One of them,
`orgs/acme/compute_node.csv`, opens like this:

```
entity_id,entity_type,organization_id,node_key,node_name,node_kind,lifecycle_stage,lifecycle_stage_status,is_monitored,valid_from,valid_to,system_from,system_to,revision,operation
acme:compute_node:phy-0000000~0e09674a1941,compute_node,acme,phy-0000000,phy-0000000.hq,physical_server,inventory,quarantined,\N,2021-01-07T17:42:12Z,\N,2021-01-07T17:42:12Z,2027-03-09T04:37:38Z,1,assert
```

Six hundred and twenty machines. That is all it is: names, a handful of adjectives about each
machine, and six columns of timestamps. There is no flag saying "this machine is safe", no
confidence score, no summary. If you want to know which machines were running unpatched software
in March 2026, and who owns them, nothing in that line will tell you — and the reason it will not
tell you is the most important thing this document has to explain.

The reason is not caution and not a missing feature. It is that **this data is about knowledge,
not about reality.** A row in that file is not a machine. It is the twin's *belief* about a
machine, held over an interval during which the twin held it. The machine existed or did not; the
belief may be right or wrong, and it was formed at a particular moment, which may be long after the
machine did anything interesting. Two of the six timestamp columns exist solely to carry that second
fact — when the twin learned — and everything difficult about this dataset follows from taking it
seriously.

Almost everything concrete here is quoted from the shipped corpus at `artifacts/small/csv/` (the
small scale: 36,187 data rows across 44 CSV files) or from the pinned dialect implementation in
`schema/csv/corpus_io.py`. Where I invent an example to make a shape obvious, I say so. Decisions
are cross-referenced by number — D19, D21, D30, D42 — pointing at `docs/spec.md`, where the
reasoning behind each is written down at length. You will want to read it after, because some of
these decisions are the kind you will want to disagree with.

---

## I. What a file actually is

Before the shape, the meaning. A file in this corpus is **a snapshot of one organization's belief
about part of its own infrastructure, as of one instant, recorded in a way that a later reader can
tell the difference between what was true and when it was found out.**

*One organization's.* Not "an organization". The global catalogue of vendors, product models and
vulnerabilities lives in `global/`; everything belonging to the fictional company Acme Industries
lives in `orgs/acme/`. A file's scope is a property of its path, and section II returns to why that
redundancy exists.

*Part of its own infrastructure.* Not all of it, and — this is the part that surprises people —
not a known fraction of it. The twin's reach is declared, region by region, in data rather than in
a number, and a great deal of this document is about how it says what it does not reach.

*As of one instant.* A row is only meaningful against a coordinate. "Was this machine in the
estate?" is not a question with one answer; it has one answer per (valid instant, transaction
instant, model version) triple, and section III is entirely about what happens when you do not pick
one.

*Recorded so the difference can be told.* This is the load-bearing clause. Most inventories cannot
answer "what did we think in March?" because most inventories overwrite. This one appends. Every
row you will read is one of two things: a belief the twin is asserting over an interval, or a
record that a belief ended. Nothing is ever edited. Nothing is ever deleted.

Here is the thing to hold onto. **A row is not a thing. A row is a sentence the twin is currently
saying about a thing, and the sentence has a start, an end, and a date of issue.** When you read
`phy-0000000` above, you are not learning that a machine exists; you are learning that as of
7 January 2021 the twin asserted a machine named `phy-0000000.hq` existed, and held that belief
until 9 March 2027. Six of the seventeen columns are about the belief. Only eleven are about the
machine.

The reason this dataset is not a photograph is worth stating as engineering judgement. The twin
commits to four security questions: *which internet-reachable hosts ran exploitable unpatched
software, and who owned them?* *What can a compromised service account reach?* *Who still holds
standing administrator after leaving?* *Which columns holding personal data sit unencrypted behind
a user-facing subnet?* Each has a "was" and a "should have been" component, and the gap between the
two is the entire value of the artifact. A question phrased as a complement — *no host was
unpatched* — hides a second assumption: that the twin saw every host. A twin answering confidently
from a photograph will be confidently wrong about everything it never photographed, and wrong in
the direction that reads as good news. That is the failure the design exists to prevent, and the
six timestamp columns are the machinery for it.

---

## II. The shape of a file

### Scope is a property of the path

Compare the two headers and notice what is missing from one of them.

```
# global/organization.csv
entity_id,entity_type,org_slug,org_name,valid_from,valid_to,system_from,system_to,revision,operation
acme:organization:acme~accb46996fcf,organization,acme,Acme Industries,2021-01-02T02:35:13Z,\N,2021-01-02T02:35:13Z,\N,1,assert

# orgs/acme/compute_node.csv
entity_id,entity_type,organization_id,node_key,node_name,...
```

`compute_node.csv` has `organization_id`. `organization.csv` does not. That is not an
inconsistency; it is the declaration. Every type is tagged at design time as either **global** —
the same fact for everyone, so there is nothing to scope and no column — or **organization**,
meaning it belongs to exactly one tenant and carries that tenant's id. There are 34 such tags in
the machine-readable seam, `schema/packs/_core_contract.json`, and the directory tree is the other
copy of the same declaration.

This is deliberate redundancy, and the reason is a specific catastrophe. The column is derivable
from the path. Writing it anyway means a file whose columns contradict its directory is a
detectable error rather than an invisible one — which catches an entity written into the wrong
tenant's directory, the one cross-tenant mistake that would be both catastrophic and completely
silent. This is decision D21, and the sentence that carries it is worth quoting: *"The column is
redundant with the path, and the redundancy is the point."*

### The identity block, and the attribute block

The first three columns of every entity file are, in this order and always: `entity_id`,
`entity_type`, `organization_id`.

`entity_id` is the row's name — a derived, readable string like
`acme:compute_node:phy-0000000~0e09674a1941`. Section V takes it apart.

`entity_type` is denormalised onto every row even though the filename already says it. On a
million-row estate that costs roughly twenty megabytes and earns all of it: a row is
self-describing when you find it out of context, the fold needs no per-file constant to know what
it is reading, and it catches an id written into the wrong file, which is otherwise invisible.

`organization_id` is the scoping column, and its value must equal the directory it sits in.

Everything between `organization_id` and the timestamps is the type's own attributes, and the only
part of the file specific to what kind of thing is described. For a server: `node_key`, `node_name`,
`node_kind`, `lifecycle_stage`, `lifecycle_stage_status`, `is_monitored`. For a database column:
`data_store_id`, `schema_name`, `table_name`, `column_name`, `ordinal_position`, `is_pii`,
`classification`, `is_encrypted_at_rest`.

Three conventions govern these names, and they are checkable rather than stylistic (D21):
`snake_case` throughout; **every boolean is `is_*`, `has_*` or `can_*`**, which is a gift if you
want to find every assertion-shaped column in a wide schema by grep; and `valid_*`, `system_*`,
`revision`, `operation`, `entity_id`, `entity_type` and `organization_id` are **reserved**, so an
attribute may never collide with one and the temporal block can never be shadowed.

Of those six attributes, one is a key. `node_key` is the *natural key*: the stable, world-issued
thing about this machine that does not change when the machine is renamed or moved, and the thing
from which the `entity_id` is computed. `node_name` and `node_kind` are attributes and can change.
Section V explains why that distinction decides more than it looks.

Two of the others deserve a sentence each because they look like the rest and are not.
`lifecycle_stage` and `lifecycle_stage_status` are a **pair**, and the pairing is the point: the most
security-relevant state an asset can be in is "still in use and past end of support", and one field
cannot express that. A single shared vocabulary in a CSV corpus also contains combinations no real
system can produce, and a stage/status pair that cannot occur is a defect the validator can name.
`is_monitored` is `\N` on that row. Hold that thought; section IV is about it.

### The temporal block, and why the order is fixed

The last six columns of every entity file, always, in this order:

```
valid_from, valid_to, system_from, system_to, revision, operation
```

Not "usually". Not "when present". Contiguous, and last. The check in `corpus_io.py` that enforces
it is short enough to quote:

```python
TEMPORAL_BLOCK = ("valid_from", "valid_to", "system_from", "system_to", "revision", "operation")

if tuple(columns[-len(TEMPORAL_BLOCK):]) != TEMPORAL_BLOCK:
    problems.append(f"temporal block is not last and contiguous; ends with {columns[-6:]}")
```

Two things break without the rule, and the first is the obvious one.

The obvious one is mechanical. `tail -6` on any corpus file is the temporal block, so a reader who
wants to know *when* something was believed can look in a fixed place without parsing, and two
files of different types can be diffed field by field because their histories line up.

The second bites harder: **the position of the temporal block is a guarantee about where to look
for the absence of data.** When a tool is deciding whether it can
answer something, it needs to know where the honesty is stored. A fixed, tail-anchored block means
a reader can ask "what does this file know about when" without understanding anything else about
the file. Section X leans on this heavily.

One more fixed-order rule before you write queries. **Rows are in canonical write order**,
`(system_from, entity_id, revision)` — not grouped by entity, because grouping was tried and
rejected for diff noise, but a total order, so two runs of the same seed produce a byte-identical
file. And nothing inside a corpus file may vary between two runs: no generation timestamp, no
hostname, no run id. That timestamp lives in `corpus/manifest.json`, beside the files, never inside
one.

### The dialect, briefly

The files are not "CSV" in the loose sense. They speak one pinned dialect, implemented in
`schema/csv/corpus_io.py`: UTF-8 with no BOM, LF line endings only (so a quoted field can never
contain CR), a header always present in schema order, minimal RFC 4180 quoting, exactly one
trailing newline, booleans as `true`/`false` and never `1`/`0`/`yes`, timestamps as
`YYYY-MM-DDTHH:MM:SSZ`, integers as plain decimal. You will meet the quoting rule in
section IV, where it turns out to matter more than it looks.

---

## III. The six time columns, and the single most important idea in this document

Four of the six timestamps form **two intervals**, and they are intervals over different things.
`valid_from`/`valid_to` is when the fact was true *in the world*. `system_from`/`system_to` is
when *this system* held that particular belief. The remaining two — `revision` and `operation` —
say how to read the pair.

This is called **bitemporal**, which is an unforgivable name for something you can understand in
one sentence: the data carries two clocks, because the world and the observer of the world are
allowed to disagree about when something happened.

### A machine that was decommissioned in April and discovered in October

Here is a real chain from the shipped corpus — two rows, no gaps, both from
`orgs/acme/compute_node.csv`:

```
acme:compute_node:end-0000421~57e4e3fae7a4,compute_node,acme,end-0000421,end-0000421.hq-b1,endpoint,operational,in_use,true,2021-01-07T03:02:10Z,2021-02-27T04:25:32Z,2021-03-07T11:37:26Z,\N,1,assert
acme:compute_node:end-0000421~57e4e3fae7a4,compute_node,acme,\N,\N,\N,\N,\N,\N,2021-02-27T04:25:32Z,\N,2026-02-16T14:48:46Z,\N,2,retract
```

**Row 1.** `valid_from = 2021-01-07`, `valid_to = 2021-02-27`. In the world, this machine existed
from the 7th of January to the 27th of February 2021. Fifty-one days.

`system_from = 2021-03-07`, `system_to = NULL`. The twin learned this on the 7th of March — eight
days *after* the machine had already gone — and has held the belief ever since. NULL here means
one thing only: *no end is known*. It does not mean "unknown", "deleted" or "still current by
some other route".

`revision = 1`, `operation = assert`. First belief, and it is a positive claim.

**Row 2.** Every attribute is `\N`. Not because the twin has forgotten the machine's name, but
because the row is not about the machine — it is about the machine *ending*. `valid_from =
2021-02-27` is the end instant, exactly adjacent to row 1's `valid_to`; `system_from =
2026-02-16` is when the twin finally worked out that the machine had gone, which is nearly five
years after it happened. `operation = retract`. `revision = 2`.

Two things about that second row are not obvious. First, **the attribute columns are all NULL and
that is not a data-quality problem**: a retract asserts that a thing ended, it does not assert
anything about the thing, and filling in `node_name` there would be asserting that the twin still
holds a belief about a machine it has already recorded as gone. Second — and this is the one that has
cost this project more than anything else in the format — **row 1's `system_to` is NULL. The retract
did not close it.**

### The tombstone amendment, and why it is the sharpest rule in the corpus

The instinct, and the near-universal industry practice, is to close the predecessor in transaction
time when you record an end. The pair then reads: "we believed this from March until February 2026,
when we learned it had ended in the previous February." Neat. Wrong. Here is what goes wrong, and
it is worth following precisely because the failure is invisible.

The selection rule — the one statement of which rows are current at a coordinate — is four lines in
`schema/fold/as_of.py`, and it is the only statement of it in the repository:

```python
PREDICATE_SQL = """
    valid_from <= ?::TIMESTAMP
    AND (valid_to IS NULL OR ?::TIMESTAMP < valid_to)
    AND system_from <= ?::TIMESTAMP
    AND (system_to IS NULL OR ?::TIMESTAMP < system_to)
"""
```

Half-open on both axes. Now ask the question the security team actually asks: *which
internet-reachable hosts ran exploitable unpatched software on 15 March, as we now know it?* That
is coordinates `(V = 2021-03-15, S = now)`. Apply the predicate to row 1 above: its valid interval
is `[2021-01-07, 2021-02-27)`, and 15 March is *after* `valid_to`, so row 1 is not selected. Apply
it to row 2: its valid interval is `[2021-02-27, ∞)`, and 15 March is inside it, so row 2 *is*
selected. But row 2 is a `retract`, and the estate projection is selected **assert** rows only. The
retract is in the ledger; the machine is not in the estate.

So the machine is absent — from *every* coordinate before its end, at *every* transaction time after
the end was learned. The query returns rows. It looks fine. The coverage claim is untouched. The
hosts that vanished are precisely the ones that should still have been there.

This was found by running the fold, not by reading the contract. It is recorded as a rule of its
own, `temporal.retract_does_not_close_its_predecessor`, severity **fatal**, whose `counterexample`
field explains why the fold cannot catch it: *"The fold cannot see it at all, because a closed
`system_to` simply removes a row from selection."* The fold is doing exactly what it was told. The
damage is in the *shape of the data*.

The fix is one sentence: **a retract is disjoint from its predecessor in valid time, and therefore
does not close it in transaction time.** The two rows are adjacent in valid time — `[t0, t1)` and
`[t1, ∞)`, meeting exactly at the boundary — and so cannot both be selected at one coordinate, which
is what makes the shape legal. The predecessor keeps `system_to = NULL`; the end is still a recorded
row, still greppable, still permanent; it no longer destroys the life it ends. The cost is
small and stated rather than hidden: one extra row per end, and any consumer assuming "one open row
per entity" is now wrong. `PREDICATE_SQL` did not change and the fold needed no code edit — the
strongest available evidence that the predicate was always the right shape and the *chain* was
wrong.

One more thing, because it decides which rows you will see in `relationships.csv`. **A superseding
assert *may* close the assert it supersedes.** A correction — the twin used to believe one thing and
now believes a different thing over the same period — legitimately closes the old belief, and the
rule says so: *"A RETRACT MUST NOT CLOSE ITS PREDECESSOR. A SUPERSEDING ASSERT MAY CLOSE THE ASSERT
IT SUPERSEDES. NOTHING ELSE CLOSES ANYTHING."* A `retract` that closes its predecessor in transaction
time is a fatal defect; an `assert` that closes the row it replaces is a correction and is fine.

### The retroactive case, where the two clocks diverge the other way

Now the shape from the other end, and the one that most directly answers "what was true in
March".

Two rows again, both `assert`, from the same file. Read the two timestamps against the columns and
something important shows up:

```
acme:compute_node:end-0000415~8421fbb9f423,compute_node,acme,end-0000415,end-0000415.hq-dc1,endpoint,operational,in_use,true,2022-09-20T17:32:33Z,\N,2022-10-23T01:04:53Z,2023-02-21T15:40:25Z,1,assert
acme:compute_node:end-0000415~8421fbb9f423,compute_node,acme,end-0000415,end-0000415.hq-dc1,endpoint,operational,legal_hold,true,2022-09-20T17:32:33Z,\N,2023-02-21T15:40:25Z,\N,2,assert
```

`valid_from` is **20 September 2022** — the machine has been there since then. `system_from` is
**23 October 2022** — the twin only heard about it a month later. So there is a month during which
the machine was true and the twin had no idea, and it is recorded rather than smoothed over.

Now ask two questions, and notice they have different correct answers.

> **"Was this machine in the estate on 1 October 2022?"**
> Coordinate `(V = 2022-10-01, S = 2022-10-01)` — what we now think about what we thought then.
>
> `valid_from ≤ 1 Oct ≤ ∞`: yes. `system_from ≤ 1 Oct`? 23 October is *after* 1 October. **No.**
> Nothing is selected. The answer is *the twin had not heard of it*. **Not** "it did not exist".

> **"Was this machine in the estate on 1 October 2022, as we now know it?"**
> Coordinate `(V = 2022-10-01, S = now)`.
>
> Same valid test, same system test with a later `S`. **Yes.** The machine was there.

Both answers are correct. They answer different questions, and the difference between them *is*
the second clock. An ordinary inventory has nowhere to put that difference: it would show the
machine with one date and the reader would have no way to know that in October the twin believed
something else. (D19 calls this "the retroactive case" and notes that it needs no new concept at
all — a retroactively inserted row with an early `valid_from` and a late `system_from`, and a
superseded belief closed in both axes.)

The two rows also show the second thing the temporal block can hold: a **supersession**. Same
entity, revision 1 then revision 2, with `system_to` closed on the first at the moment the second
was written. The machine did not change; the twin's account of its lifecycle did, from `in_use` to
`legal_hold`, and that change was learned on 21 February 2023. Note what the valid-time story is:
`valid_from` is unchanged at `2022-09-20T17:32:33Z` on both rows. The twin did not decide the machine
entered legal hold in February 2023. It decided it *now knows*, as of February 2023, that the machine
had been in legal hold since September 2022. Back-dating a learned correction is the whole point.

### The two questions every reader should carry

| Name | Coordinates | The question it answers |
|---|---|---|
| **current** | `(now, now)` | What does the twin believe, now |
| **history as we now know it** | `(t, now)` | What was true at `t`, using everything learned since |
| **history as we thought it then** | `(t, t)` | What did the twin believe at `t`, back then |

The third is the only answer to *"we knew in March and did not fix it"*, and it is the entire
justification for having two clocks at all. The second is the one you get by default for a
historical question, and that default is itself a decision with a name and a reason (D30): a
practitioner who has not said "as we believed then" must not be handed the past's beliefs wearing
the past's date. Asking for the third is a visible, deliberate act.

**`now` is never a wall clock.** It is the corpus's own declared `window_end`, read from
`manifest.json` — `2027-04-25T23:59:59Z` for the shipped small corpus. A wall clock would make the
same corpus answer differently twice, which makes diffing snapshots produce noise and makes the one
check that would catch a broken fold untestable. It fails invisibly, because both answers look
reasonable.

You can see all of this measured. The vertical slice runs the four canonical questions at both
classes over a real corpus and diffs the answers, published in `slice/out/questions.json`.
Ownership of internet-reachable hosts, as known now: **13 rows**. The same question, as thought
then: **9 rows**. Four owners appear in the first answer and not the second; one appears in the
second and not the first. Nothing about the estate changed between March and September. What changed
is what the twin knows, and the difference in the answer is the size of that change.

One more measured fact from the same run, because it shows the size of the gap and not only its
effect: at the fold, 2,303 entities are `not_yet_known` at the as-thought-then coordinate against 89
at the as-known-now coordinate, with 2,068 becoming `retrospective_gap`. Nearly two thousand
entities were in the estate in March, were believed to be in the estate in March, and are not in
the estate as the twin believed it in March — because the March belief was superseded later. That
is not a bug in the data. That is what "we now know more than we did" looks like when you keep
both.

### `revision` and `operation`, briefly

`revision` is a per-entity counter starting at 1, gapless, and it exists to make one thing
unambiguous: which of two rows about the same entity the twin wrote first. It orders **transaction
time only**, and it is paired with `system_from` to do so: `(system_from, revision)`. It never
appears on the valid-time axis. That is not an oversight and it has a reason: a retroactively
inserted row has an *early* `valid_from` and a *late* `revision` at the same time, so ordering
valid time by `(valid_from, revision)` misorders it — the correct valid order is `valid_from`
alone, because within one system interval the valid intervals are disjoint and therefore already
a total order.

`operation` is `assert` or `retract`, and those are the only two values. Not `insert`, not
`update`, not `delete` — a delete is a retract, and saying otherwise would put a third word in a
two-way vocabulary for no gain.

And one precise statement about what `revision` counts, because a rule depends on it and it was
reconciled late: a retract consumes a revision number, so **`revision` counts rows**. Every row
written for an entity, assert or retract, takes the next number.

### The grain, which is the ceiling on all of this

The last structural fact, and the one that quietly bounds everything: **a cell value is never a
node** (D4). The model goes down to a database *column* and stops there. A table row can be a node
if the table has been designated *data tier*; the individual field values in it cannot. The ceiling
is set by renderability and queryability, not by fidelity for its own sake.

This is the difference between a question the data can answer and one it structurally cannot. "What
is in this table's `ssn` column, and is it encrypted?" is answerable. "What was the value of this
employee's social security number in March?" is not, and section X will say so again. A row's
values live in a per-table payload, at one instant; asking about their past is a different and much
harder question.

---

## IV. `\N` and what it does not mean

### The convention

A NULL in this corpus is the two unquoted characters `\N`:

```
acme:database_column:acme-data-store-store-00000~56892f84afd3,database_column,acme,acme:data_store:store-00000~199fa6b0c449,hr,employee,event_id_001,1,\N,\N,\N,2021-01-07T17:42:12Z,\N,2021-01-07T17:42:12Z,\N,1,assert
                                                                                                            ^^^   ^^^   ^^^
                                                                                             is_pii     classification  is_encrypted_at_rest
```

That row has three NULLs in a row, and they are the most consequential bytes in the file. Why not an
empty field? Because an empty field is exactly how RFC 4180 spells the empty string, and if NULL
and the empty string share an encoding the empty string becomes unrepresentable — which matters,
because "a column that holds an empty string" is a real thing in an inventory, not an edge case. So
three things are visibly different on disk:

| On disk | Means |
|---|---|
| `\N` (unquoted) | no value was recorded |
| `""` (quoted, zero length) | the value is the empty string |
| `"\N"` (quoted) | the value is the two characters `\` and `N` |

And the corollary is enforced rather than documented. **An unquoted empty field is illegal.**
`a,,b` is a malformed file. The reader raises:

```python
if text == "" and not quoted:
    raise DialectError(
        f"{path}: unquoted empty field; write {NULL_TOKEN} for NULL and "
        f'"" for the empty string'
    )
```

This is one of the two bugs that were found by writing the round-trip test rather than by writing
an example, and both were silent-corruption bugs rather than loud ones. The other was that NULL
must be quoted on the strength of the *value* being null rather than the rendered text — quote the
sentinel and a NULL becomes byte-identical to the string `\N`, and the two then decode
identically. The fix is that the decoder takes the parser's *quoted flag*, because that flag is
the only thing distinguishing them:

```python
def decode_field(text: str, quoted: bool) -> str | None:
    if not quoted and text == NULL_TOKEN:
        return None
    return text
```

### The harder half: NULL is not false, and it is not zero

Here is the sentence that matters more than the one about the bytes:

> **NULL means no value was recorded. It is not a statement that the value is absent, and it is
> certainly not a statement that the value is "no".**

Those are three different claims about three different worlds, and CSV gives you exactly one
marker, so the marker has to mean the weakest of the three — otherwise the system will invent
facts on your behalf. In an inventory column, `is_encrypted_at_rest = \N` does not say the data
is unencrypted. It says **nobody has written down whether the data is encrypted at rest.** Those
have opposite operational consequences and a security system must be able to tell them apart.

D30 puts the consequence of collapsing them this way:

> *A populated field with an empty value is a finding; a field nobody ever populated is a coverage
> gap, and only the second caps a claim.*

A CSV corpus cannot express that distinction by default, so the corpus contract requires it to be
expressed. And the cheap encoding real CMDBs use instead — a global "this source populates
everything or nothing" — is exactly why their detail-completeness metrics mean nothing.

### Why three columns on `database_column` are nullable, and what it would cost if they were not

D4 set the depth floor: a database column is a node. D42 then made three of that node's
attributes nullable, because the fourth canonical question is written over them: *which PII columns
sit unencrypted at rest behind a user-facing subnet?* In any CSV corpus produced by a generator a
boolean column nobody thought about comes out **false**, because that is what a missing value
becomes when a table is filled in. D42 states the finding directly:

> *"`is_pii` is false by default in any CSV corpus, so a column nobody ever assessed reads as
> **not PII** and drops out of the answer."*

So the three columns are nullable, and NULL means *unassessed, never false*. D45 later added a
fourth — `sensitivity` — under the same rule. The rule is unchanged and now covers four columns.
(Amendment, honestly stated: the shipped corpus at `artifacts/small/csv/` carries the original
three; `sensitivity` exists in the taxonomy and the coverage contract, and the generator has not
yet grown the column. If you are reading this against a corpus regenerated after that lands, the
fourth column is there and the rules in this section apply to it unchanged.)

### The false all-clear, concretely

Consider the row in the corpus with all three unassessed:

```
acme:database_column:acme-data-store-store-00000~56892f84afd3,database_column,acme,
acme:data_store:store-00000~199fa6b0c449,hr,employee,event_id_001,1,\N,\N,\N,
2021-01-07T17:42:12Z,\N,2021-01-07T17:42:12Z,\N,1,assert
```

Column `event_id_001` of `hr.employee`. Nobody has classified it. Nobody has said whether it is
personal data. Nobody has said whether it is encrypted at rest.

Now suppose the loader — any loader, yours included — coerces NULL to `false` "to make the booleans
work". Trace it through a control written over the data. The control is: *every column whose
classification is at or above `restricted` must be encrypted at rest.* A NULL `classification`
becomes `public`, the lowest rung; this column is not at or above `restricted`, so it passes. So are
the other 80.

The shipped small corpus has **81 `database_column` rows out of 1,100 with a NULL
`classification`** — 7.4% of the columns, carrying no classification at all. Under a NULL-as-false
reader every one of them silently qualifies for the lowest band, and the report says: *0 columns
classified at or above restricted are unencrypted at rest.* That sentence is not a lie about any
individual column. It is a lie about the estate, produced entirely by an omission, and it reads
exactly like good news.

Nothing was wrong with the data. The corpus said `\N`, said it correctly, and even **declares the
gap itself** — `blind_spot.csv` carries a row whose whole job is to say that the `classification`
attribute class has never been assessed:

```
acme:blind_spot:spot-classification-gap~31cf6a9313ce,blind_spot,acme,spot_classification_gap,
unclassified_attribute_class,attribute_class,\N,classification,not_yet_classified,\N,none,
walkdown_sites,asserted_by_owner,[],2021-01-11T13:34:04Z,\N,2021-01-11T13:34:04Z,\N,1,assert
```

That row is a small masterclass in the vocabulary. `region_kind` is `attribute_class` — this gap has
**no location**; it is about a class of field everywhere. `region_ref` is therefore NULL, which is
the only region kind where that is legal. `cause_kind` is `not_yet_classified`. `scope_magnitude` is
NULL and `scope_basis` is `none`, because the twin cannot honestly say how many columns are
unclassified, and with no basis there is no bound. That one omission is the entire difference between
"the report is clean" and "we do not know, and here is the file that says so".

The machinery treats the distinction as load-bearing in three further ways. **A NULL on any of the
four columns is a Blind Spot scoped to that attribute class**, and a blind spot *suppresses* a
complement rather than satisfying it: naming a gap is the opposite of clearing it. **Every attribute
class must be declared whether or not it is assessed**, and an organization that never lists
`classification` has declared no gap over unclassified columns — which D40 calls, in a phrase worth
stealing, a *false all-clear manufactured by an omission*. And **the coverage claim is attributable
or absent**: a completeness figure is admissible only if its denominator came from a named
observation the twin can point at.

### A related trap: encryption is not one boolean

**Encryption at rest is an inference over three levels, not one boolean**: the column's own
assertion if there is one, else the store's, else unknown, with the basis always named beside the
answer. A store-level "encrypted" can therefore never silently become a column-level answer — the
same failure in a different costume, a fact about the container passed off as a fact about the
thing inside it.

---

## V. Identity: `{org}:{type}:{slug}~{hash12}`

### The shape

Every entity id in the corpus has this form:

```
acme:compute_node:phy-0000000~0e09674a1941
  │      │            │            └── 12 hex characters of BLAKE2b
  │      │            └── a lossy, readable rendering of the natural key
  │      └── the entity type
  └── the organization slug
```

and a relationship id looks like `acme:rel:assigned_to~e3e7f8321c19`.

**The derivation is a pure function.** Given an organization, a type, and the thing's natural key,
the id is computed. There is no lookup table, no registry, no dependence on generation order, no
dependence on insertion order, and no dependence on which As-Of you are asking about. You can
recompute any id in the corpus from three strings and a hash function:

```
derive_id("acme", "compute_node", "phy-0000000")
  -> "acme:compute_node:phy-0000000~0e09674a1941"
derive_id("acme", "blind_spot", "spot_classification_gap")
  -> "acme:blind_spot:spot-classification-gap~31cf6a9313ce"
```

Both match the corpus exactly, and the slug of the second is visibly lossy — `spot_key` is
`spot_classification_gap` and the id carries `spot-classification-gap` — which is fine, because
the hash carries the exactness and the slug carries the legibility.

**The constants are pinned** the way a database version is pinned, because changing any of them
changes every id in the corpus: BLAKE2b at `digest_size=6` in hex; Unicode NFC normalisation;
**no case folding**; leading and trailing whitespace stripped per component with interior
whitespace significant; components joined with U+001F, a character that cannot occur in a normalised
component. `SCHEME_VERSION` — currently `id-v1` — is written into every exported artifact, so a
reader can always tell what produced an id. No case folding looks like pedantry and is not: `HR-01`
and `hr-01` are different keys, and folding them silently merges two real things.

**The escaping rule is that there isn't one, by construction.** The slug alphabet is `[a-z0-9-]`,
which excludes both the `:` and the `~` separators, so an id never needs quoting in CSV, Parquet, a
GraphML `<node id>`, JSON, a file name, or a URL path segment. The hash separator is `~` rather than
`#` precisely because a URL fragment would eat it. A fully escaping, fully reversible id was
considered and rejected: it puts `/` and `:` from paths and CIDRs into every id and then needs
quoting everywhere, to buy a reversibility nobody asked for.

### Why the natural key must be made of non-nullable columns

This is the constraint in the seam that looks fussy until you meet `blind_spot`, and the
`blind_spot` case is worth following because it is where a rule was learned rather than chosen.

The `blind_spot` type records the twin's own declared gaps — the named regions it knows it has not
observed. Its first two key components were going to be `(region_ref, spot_class)`. Here is the
obstacle:

```
acme:blind_spot:spot-classification-gap~31cf6a9313ce,blind_spot,acme,spot_classification_gap,
unclassified_attribute_class,attribute_class,\N,classification,...
                                          └── region_ref, NULL
```

**`region_ref` is NULL exactly when `region_kind = attribute_class`.** And the identity derivation
rejects a NULL key component outright:

```python
if value is None:
    raise IdentityError(
        "natural key component is NULL; NULL means 'no value', and a key cannot be NULL"
    )
```

The reason is in D20 and it is a principle rather than a technicality: **an id must never be
derivable from a missing fact, because a missing fact is a blind spot rather than an identity.**
So a key that leads with `region_ref` can name a region gap and cannot name an attribute-class gap
*at all* — not badly, not degenerately. It raises.

Dropping `region_ref` and using `spot_class` alone does not rescue it, because the two
attribute-class gaps a real estate has — one per unassessed attribute class — share both
components. The key collides.

> **A natural key is a tuple of the type's own columns, every one of which is non-nullable for
> that type. A column some row of the type may leave NULL is structurally ineligible.**

`blind_spot`'s key is therefore `spot_key` — its own readable name, which is non-null, unique
within the organization, and which D30 specifies. So the gap stays addressable *even when its
region is unknown*, which is the entire point: you must be able to name "we have never assessed
encryption" without knowing which store it applies to, and an identity scheme that cannot derive
an id for that is a scheme that makes the honest answer unrecordable.

This is a case where the encoding refused a value rather than inventing one, and it is the same
instinct as the NULL discussion in section IV, arriving from the other side.

### Why a collision always fails

Twelve hex characters is 48 bits; among a million distinct keys that is roughly a 0.18% chance of
one collision, about one run in 550 at full scale. The decision is not to make that number smaller
but to make the collision **loud**: it is a hard validation failure that is always detected, and
the fix is always a longer hash. Never a disambiguator — an id that depends on discovery order is
not derivable and not reproducible, and derivability is the entire guarantee. A system that
resolved collisions by appending a counter would still be *correct* and would still be worthless,
because you could no longer recompute an id from first principles and two snapshots would no longer
diff by eye.

### Why a renamed thing is a new thing

```
acme:rel:succeeds~156d6226f80a,succeeds,
acme:certificate:hq-acme-example-9a477cdd0d36~ebcbd80dbd9c,
acme:certificate:remote-acme-example-f9570ecc1a1a~e1f0411b653f,acme,
2022-02-06T18:12:51Z,\N,2022-02-06T18:12:51Z,\N,1,assert
```

That certificate and its renewal are two entities. If the renewal had inherited the id, the
question *"was this patched before the certificate was replaced?"* would be unanswerable, because
the two histories would interleave into one chain.

And one rule to know before you write an id resolver: **an id is never reused**, load-bearing
precisely because end-records are permanent. Recycle an id and last March's As-Of silently
resolves to this year's machine.

### Native identifiers live elsewhere, on purpose

An asset tag, a serial number, an ARN, a `objectGUID`, a vCenter uuid, a CMDB number — none of
these is the identity. They are attributes in `source_refs.csv`, keyed by entity id:

```
acme:principal:svc-hq-00000~01978ce268bc,iam_corp,svc-hq-00000,rec-svc-hq-00000,2021-01-07T17:42:12Z
acme:entitlement:acme-principal-svc-hq-00000~d49af567e0ad,ticket_bridge,grant-00000084,rec-grant-00000084,2021-01-29T17:22:40Z
acme:entitlement:acme-principal-svc-hq-00000~0f55761b8e85,ticket_bridge,grant-00000066,rec-grant-00000066,2021-02-05T05:05:27Z
```

Three rows, two source systems, and the pattern is worth internalising. A real organization runs a
directory and a ticket bridge and a CMDB, and the same grant appears in two of them under two
native ids. **Multiple rows per entity in `source_refs` are the normal steady state, not a defect** —
and that is the whole reason the natural key can be a content key at all: because the world's own
handles are preserved verbatim beside the derived id, a real export round-trips and a real
organization can be onboarded without the identity scheme becoming an integration problem.

`source_refs.csv` is also the one table that is *not* bitemporal. It is current state, because the
assertion history already exists in the entity's own rows and in `observation`. It is explicitly
exempt from the rule that entity files carry no foreign keys, because it is not topology — it
expresses no edge in the graph at all. Section VI returns to that.

---

## VI. Relationships are facts, not edges

### One file, eleven columns

All connectivity in this corpus lives in a single file per organization. `relationships.csv` is
4,888,450 bytes and 23,106 rows in the small corpus, and its header is exactly eleven columns:

```
relationship_id,relationship_type,from_entity_id,to_entity_id,organization_id,valid_from,valid_to,system_from,system_to,revision,operation
acme:rel:contains~d3642775e03f,contains,acme:organization:acme~accb46996fcf,acme:org_unit:none-div-corp~ad3df9f21c07,acme,2021-01-02T02:35:13Z,\N,2021-01-02T02:35:13Z,\N,1,assert
```

Count the columns against the identity block and you find something worth sitting with: **there is
no attribute block.** Five identity-ish columns, then straight into the temporal block. Not because
the table was cut short. Because D10 and D18, as amended, say a relationship is a *fact*, and under
D19 every fact is bitemporal, so a relationship row carries the four time columns plus `revision`
and `operation` and nothing else.

This is a real divergence from both incumbents and the specification says so rather than dressing
it up: BMC's own documentation states plainly that "relationships, like CIs, have attributes". The
two-sided naming convention is adopted; the rest is paid for with the type count.

### Why a relationship needing a domain attribute is really an entity

The rule is stated as a corollary rather than an exception, and it is the mechanism that stops
D10 from being violated by slow accretion:

> **A relationship that needs a domain attribute becomes an entity.**

A firewall rule with an action, ports and a zone pair is not an annotated edge. It is a type with
its own CSV and its own node, because it deserves somewhere to attach a finding. In the shipped
corpus that logic has produced `access_rule`:

```
acme:access_rule:rule-019050~bcbef8b2c46d,access_rule,acme,rule-019050,deny,tcp/389,389,150,true,...
                                            │      │        │    │      │    │    │
                                            │      │        │    │      │    │    └── is_reviewed
                                            │      │        │    │      │    └─────── rule_order
                                            │      │        │    │      └──────────── dst_port
                                            │      │        │    └─────────────────── protocol
                                            │      │        └──────────────────────── action
                                            │      └───────────────────────────────── rule_key
                                            └────────────────────────────────────────── type
```

and the four role edges that connect it to the things it governs. `data_flow`, `entitlement` and
`affected_product` are the same pattern: the entity carries the attributes and the interval, its
edges to each participant are ordinary topology, and the validator asserts each edge's interval
equals the entity's. The cost is stated in the decision rather than hidden — one extra
relationship type per participant role, and the type count grows over time.

The same instinct applies to duplications as to missing columns. `data_flow` must not carry a
`direction` attribute: the ordered endpoints already say it, and storing it would be a second source
of truth about the same fact.

### `operation` on an edge means what it means on an entity

`relationships.csv` carries 1,255 `retract` rows in the small corpus. They are the same shape as
the entity retracts: attributes are already absent, so the whole thing reduces to the two
intervals and the counter.

```
acme:rel:designated_data_tier~b80af623da80,designated_data_tier,
acme:database_table:acme-data-store-store-00005~7dbac2aa6678,acme:team:team-028~56f3500ef004,acme,
2021-03-13T19:51:08Z,\N,2026-09-28T00:00:00Z,\N,2,retract
```

Read that as a sentence: *the designation of this table as data tier, by this team, was believed to
hold from 12 January 2021 to 13 March 2021, and the twin has believed that since 28 September
2026.* A relationship can end. A VM can migrate between hosts, an IP can change segment, a person
can change team, an entitlement can be revoked — each of those is a fact about the estate over
time, and the first and last of them are things this twin exists to answer. A model in which
relationships are timeless edges has nowhere to put any of it.

### Provenance is not topology

`source_refs.csv` was covered in section V; the decision-level point deserves its own line here,
because it is the exception that makes the whole "no foreign keys" rule workable. D11 says entity
files carry `organization_id` for scoping and **no other foreign keys**. Two mechanisms for one
edge would be two truths, and coherence would rot.

`source_refs` is exempt, because it is not topology: it is a provenance side-table keyed by entity
id, carrying native identifiers, the asserting source system and a `reconciliation_id`. It holds
references because it expresses no edge in the graph. And there is deliberately **no `discovered_by`
relationship type** — a million rows of provenance edges would buy nothing a keyed table does not
already answer, and duplicates across sources are the expected steady state of a multi-source
estate rather than a defect.

The same exemption is later extended to `region_ref`: a blind spot's region reference is a *scope
declaration*, not a containment edge. If it were topology it would need a containment parent, and an
attribute-class gap — which has no location at all — could not have one.

### The containment spine, and its one lawful exception

Every type declares at most one **structural parent**, the thing that holds it. In the schema
graph that renders as 38 `spine` nodes. In the estate it renders as `contains` edges, and `contains`
is by a wide margin the most common relationship in the corpus — 6,339 of 23,106 rows in the small
estate.

The rule is checked as a *temporal* property, not a structural one, and that is the interesting
part. Two parents **at two different times** is not two parents. It is two `contains` rows on the
same entity with different intervals, and the validator asserts that at any single As-Of the
closure yields at most one. A server that moved from one rack to another has one parent at a time
and two across its life.

And then there is **the reachability invariant**: every entity is reachable from `organization` by
`contains`. An entity with no containment path is an orphan, and an orphan is a defect.

With exactly one exception, and the exception is the reason blind spots have to be first-class
data rather than a caveat in a document:

> An entity lying inside a **declared blind spot** is not an orphan.

Without that exception, "what the twin has not seen" and "what the twin has misplaced" are the same
error, and you cannot tell a gap from a bug. The scope of the exception is narrower than it reads,
and the narrowing matters: it is evaluated by containment closure over `region_ref`, so **a gap
about a *place* can excuse something lost there, and a gap about a *field* excuses nothing.** The
`classification` blind spot in section IV does not excuse a single orphan, and it is not supposed
to.

The four global-scope types — `vendor`, `product_model`, `vulnerability`, `affected_product` — are
recorded as **spine-exempt**, because they are by definition not owned by an organization: a real
exception to the invariant as written, surfaced rather than fixed.

### The edge states, and why "the edge points at nothing" is not an error

D22 and D54 give every edge a state at every coordinate, and the vocabulary is worth learning
because section X depends on it.

| State | Meaning |
|---|---|
| `asserted` | an assert covering V is selected at S — the normal case |
| `ended` | no assert is selected and a retract is — **valid state** |
| `retrospective_gap` | the twin held beliefs at S and none covers V — **valid state** |
| `not_yet_known` | every row of this relationship has `system_from > S` — the twin had no belief at all |

Separately, an edge's *target* carries one of five states: `present`, `ended`, `retrospective_gap`,
`not_yet_known`, and `unknown`. Two of the five are defects and three are valid state, and
conflating any pair of them is the mistake this whole mechanism exists to prevent.

The one a reader is most likely to get wrong is the second: **an edge pointing at something that
has legitimately ended is valid state, and it is the raw material of the third canonical question.**
A departed employee still referenced by a standing entitlement is a reference to something real
and gone. Flagging it would fail exactly the rows the departed-privilege question needs, and
deleting the edge is the tempting, destructive fix that must not be applied. The small corpus
carries 591 such expected-dead targets in the estate graph and the validator grades that entire
population `info` — a census that never fails a run.

---

## VII. Three tiers, and what a pack may add

### The three tiers

Not every kind of thing in this model has the same lifetime, and the model says so explicitly (D14,
D18). Three strata, declared on every one of the 34 core types:

| Tier | What it is | Examples in the corpus |
|---|---|---|
| **R** — reference data | real, named, not an instance of managed configuration | `site`, `team`, `person`, `privilege`, `security_zone`, `source_system`, `contract`, `organization` |
| **P** — product model | what a kind of thing *is*, as distinct from any particular one | `product_model`, `vulnerability`, `affected_product` |
| **I** — instance | one real thing in one organization at one moment | `compute_node`, `ip_address`, `service`, `database_table`, `database_column`, `blind_spot` |

The reason to split them is a worked case that is easy to get wrong. *A Dell PowerEdge R750, as a
product* and *the R750 in rack B12, as a thing* are not the same entity, and their lifetimes differ
— the product outlives every instance of it by years. One flat layer would force every software
installation to inline its own copy of the product's metadata, and the copies would drift apart.

A second axis runs across the tiers, and it determines whether a file has an `organization_id`
column: **global** (the same fact for every organization) or **organization**. Both axes are
declared, because a tier alone does not tell you which, and getting that wrong produces a corpus
where half the tables carry a constant scope.

Note where `blind_spot` and `discovery_run` land, because it is unintuitive: both are tier **I**,
scope **organization**. A blind spot is a thing that exists, in one organization's knowledge, over
an interval during which the twin held it, and it is subject to supersession like anything else.

### What a pack is, and what it is forbidden from doing

A **type pack** is a loadable set of types and relationships contributed by one ecosystem — a
cloud provider, a hypervisor — that an organization opts into. Two ship against the core:
`schema/packs/cloud/aws.yaml` and `schema/packs/virtualization/vsphere.yaml`, both version 1.0.

The rule that governs them is a single sentence, and it is the most useful thing in this section
(D32):

> **A pack extends the core's *topology*; it may not extend the core's *shape*.**

*Topology* is which types may be connected to which — a set of permitted edges, which is exactly
what an ecosystem vocabulary is made of. *Shape* is types, their attributes, their natural keys,
their tiers and their scopes.

What a pack *may* add is enumerated and short: new entity types with tier and scope declared; new
relationships, including between two core types; extensions to a core relationship's target set where
the contract marks it `open`; guarded re-parenting of a core type; new values for a core's declared
open vocabularies, each with a stated meaning; and **global-scope catalogue rows** into the core's
`product_model` and `vendor`. That last one is unintuitive and worth a note: a pack ships its
vendor's *catalogue* — what an EC2 instance *is* — into the core's own `product_model` type, never
into a pack-owned one, because two organizations running the same estate would otherwise carry two
catalogues and their versions would drift. So a pack may ship data, but only global-scope data.

A pack's type names are namespaced, with a single `.`, and the corpus shows it:

```
acme:aws.aws_account:100200300400~59c368eb4251,aws.aws_account,acme,100200300400,prod-eu,standalone,false,root+prod-eu@acme.example,false,2026-09-15T03:45:06Z,\N,2026-09-15T03:45:06Z,\N,1,assert
```

The file sits at `orgs/acme/packs/aws/aws_account.csv`; the directory carries the namespace and the
id flattens it. The two agree on the namespace and differ in separator, deliberately. Namespacing
protects *identity* — two packs contributing the same type name cannot produce colliding ids — but
it does **not** protect the schema graph, where two identically-named nodes are one node a reader
cannot tell apart. So ids are namespaced by pack, schema-graph type names are globally unique, and
two packs contributing the same name is a hard error. Identity disambiguation is not schema
disambiguation.

### The overlay, and the one test that separates it from a pack

The third leg of the model is the **organization overlay**, defined by a one-sentence test: *could
you hand this to another organization?* A pack is ecosystem-shaped and portable; the overlay is
organization-shaped and belongs to exactly one. The overlay is declared to add **no types and no
attributes at all** — only data, plus the list of packs this organization selected. That is a
stronger claim than the design needs, which is the point of making it. Its one load-bearing job is
the thing a pack structurally cannot do: binding an ecosystem's structures to *this* organization's
own reference data. The file is `schema/overlay/acme/profile.yaml`, and what it binds against is
ordinary corpus data, matched on natural keys and never on entity ids. A binding that needs a type,
a relationship, a column or a key of its own is a schema change wearing a data costume.

---

## VIII. How to read a row, end to end

Everything above is machinery. This section is the point of the machinery: here is one real row,
and here is what it licenses you to conclude.

Take a database column from the shipped corpus — the thing the fourth canonical question is
written over. On disk this is one line; it is wrapped here so you can see the blocks.

```
acme:database_column:acme-data-store-store-00000~b12710f5fb96,database_column,acme,
acme:data_store:store-00000~199fa6b0c449,hr,employee,event_ts_001,2,false,public,false,
2021-01-08T00:49:40Z,\N,2021-01-08T00:49:40Z,\N,1,assert
```

Column by column, with the question each one answers and — the part that is easy to skip — the
question it does **not**.

### `entity_id` — `acme:database_column:acme-data-store-store-00000~b12710f5fb96`

*What it is:* the derived name of this entity. Readable in three parts — `acme`, the type, and a
lossy slug over the natural key — plus twelve hex characters of BLAKE2b that carry the exactness
the slug loses.

*Where it came from:* computed from `(acme, database_column, "acme:data_store:store-00000~199fa6b0c449", "hr", "employee", "event_ts_001")`. You can recompute it and you will get this string.

*What it licenses:* you can point at this column unambiguously, and you can ask for it at any
coordinate. That is a strong guarantee and it is about *this entity*, not about a name.

*What it does not license:* it does not tell you the column still exists. It does not tell you
anyone is still using it. It does not tell you there is only one `event_ts_001` in the estate —
there is one per table, and the corpus has 1,100 `database_column` rows with names that repeat
across 130 tables.

### `entity_type` — `database_column`

*What it is:* the kind of thing. Denormalised onto every row so that a row is self-describing out
of context.

*What it licenses:* you can tell what sort of row this is without opening the file, and the fold
does not need a per-file constant.

*What it does not license:* it is not a foreign key and it is not a class hierarchy. A
`database_column` knows nothing about the table it belongs to except through the columns to its
right.

### `organization_id` — `acme`

*What it is:* the tenant. Redundant with the path `orgs/acme/`, deliberately.

*What it licenses:* you can filter to one tenant, and a file whose columns contradict its
directory is a detectable error.

*What it does not license:* it says nothing about **who owns the column**, which is a different
question answered by a different mechanism entirely — a `designated_data_tier` edge to a `team`
for a table, or an `operated_by` edge, and for most columns nothing at all.

### The four natural-key components

```
data_store_id = acme:data_store:store-00000~199fa6b0c449
schema_name    = hr
table_name     = employee
column_name    = event_ts_001
```

*What they are:* the tuple that makes this column nameable. Content plus parent, never position.
The seam declares the key as `(data_store_id, schema_name, table_name, column_name)`.

*Why the store is an id and not a name:* the components are the *stored key values*, which is what
makes the id derivable. A composite key embeds the parent's key components, not the parent's id,
and that is the whole answer to "how does a traversal join with no foreign keys" — **it joins on
the parent's own key column.**

*What the key does not license:* `hr.employee.event_ts_001` is a **qualified name, not an
identifier**, and section X returns to what happens when you forget that.

### `ordinal_position` — `2`

*What it is:* the column's position in the table. An attribute.

*What it licenses:* you can order columns, reconstruct a `CREATE TABLE`, and reason about
physical layout.

*What it does not license:* nothing about the data, and — because it was once in the key and was
removed — its value is not part of the entity's identity. Two rows with the same four key
components and different positions are the same column at two moments.

### `is_pii`, `classification`, `is_encrypted_at_rest` — `false`, `public`, `false`

*What they are:* two independent assertions and one classification, against a global versioned
vocabulary. `classification` is **kind** — what sort of data this is. `sensitivity`, the fourth
column that decision D45 adds, is **amount** — how much it matters. They are two columns because
they are two facts.

*Why `is_pii` survives alongside `classification` when it is derivable:* because **derivable is not
the same as authoritative.** A scanner that flags a column and a human who classified it
differently are two sources disagreeing, and the system reports the disagreement rather than
picking. Deriving it instead would have been a *subtractive* change — dropping a column is the one
kind of schema change the versioning decision refuses outright, because a value lives in exactly
one row and there is nowhere else for it to be.

*What this row licenses:* **nothing about encryption.** `is_encrypted_at_rest = false` on this row
is the column's own assertion, and D42 is explicit that a store-level "encrypted" can never
silently become a column-level answer. On a real query the answer to "is this encrypted at rest"
is a three-level inference — the column's assertion, else the store's, else unknown, with the
basis named — and this row only supplies the first rung.

*What this row does not license:* any statement of the form "this column is safe". Three `false`
and `public` values are three assertions about *this column*, made on 8 January 2021, about
encryption, classification and personal-data status. They are not a clearance.

### The temporal block

```
valid_from = 2021-01-08T00:49:40Z   valid_to   = \N
system_from = 2021-01-08T00:49:40Z  system_to  = \N
revision = 1                        operation  = assert
```

*What it licenses:* this belief has been held since the instant it was made, it covers a valid
interval that has not ended, and at any coordinate `V ≥ 2021-01-08T00:49:40Z` with `S ≥
2021-01-08T00:49:40Z` this column is in the estate. At a coordinate before either, it is
`not_yet_known` — which is a **named state**, and a real one, not a zero.

*What it does not license:* three things. It does not say the column exists now — "now" is the
corpus's declared `window_end` of `2027-04-25T23:59:59Z`, and the twin has held this belief across
the whole span without ever revisiting it, which is a different statement. It does not say the
column has ever held a *value*; the depth floor stops at the column, and asking what
`event_ts_001` contained in March is a question this corpus structurally cannot answer. And it does
not say anything at all about the other 1,099 columns in the file, 81 of which have no
classification recorded whatsoever.

### The row you have just read, summarised

You may conclude: *as of 8 January 2021, and as far as the twin's knowledge at any later point
stands, Acme had a column `event_ts_001` at position 2 of `hr.employee` in data store
`store-00000`, and the twin believed it held no personal data, classified as `public`, and was not
encrypted at rest.*

You may not conclude anything about whether that was true. You may not conclude it is true now.
You may not treat the estate's unencrypted personal-data columns as a complete set, because 81
columns in the same file are unassessed and the twin has declared a blind spot over exactly that.
And you may not conclude what the column's contents were.

That is a narrow conclusion, and it should be. Every widening of it available in this system costs
something the specification names and the sections above explain.

---

## IX. The two graphs

The corpus is the authority. Everything else is derived from it, and the derivation produces two
things that are frequently confused.

**The schema graph** answers: *what kinds of thing can exist, and how may they connect?* It is
independent of any one organization. In the shipped artifact it is a single GraphML file of 70,928
bytes holding 107 nodes — 38 entity types, 31 relationship types, 38 containment-spine entries —
and 112 `<edge>` elements, of which 29 are the spine itself, 31 declare a relationship's endpoint
shape, and the rest attach a type's own key and vocabulary to itself. Its eight
`<key for="graph">` declarations carry the coordinate and the model stamp:

```xml
<key id="schema_version" for="graph" attr.name="schema_version" attr.type="int"/>
<key id="schema_digest" for="graph" attr.name="schema_digest" attr.type="string"/>
...
<data key="schema_version">7</data>
<data key="schema_digest">e3db04f5d1cd7a90aba9a6a2</data>
<data key="as_of_coordinate_class">current</data>
<data key="identity_scheme">id-v1</data>
```

**The estate graph** answers: *what actually exists, at this coordinate?* In the small artefact it
is 7,110 nodes and 20,596 edges, sharded across 42 GraphML files, of which **6,519 nodes are
`present` and 591 are expected-dead ghosts** — entities that ended, which appear in the graph
because an edge still points at them, and which is exactly the population the third canonical
question is made of. At full scale: 995,727 nodes and 3,501,949 edges.

Both come from one pass over the corpus (D6). Neither is hand-maintained. Neither may drift from
the CSVs or from each other — and the check that they have not is not a promise but a run:
`check_sync` re-derives the fold from the corpus and compares CSV against Parquet against GraphML
across three coordinates with no sampling. **379 checks at small scale, 411 at full, 0 failed.**

### The invariance, and why your pipeline has to preserve it

The two graphs are byte-identical across scales. The schema graph is `sha256 dc493a57134b6489` at
7,110 estate nodes and at 995,727 estate nodes; the Parquet type, relationship and spine files are
identical too, and the `content_digest` matches. The corpus is 7,220,759 bytes at one size and
1,101,992,206 at the other — a factor of 153. The model does not move.

That is not a curiosity. It is the checkable form of "schema" and "estate" being two different
things rather than one thing filed twice, and the sentence that carries it is worth memorising:

> **A schema that grew with the data would be a schema describing the data.**

The failure mode this catches is specific and common. A pipeline that infers a column's type from
the values it sees, or a type list from the files it happens to find, or a vocabulary from the
strings it happens to encounter, will produce a schema that grows with every load. You will not
notice, because the schema will keep validating. But the model has stopped being a model and
started being a description of the last load, and the next question you cannot answer is *"what
kinds of thing exist?"* — because the answer now depends on what you happened to load.

So the test is a test you can run on your own output, and it is the single most useful check in
this document: **generate at two scales and compare the schema graphs. If they differ, something
in your pipeline is reading the data to decide the shape.**

### The third component, and why "as of today" is not a property of the data

There is a subtlety that will bite anyone who assumes a schema graph is timeless, and it is decision
D41 in one sentence: **the schema version rides transaction time, and it is a function of the
transaction instant.** An As-Of is a triple `(V, S, K)` where `K` is the schema version, and
`K = f(S)` — not `f(V)`, because **a model does not exist in the world.** `aws.account` is not a
thing; it is this twin's description of a kind of thing it can hold. A schema version therefore has a
know-date and no world-date, and the only coherent reading is that the know-date selects it.

The corpus's `manifest.json` stamps `schema_version: 7`. The authority is
`schema/schema_versions.json`, which holds seven versions for this organization, each with an
`effective_from`, an exact pinned pack set, a `core_contract` version and a `content_digest`. The
first becomes effective at `2026-01-01T00:00:00Z`; the seventh at `2026-09-30`. Four of the seven
carry `recorded_late: true` with a `recorded_by` naming the session that recorded them after the
fact — the mechanism working as designed, since a version history is the only thing that lets you
*prove* you never retro-adapted rather than assert it.

Two consequences follow, and the second is the sharp one. The first is that the March As-Of reads
through **the model the twin held in March**, and today's model would be a different thing. That is
what makes it answerable to ask whether this estate had AWS in March: the answer is not "no", it is
*the question could not be posed in March's model*, and the twin says so rather than answering. The
rule that enforces it is `schema.no_retroactive_type_introduction`, which fails the run if any row
of an introduced type has a `system_from` earlier than the `effective_from` of the version that
introduced it.

The second is the four-corner warning. When an As-Of is read through today's model — which is what
"as we now know it" means — it is safe **only because** the Compatibility Rule makes today's model
unable to say anything the earlier one could not. Within one window the schema may add a type, an
attribute, a relationship, a vocabulary value or a pack. It may not remove and may not reinterpret
anything. A change that would do either ends the observation window and begins a new corpus. So the
safety of the default historical question is conditional on a rule, and if you relax additive-only
the default becomes silent corruption of every artifact already in existence.

## X. What the data cannot tell you

This section is the one to read twice. Everything above describes what the data *is*; this describes
the boundaries of it, and the boundaries are where a reader gets hurt. They are stated here without
hedging, because a reader who is impressed and then misled is worse off than a reader who was never
impressed.

The founding statement, in its most uncomfortable form: **it cannot tell you the estate, only the
twin's belief in the estate.** No query, no model change and no amount of cleverness turns "what the
twin believes" into "what is true". That gap is not a bug a later ticket closes; it is the
difference between a record and the world, and every system that claims otherwise is making a claim
about the world on the strength of a belief.

### Every claim is currently capped at `claim_strength: unknown`

This is measured, not promised. The vertical slice runs the four canonical questions against the
real corpus at two As-Of classes and publishes the answers in `slice/out/questions.json`. All four
come back at the bottom rung, in both classes:

| | Q1 hosts | Q2 reach | Q3 departed admins | Q4 PII unencrypted |
|---|---|---|---|---|
| as known now | `unknown` | `unknown` | `unknown` | `unknown` |
| as thought then | `unknown` | `unknown` | `unknown` | `unknown` |

And each answer says what it is not allowed to say:

```json
"complement_licensed": false,
"sentences_unavailable_below_this_rung": ["safe", "none", "no", "all", "compliant"]
```

That is the mechanism working, not a limitation being apologised for. The claim strength is a
five-rung ordered lattice — `observed`, `observed_within_declared_gap`, `bounded`, `unbounded`,
`unknown` — and it is deliberately not called a *score* and deliberately not called *confidence*
(the word already belongs to `observation.confidence`, which is a per-finding attribute, and
naming collision is a real defect). What a lattice gives you that a number cannot is a rung below
which a *kind of sentence* becomes unavailable, and that can be enforced in code. A complement —
"no host was unpatched" — is assertable only at the top rung and only over a **named Declared
Universe**. Below that the answer enumerates and the words *safe*, *none*, *no*, *all* and
*compliant* are not available to it.

Why the gate says `unknown` is worth reading, because the reason is not "not enough data" but a
distinction most systems do not draw:

> *A Claim Strength describes an OBSERVATION, and a path that cannot run is not a coverage gap over
> the world but a gap in the twin. The coverage layer is not permitted to supply a rung for a
> computation that did not happen.*

The four answers are capped by paths the traversal *refused* — Q1 refused
`reachability_by_attribute` and `software_exposure`; Q3 refused all three of its paths; Q4 refused
`network_path`. A question that did not run is not a question with a weak answer. It is not a
question with an answer.

### A coordinate before the first model refuses by name

An As-Of whose transaction instant precedes the first recorded schema version has **no** `K`. It
does not have an empty one, and it does not inherit today's. The fold raises, and the message is
the mechanism working:

```python
raise FoldError(
    f"no schema version in force at system time {s}; the earliest recorded version "
    f"becomes effective at {self.version_history[0].get('effective_from')!r}. "
    f"A model has transaction time, so this is unanswerable rather than empty."
)
```

Read the last clause carefully. **A model that did not exist cannot say "no" about anything.**
Falling back to the manifest's version — which is correct at exactly one coordinate, the corpus's
own `window_end` — is the "every past As-Of is stamped with today's model" defect, and the
specification records it as a live one.

### Absence is a named state, and a row count is never the answer

This is the section that matters most to anyone planning a query.

A gap in the twin's knowledge has a name. It is never a zero and never an empty result set. The
fold's vocabulary:

| State | What it means | Defect? |
|---|---|---|
| `present` | an assert is selected at (V, S) | no |
| `ended` | a retract is selected and no assert — the thing existed and ended | **no — valid state** |
| `retrospective_gap` | the twin held beliefs at S and none of them covers V — we can no longer tell you | **no — valid state** |
| `not_yet_known` | every row of this entity post-dates S — the twin had not got to it | on the *edge* axis only |

Two of these are routinely mistaken for errors and are not. `ended` is expected-dead: a reference
to something real and gone, which is precisely the rows the departed-privilege question needs.
`retrospective_gap` is the recorded price of bitemporality, and it is the one most often
over-read as a bug.

The word that was deleted is the one to know about. **`absent` is not a state.** It was a *union*
of two of the four, and every reader of it read the union as one thing — which is the entire
failure this section is about, committed by the mechanism that was naming it. "We believed it and
we no longer cover this" and "we had not learned of it yet" have different evidence and different
remedies: the first needs a record somebody superseded, the second needs a record somebody wrote.
They are the same empty answer if you collapse them.

### Completeness is a set of declared regions, never a number

No figure in this twin is a bare percentage, and the reason is worth internalising as a principle
rather than a rule:

> A completeness figure is admissible only if its denominator was produced by a named observation
> the twin can point at. A figure whose denominator is the twin's own belief about the world is not
> a measurement, it is a restatement.

*"We have 94% coverage"* divides the things we found by the things that exist, and the twin does
not know the second number. So the ratio is either circular or invented, and the interesting cases
are the ones where somebody wrote it down anyway.

What is admissible instead: a `(numerator, denominator, channel pair, coordinate)` tuple, and only
where numerator and denominator come from *different* channels — a discovery sweep against an
inventory of record. One rule earns its keep by doing exactly that, and it is the only rule in the
run that can say a ratio at all:

> `506 of 736, channel pair (register of record, aggregate inventory) at
> (2027-04-25T23:59:59Z, 2027-04-25T23:59:59Z). NO BAND IS ASSERTED and none should be: the
> denominator here is the twin's own...`

Completeness is applied **per region and per attribute class**, not globally, and the second axis
is the one that is easy to miss. Two of the four canonical questions are damaged by *attribute*
blindness, and no entity-level mechanism sees it: "…and who owns them" is completeness of required
*detail*, not of entities, and an entity present with its ownership unrecorded is not a covered
entity. So an attribute class is a region, subject to the same declaration obligation as a subnet.

And the rule that keeps the two honest: **a region with no observing channel is legal only with a
`documented_exception`, and an exception is an acceptance rather than a permission.** It carries a
named owner, an acceptance date and a reason; it changes no rule, suppresses no check, buys no rung;
it appears on the answer envelope; and it **expires unless re-affirmed on every profile revision**.
An organization that cannot satisfy a policy rule must be told, not accommodated — a rule that is
optional is not a rule.

There is a third window, and it must never be declared. The **observation window** (when the twin
could have learned something) and the **model window** (when the model was stable) are both finite
and both on transaction time — and in this repository they **overlap without either containing the
other**: the model window is `[2026-01-01, 2027-06-30)` and the corpus's is
`[2026-01-01, 2027-04-25]`, so nine months have a model and no estate. The **world window** — the
span of *valid* time the twin claims to cover — has no owner artefact and no key to declare it in,
because a valid-time extent is a completeness claim whose denominator is the twin's own belief
about the world. Declaring one fails the run.

And the hard limit, stated rather than worked around, and it is the sentence I would put on the
wall:

> **The twin cannot warn you about a gap it did not know it had, at a coordinate where it did not
> know it. The only remedy is to change which coordinate you ask at.**

### A qualified name resolves to a set, and the cardinality is part of the answer

`hr.employee.ssn` is not an identifier. It is a query, and it answers in every environment that
has one. Nothing anywhere says that a production `hr.employee.ssn` and a staging one are the same
field, and they may hold different types, different classifications, different values and
different owners. So the traversal returns a **set**, and how many is part of the answer rather
than a defect to be smoothed over. The fixture makes it concrete:

```
# data/fixtures/column_resolution/.../prod/hr/employee
employee_id,full_name,ssn
EMP-004821,Priya R. Raman,412-55-0199

# .../stg/hr/employee
employee_id,ssn
EMP-004821,XXX-XX-4471
```

Same qualified name. Two stores. Real national identifiers in one, redacted placeholders in the
other, different `is_pii`, different `is_encrypted_at_rest`. **De-duplicating them would be actively
wrong** for the fourth canonical question, because the same field in two environments has different
encryption and different reachability — and that difference *is* the finding. There is no preferred
store and no tie-break in the core; a single answer is admissible only when the declared universe is
one store, and the ways to narrow are all declared attributes.

### One security rule computes the wrong quantity, and it was left that way on purpose

I am going to state this one flatly, because a data file that hides it is worse than a data file
that omits the data.

There is a rule in the catalogue, `security.public_certificate_expiring_within_notice_window`. Its
title is *"A publicly-trusted certificate valid at the As-Of but inside the renewal notice
window"*, it has a 30-day operational parameter, and it is a good idea. What it computes is **the
age of the interval** — `assert: age_at_least`, `start_column: valid_from` — and it renders its
findings as *"certificate validity remaining is N day(s) old at the As-Of, at or beyond the
declared threshold of 30 day(s)"*.

Which means it fires on certificates with **1,905 days of validity left** and is silent on any
inside 30. Seventeen findings in the small corpus. The message is self-contradictory — "remaining
is 1905 day(s) old" — and the rule is doing the exact opposite of what its title promises.

It was not patched, and the reason is worth more than the fix:

> **A rule whose direction is ambiguous is exactly where a silent flip is worse than a loud wrong
> answer, and the fix belongs with whoever owns the catalogue's arithmetic.**

The severity is `report`, which is not a grade: it can never reject a run, and a rule whose firing
is the deliverable carries `report` so that a corpus which produces findings is not thereby
failing. So the defect is contained, and it is *loud* — 17 rows of nonsense that a reader will see
and be confused by.

**If you consume these findings, ignore this rule.** That is the published advice in the data
repository and it is the right advice. Do not "fix" it by flipping the comparison in your pipeline
without deciding what it was supposed to mean, because the two directions have opposite failure
consequences and only one of them is a false all-clear.

### And the questions this system has not answered

Three concrete demonstrations, because abstract honesty is cheap.

**Q3 returns nothing, and would return thirteen living staff if one character were different.**
The question is *who holds standing administrator despite having departed*. It answers zero rows on
all three of its paths, and the repository records that a missing `classify:` in the query would
have made it return **thirteen members of staff who had not left**. That is a false all-clear in
the most dangerous direction available to this system: not "we found nothing", but "we found
nothing, and the thing we would have found is exactly the thing you were afraid of". A different
defect in the same run found one grant authorised **254 days after its authoriser's employment
ended**.

**The four questions had never been answered by anything.** When the vertical slice finally ran
them, `slice/questions.py` turned out to carry four independent fatal defects **stacked**, so the
first always stopped the run before the second was reached. Nothing could tell, because the stage
that would have run that module had died earlier on a keyword the fold had renamed, and was not
re-run after the fix. Four questions, zero answers, and a suite that reported nothing about it.

### A summary you can hold

The data cannot tell you whether any of it is true; what it does not cover, in numbers rather than
in named declared regions; what a cell held in the past; whether a name is one thing or several;
anything at all at a coordinate before the model existed, which it refuses by name; or anything
phrased as a complement, at the rung every answer currently occupies.

It can tell you, precisely and reproducibly: **what this system believed, about these things, over
these intervals, as of these instants — and where it has said it does not know.** That is a narrower
promise than a spreadsheet makes, and it is a promise a machine can keep.

---

## XI. Closing

### What you can now do that you could not before

You can open `compute_node.csv`, pick any row, and say out loud what it asserts, over what interval,
as of when — knowing that the machine and the claim about it are two different objects, and that the
claim is the one on disk. You can read the six timestamps and know which question you are being
asked: a `valid_to` closed in March and a `system_from` in 2026 do not mean what a single "updated"
column would mean, and the difference is the point of the format.

You can read `\N` and know it is a statement about the *twin*, not the estate — and you can name
the false all-clear a NULL-coercing loader would produce in the PII question, with a count: 81 of
1,100 columns carry no classification, and a false-default reader turns all 81 into clean columns.
You can recompute any entity id from three strings, and you know a collision would fail loudly
rather than be disambiguated, that an id is never reused, and that a renamed table is a new table
linked by `succeeds`.

You can tell a schema graph from an estate graph, and you know the one-line test your own pipeline
must pass: generate at two scales, compare the schema graphs, and if they differ, something is
reading the data to decide the shape. And you can read a completeness claim and know that a
percentage in it is either a measurement someone can trace to a named observation, or a
restatement of the twin's own opinion wearing a decimal point.

### The sentence that carries the philosophy

Every idea in this document reduces to one failure mode, and the project has a name for it:

> **A state the model cannot name gets reported as absence, and absence reads as a clean result.**

Not "has caused". Not "can cause". **Has.** By the repository's own count this map has hit it
eleven times, and the count lives in the project state file rather than in a design document
because it grew every time something ran. Here are three, and they are three different mechanisms.

**The tombstone shape.** D19's end-of-life encoding closed the predecessor in transaction time. The
contract was correct, every invariant held, and every entity that had ended was absent from the
estate at every As-Of before its end — so a question about last March silently omitted every
decommissioned host. The query returned rows; the coverage claim was untouched; the hosts that
vanished were precisely the ones that should still have been there. Found by running the fold, and
the fold *could not have found it*: a closed `system_to` does nothing but remove a row from
selection. That
is why the fix is a rule about *which operation* does the closing, and why that rule found three
real violations in hand-built fixtures the day it was written.

**`is_pii` false by default.** The corpus had no unassessed state for a boolean, so a column nobody
had ever looked at came out `false`, which is the same as *not personal data*. The security layer
built on it would have produced a clean report about a field it had never been told about. Found
not by review but by asking where "not PII" came from.

**Three windows, none of them nested.** The observation window and the model window are both
declared, both finite, both on transaction time, and they overlapped without either containing the
other — nine months had a model and no estate, nine months had an estate and no model. Nothing in
the twelve existing suites could see it, and the lesson is now recorded: **nothing had ever named
the two as two.** The words were the defect.

The through-line is not caution. Every one of these was a place where a *state* existed that the
system had no word for, and the only available move for an unnameable state was to return nothing —
and returning nothing, to a security practitioner, is indistinguishable from having looked and found
the estate clean. The fix in every case was the same: **name the state, and the mechanism has
somewhere to put it that is not zero.** `not_yet_known`. `retrospective_gap`. `expected_dead`.
`undetermined`. `unknown`. `retract`. `blind_spot`. Each is a piece of vocabulary that exists so a
real condition does not have to be rendered as an absence.

And the discipline that produced all of them is the only instruction here that matters
operationally: **every claim above was found by running something.** Not by reading the
specification, not by review, not by a checklist. The specification said the right things in every
one of these eleven cases and the system was still wrong. That is not an argument against writing
decisions down; it is the argument for treating them as the *thing under test* rather than the
thing that settles it.
