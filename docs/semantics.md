# Semantics

The Python evaluator in `fraudrules.pyeval` is the definition. The SQL compiler and the Sigma emitter are tested against it; this page states what it does.

## Rows and keys

- A row whose key has a null in any key column never matches anything: it is not an anchor with members, not a member, not a sequence step. SQL gets this for free from `=` on nulls; Python checks it explicitly.
- A hit is reported as `(rule_id, anchor_table, anchor_id)`. For an aggregate, every anchor whose window satisfies `having` is a hit, so a burst of five failed logins against a threshold of five produces one hit and a burst of seven produces three. Deduplicate per key and time bucket downstream if you want one alert per episode.

## Windows

- Aggregate windows are `(anchor.ts - window, anchor.ts]`: the lower bound is open, the upper bound closed. Rows with the anchor's own timestamp are inside, in both directions, so two rows at the same second see each other.
- Without a window, the lower bound is open-ended: all rows up to and including the anchor's timestamp. That is the point-in-time count the synthetic identity linkage rules use.
- An anchor with no members is not evaluated, so `having` can never fire on absence.

## Sequences

- Step rows must have strictly increasing `ts` in step order and the anchor's `ts` is strictly greater than the last earlier step. Two events in the same second do not form a sequence; clocks that coarse should not be trusted for ordering.
- The first step must be inside `(anchor.ts - within, anchor.ts)`.
- Existence is all that matters: one chain is enough, and the evaluator finds it greedily (earliest qualifying row for each step), which is optimal because every constraint relates a step either to the previous step's time or to the anchor.

## Nulls

- Every comparison involving a null is false: `=`, `!=`, `<`, `IN`, `NOT IN`, field-to-field.
- `not` is two-valued: true exactly when its operand is not true. So `{not: {field: payee_id, eq: p1}}` is true for a null `payee_id`, while `{field: payee_id, ne: p1}` is false. The SQL compiler writes `NOT COALESCE(..., FALSE)` to get this; the Sigma emitter writes `ne` as `not (x: v or x: null)`.
- Aggregates skip nulls: `sum`, `min`, `max` of no non-null values is null (and every comparison with it is false); `count_distinct` does not count null; `count` counts rows.

## Arithmetic

Integers only. `times` multiplies; there is no division. `plus` adds a constant to a column of the same row. SQL `SUM` over 64-bit integers widens in every supported engine, so there is no overflow at realistic amounts.

## Sigma

Sigma's string comparison is case-insensitive. The data model fixes every vocabulary column (`event_type`, `outcome`, `channel` and so on) to lower case, and on data that follows it the Sigma output and the other backends agree; the test suite only generates lower-case vocabulary for that reason. A test documents the difference on upper-case input.
