# Contributing

New rules, better thresholds and bug reports are welcome. For a new rule kind or a change to the data model, open an issue first: both affect every backend and every user's views.

## Setup

```sh
python -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[dev]'
make check
```

`make check` runs ruff, the content lint in `scripts/check.py`, mypy in strict mode, pytest (including the Hypothesis agreement tests across backends) and confirms `compiled/` is current. CI runs the same on Python 3.11 to 3.13.

## Adding or changing a rule

Follow [docs/spec.md](docs/spec.md#writing-a-new-rule). In short:

- Primary sources only: the regulation, the FinCEN advisory, the FFIEC or agency guidance, the Nacha rule. Vendor blogs and marketing reports are not sources here. Say in `note` what in the source supports the rule.
- Add a positive and a near-miss scenario to `fraudrules.synth.SCENARIOS`. The near miss should differ from the positive in exactly one condition, and the commit message should say which.
- Regenerate `compiled/` with `python scripts/build_compiled.py`.
- If you change a default threshold, explain why in the commit message. "Fewer alerts" alone is not a reason; "the benign pattern in false_positives item 2 sits at 3 to 4 senders" is.

## Changing a backend

The Python evaluator defines the semantics ([docs/semantics.md](docs/semantics.md)). A change to the SQL compiler or the Sigma emitter must keep `tests/test_equivalence.py` passing. Never loosen a property test to get a change through; when Hypothesis finds a disagreement, keep the failing input as a plain regression test in `tests/test_semantics.py`.

## Things we will not merge

- Real customer, account or transaction data in any form, including in tests and examples. Use `fraudrules.synth` or hand-made rows.
- Code or rule logic copied from a commercial product.
- Wording that presents the pack as legal advice, as satisfying a regulatory requirement, or as certified by anyone.

## Commit messages

Short imperative subject in lower case (`mu-001: exclude returns from inflow`), a blank line, then why.

## Conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1). Reports go to opensource@banrox.com and are read by the maintainers only.
