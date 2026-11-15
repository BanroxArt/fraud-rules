# Examples

- `custom-rule/ck-901-new-account-check-deposits.yaml`: a rule kept outside the bundled pack, loaded with `--rules`. It follows the FinCEN 2023 mail theft alert's "new customer whose account seems to be used only for check deposits".
- `views/transactions_view.sql`: one way to build the `transactions` view, including the point-in-time `counterparty_new` flag, from a hypothetical ledger table. Column names on the left side are invented; map them to yours.

```sh
python -m fraudrules --rules examples/custom-rule list
python -m fraudrules --rules examples/custom-rule sql --dialect postgres
```
