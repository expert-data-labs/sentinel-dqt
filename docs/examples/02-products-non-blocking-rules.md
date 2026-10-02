# 2. Track a problem without blocking: `products`

**The situation.** The catalog team knows some products have no description. It's worth fixing, but a missing description shouldn't stop the nightly pipeline the way a missing price would. You want the problem recorded and visible, not enforced.

**You'll learn:** non-blocking rules, the difference between a rule's result and the run's result, and how Sentinel turns a failure into a prioritized incident.

```bash
uv run sentinel validate products
```

---

## The data

`data/products.csv`: 30 products. Every SKU is unique and every price is filled in, but **6 products have an empty description** (20%).

## The policy

`datasets/products.yaml` marks the dataset `criticality: low`. The policy:

```yaml
dataset: products
rules:
  - name: row_count
    type: row_count
    threshold: {strategy: static, min: 10}

  - name: sku_unique
    type: uniqueness
    column: sku
    severity: high
    threshold: {strategy: static, max: 0}

  - name: price_not_null
    type: null_rate
    column: price
    severity: high
    threshold: {strategy: static, max: 0}

  - name: description_not_null
    type: null_rate
    column: description
    severity: info               # the lowest severity
    blocking: false              # record it, but don't fail the pipeline
    threshold: {strategy: static, max: 0.05}     # up to 5% missing is fine
```

The first three rules are hard requirements, so they stay blocking. `description_not_null` is the "track, don't enforce" rule.

## What you'll see

```text
Dataset: products
Run ID:  a64b34bc-0a9a-4858-9533-2b848eb054b0
Result:  PASS

  ✓ row_count  actual=30  expected: row_count >= 10
  ✓ sku_unique  actual=0  expected: sku_unique <= 0
  ✓ price_not_null  actual=0  expected: price_not_null <= 0
  ✗ description_not_null  actual=0.2  expected: description_not_null <= 0.05
      priority=WARNING score=33.0  Dataset criticality: LOW
```

Exit code `0`, and still an incident. Both are correct:

- **The rule failed**, so it shows ✗ and an incident is recorded. It appears in `sentinel history`, the dashboard's incident list, and the failure counts.
- **The run passed**, because `Result` and the exit code only consider blocking rules. Your scheduler sees success and carries on.

Use this pattern for a check you've just introduced and want to watch for a while, or for a quality goal the data owner is still working towards. When you're ready to enforce it, remove `blocking: false`.

## Why WARNING, if severity is info and criticality is low?

Every incident gets a 0–100 score from five weighted parts. Priority follows from the score: 75+ is CRITICAL, 50+ HIGH, 25+ WARNING, otherwise INFO.

| Part | Weight | This incident | Points |
|---|---|---|---|
| Severity of the rule | 30% | info → 10 | 3.0 |
| Criticality of the dataset | 30% | low → 10 | 3.0 |
| How far past the limit | 20% | 0.2 is 3× past the 0.05 limit → maximum 100 | 20.0 |
| How often it has failed before | 10% | first time → 10 | 1.0 |
| Confidence in the signal | 10% | static threshold → 60 | 6.0 |
| **Score** | | | **33.0 → WARNING** |

Severity and criticality are both as low as they go, but the value is far outside its limit, and that alone is enough to lift the incident to WARNING. The full model is in [Incident Prioritization](../components/prioritization.md).

The CLI and dashboard show only the first reason. To see all five, with the score parts and the threshold details, inspect the run (the latest one by default, or pass a Run ID):

```bash
uv run python demo/inspect_run.py a64b34bc-0a9a-4858-9533-2b848eb054b0
```

```text
- description_not_null: FAIL  value=0.2  expected: description_not_null <= 0.05
    severity=info  blocking=False  threshold={"method": "static", "actual": 0.2, "min": null, "max": 0.05}
    INCIDENT priority=WARNING score=33.0
    components={'severity_score': 10.0, 'criticality_score': 10.0, 'deviation_score': 100.0, 'frequency_score': 10.0, 'confidence_score': 60.0}
      · Dataset criticality: LOW
      · Validation severity: INFO
      · Deviation: 300% of the tolerance edge (strategy: static)
      · Failure frequency: first-ever recorded evaluation of this rule
      · Anomaly confidence: 0.60 (static, n=n/a)
```

The stored run's status is `FAIL`, because one of its rules failed. Only the exit code ignores non-blocking rules, so `sentinel history products` lists this run as `FAIL` with `failed: description_not_null`.

## Try it

- **Make it blocking:** delete `blocking: false` and rerun. The same ✗, but now `Result: FAIL (blocking)` and exit code `2`.
- **Fill in descriptions:** add text to all but one of the six empty descriptions (1 of 30 = 3.3%, under the 5% limit). The rule passes and no incident is created.
- **Raise the stakes:** set `criticality: high` in `datasets/products.yaml`. The same failure now scores 51.0 → HIGH, because the criticality part goes from 3 to 21 points.

**Next:** [3. A broken load](03-orders-broken-load.md)
