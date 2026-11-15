-- Building the canonical transactions view from a hypothetical ledger.
-- ledger_entries, accounts and customers are invented names; map them to yours.
-- counterparty_new is computed with a window over strictly earlier rows, so it
-- only uses information available at the time of each entry.
CREATE OR REPLACE VIEW transactions AS
WITH base AS (
  SELECT
    e.entry_id                               AS id,
    CAST(EXTRACT(EPOCH FROM e.posted_at) AS BIGINT) AS ts,
    a.customer_id,
    e.account_id,
    a.product_type                           AS account_type,
    LOWER(e.entry_kind)                      AS txn_type,
    CASE WHEN e.amount_minor > 0 THEN 'in' ELSE 'out' END AS direction,
    LOWER(e.rail)                            AS channel,
    ABS(e.amount_minor)                      AS amount_cents,
    e.counterparty_key                       AS counterparty_id,
    LOWER(e.counterparty_class)              AS counterparty_type,
    e.return_reason                          AS return_code,
    e.branch_or_atm                          AS location_id,
    CAST(EXTRACT(EPOCH FROM a.opened_at) AS BIGINT) AS account_opened_ts,
    DATE_PART('year', AGE(e.posted_at, c.birth_date)) AS customer_age,
    a.credit_limit_minor                     AS credit_limit_cents
  FROM ledger_entries e
  JOIN accounts a ON a.account_id = e.account_id
  JOIN customers c ON c.customer_id = a.customer_id
)
SELECT
  b.*,
  CASE
    WHEN b.counterparty_id IS NULL THEN NULL
    WHEN COUNT(*) OVER (
      PARTITION BY b.account_id, b.counterparty_id
      ORDER BY b.ts, b.id
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) = 0 THEN 1
    ELSE 0
  END AS counterparty_new
FROM base b;
