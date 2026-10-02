# 9. Replay eight weeks: the threshold simulator

**The situation.** You're about to choose a threshold strategy for a daily orders feed. Scenario 4 showed one day of verdicts, but the real question is about weeks: which strategy would have caught last month's incidents, and how many false alarms would it have raised in between? Testing that on production means waiting two months.

The simulator answers it in seconds. It replays eight weeks of daily loads, with problems injected on known days, through the real Sentinel pipeline, then scores every strategy.

**You'll learn:** how each strategy behaves over time, how to read a caught/missed/false-alarm scorecard, and how to tune a policy by experiment instead of by guesswork.

```bash
uv run python -m examples.simulate                    # loads into a CSV file read by DuckDB
uv run python -m examples.simulate --source postgres  # or mysql, mongodb
```

---

## What happens on each simulated day

1. **Generate the day's orders.** About 1000 on weekdays and 550 at weekends, growing 0.3% a day, with ±3% noise and about 0.5% of customer ids missing.
2. **Load them** into the chosen source, replacing the previous day's.
3. **Validate** with `policies/simulated_orders.yaml`, through the same code path `sentinel validate` uses, with Sentinel's clock set to that day. Each run is stored, so the adaptive strategies read their history from the store with their real queries.

**Days 1–14 are a warm-up.** Every rule runs on a permissive static threshold to build history, which is the recommended cold start for a new rule. From day 15 the real policy takes over, and four problems are injected:

| Problem | What the data looks like | Which rules should catch it |
|---|---|---|
| Duplicate load | Volume +60% | Volume rules |
| Partial load | Volume −55% | Volume rules |
| A weekday at weekend volume | A weekday arrives with ~550 rows | Only a rule that knows weekdays from weekends |
| Null spike | 8% of customer ids missing | Null-rate rules |

## The policy under test

`policies/simulated_orders.yaml` has eight non-blocking rules, so every strategy is evaluated every day:

| Rule | Metric | Strategy |
|---|---|---|
| `volume_static` | row count | `static`, min 600 |
| `volume_pct_of_mean` | row count | `percentage_deviation`, ±25% |
| `volume_statistical` | row count | `statistical`, ±3σ |
| `volume_median_mad` | row count | `median_mad`, ±3 MAD |
| `volume_seasonal` | row count | `seasonal`, ±3σ per weekday |
| `nulls_static` | null rate of `customer_id` | `static`, max 2% |
| `nulls_statistical` | null rate of `customer_id` | `statistical`, ±3σ |
| `nulls_median_mad` | null rate of `customer_id` | `median_mad`, ±3 MAD |

## What you'll see

```text
Simulated 42 evaluated days into postgres (22 Aug to 02 Oct).

Injected anomalies:
  Sun 30 Aug  duplicate load (+60%)  (926 rows)
  Mon 07 Sep  partial load (-55%)  (503 rows)
  Wed 16 Sep  weekday at weekend volume  (606 rows)
  Sat 26 Sep  customer_id nulls 8%  (625 rows)

rule                  strategy                caught  missed  false alarms
volume_static         static                     1/3       2             4
volume_pct_of_mean    percentage_deviation       2/3       1            22
volume_statistical    statistical                0/3       3             0
volume_median_mad     median_mad                 2/3       1            11
volume_seasonal       seasonal                   3/3       0             5
nulls_static          static                     1/1       0             0
nulls_statistical     statistical                1/1       0             0
nulls_median_mad      median_mad                 1/1       0             0

Timeline (# caught  x false alarm  ! missed  . quiet; ^ = anomaly day)
                      SSMTWTFSSMTWTFSSMTWTFSSMTWTFSSMTWTFSSMTWTF
                              ^       ^        ^         ^
volume_static         xx.....x!.....x.#........!................
volume_pct_of_mean    xx.....x!.....xx#..x.xx..#..xxxxxxxxxxxxxx
volume_statistical    ........!.......!........!................
volume_median_mad     xx.....x!.....xx#....xx..#..xx.....xx.....
volume_seasonal       ..x..x.x#x......#........#........x.......
nulls_static          ...................................#......
nulls_statistical     ...................................#......
nulls_median_mad      ...................................#......
```

The dates end today, so yours will differ. The scorecard is identical for every `--source` and for the default seed, which `tests/integration/test_simulator.py` checks.

## Reading the scorecard

- **caught**: the rule failed on an anomaly day meant for it.
- **missed**: it passed on one of those days.
- **false alarms**: it failed on a normal day. Each one wakes someone up for nothing, so this column matters as much as *caught*.
- **The timeline** has one column per evaluated day (the letters are weekdays) and shows *when* things happened. `^` marks the anomaly days.

What it tells you about each volume strategy:

| Strategy | Result | Why |
|---|---|---|
| `seasonal` | 3/3, 5 false alarms | The only one that catches the weekday at weekend volume. Its false alarms cluster in the first week (`x..x.x` at the start), when each weekday had only two past values and its range was very narrow. |
| `statistical` | 0/3 | The weekday/weekend swing makes its range so wide that even a 60% jump fits inside. No false alarms, but it misses everything. |
| `percentage_deviation` | 2/3, 22 false alarms | It compares with the average of *all* days, so it fires on weekends. As volume grows, the average lags behind and it starts firing on weekdays too (the run of `x` at the end). |
| `median_mad` | 2/3, 11 false alarms | It locks onto the weekday level and treats most weekends as anomalies. |
| `static` | 1/3, 4 false alarms | A fixed floor of 600 can't move with growth or the weekly pattern. |

**The null rate has no weekly pattern**, so all three null-rate strategies catch the spike with no false alarms. The strategies only diverge when the data has structure. Choose a strategy for the *shape* of your metric, not by default.

## Tune by experiment

Edit `policies/simulated_orders.yaml` (or pass flags), rerun, and compare scorecards.

- **Give `seasonal` more history:** `--warmup 28 --days 70`. With four past values per weekday it catches all three volume anomalies with **zero** false alarms. Its earlier false alarms came only from thin history.
- **Narrow `statistical`:** set `n_sigma: 1.5` on `volume_statistical`. It now catches the partial load with one false alarm, but still misses the duplicate load and the weekday gap: a narrower range doesn't fix an average that ignores the weekly pattern.
- **Run longer:** `--days 112`, and watch `percentage_deviation` get worse as growth outpaces its average.
- **Require more history:** raise `seasonal`'s `min_history` to 4. With the default 14-day warm-up the simulator stops and says there isn't enough history, just as a real run would. Add `--warmup 28` to fix it.
- **Change the luck:** `--seed 3` generates different daily noise. The anomalies stay at the same points in the window, so scorecards remain comparable.
- **Test your own policy file:** `--policy path/to/policy.yaml` replays any policy written against the same data (a `row_count` metric and a `customer_id` column).

Rule names are history keys. If you rename a rule, its history starts from scratch, and an adaptive rule without enough history stops the run.

## See it in the dashboard

The simulated runs stay in the store as `simulated_orders_<source>`, for example `simulated_orders_duckdb`.

```bash
uv run sentinel history simulated_orders_duckdb --limit 60
uv run streamlit run dashboard/app.py
```

In the dashboard, choose *Last 30 days*, select the dataset, and pick a rule under **Metric Trends**. The chart shades the range the rule allowed on each day and marks its failures in red. For `volume_seasonal` you can watch the range follow the weekly rhythm; for `volume_statistical`, how wide it is.

For a purely statistical comparison on more scenarios, without the pipeline, see the [Threshold Strategy Evaluation](../experiments/threshold-strategy-evaluation.md).

**Next:** [10. History and the dashboard](10-history-and-dashboard.md)
