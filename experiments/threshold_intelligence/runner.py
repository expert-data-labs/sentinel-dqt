"""Scores every threshold strategy against every synthetic scenario.

Writes docs/experiments/threshold-strategy-evaluation.md. Run from the repo
root:

    python -m experiments.threshold_intelligence.runner

Output is reproducible byte for byte. Calls ``evaluate()`` directly, without
rules, data sources or persistence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from experiments.threshold_intelligence.scenarios import ALL_SCENARIOS, ScenarioPoint
from sentinel.domain import Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdStrategy
from sentinel.thresholds.median_mad import MedianMadStrategy
from sentinel.thresholds.percentage_deviation import PercentageDeviationStrategy
from sentinel.thresholds.seasonal import SeasonalBaselineStrategy
from sentinel.thresholds.static import StaticThresholdStrategy
from sentinel.thresholds.statistical import StatisticalThresholdStrategy

_RESULTS_PATH = (
    Path(__file__).parents[2] / "docs" / "experiments" / "threshold-strategy-evaluation.md"
)


@dataclass(frozen=True)
class ConfusionMatrix:
    """One strategy's results on one scenario.

    ``skipped`` counts points the strategy couldn't judge yet (not enough
    history); they aren't counted as right or wrong.
    """

    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    skipped: int

    @property
    def evaluated(self) -> int:
        return (
            self.true_positives
            + self.false_positives
            + self.true_negatives
            + self.false_negatives
        )

    @property
    def false_positive_rate(self) -> float | None:
        """None when there were no negative cases (not the same as a 0% rate)."""
        denominator = self.false_positives + self.true_negatives
        return self.false_positives / denominator if denominator else None

    @property
    def false_negative_rate(self) -> float | None:
        denominator = self.false_negatives + self.true_positives
        return self.false_negatives / denominator if denominator else None


def evaluate_strategy(
    points: Sequence[ScenarioPoint], strategy: ThresholdStrategy, config: ThresholdConfig
) -> ConfusionMatrix:
    """Evaluate each point using all earlier points as history (expanding window).

    FAIL counts as flagged; PASS as not flagged. No built-in strategy returns
    WARN.
    """
    true_positives = false_positives = true_negatives = false_negatives = skipped = 0

    for index, point in enumerate(points):
        history = tuple(p.metric for p in points[:index])
        try:
            result = strategy.evaluate(point.metric, config, history)
        except InsufficientHistoryError:
            skipped += 1
            continue

        flagged = result.status is Status.FAIL
        if flagged and point.is_anomalous:
            true_positives += 1
        elif flagged and not point.is_anomalous:
            false_positives += 1
        elif not flagged and not point.is_anomalous:
            true_negatives += 1
        else:
            false_negatives += 1

    return ConfusionMatrix(
        true_positives, false_positives, true_negatives, false_negatives, skipped
    )


# One fixed config per strategy, used for every scenario (not tuned).
# static and percentage_deviation need explicit values; the rest are defaults.
STRATEGIES_UNDER_TEST: dict[str, tuple[ThresholdStrategy, ThresholdConfig]] = {
    "static": (
        StaticThresholdStrategy(),
        ThresholdConfig(strategy="static", params={"min": 800, "max": 1200}),
    ),
    "percentage_deviation": (
        PercentageDeviationStrategy(),
        ThresholdConfig(strategy="percentage_deviation", params={"max_deviation": 0.15}),
    ),
    "statistical": (
        StatisticalThresholdStrategy(),
        ThresholdConfig(strategy="statistical", params={"n_sigma": 3.0}),
    ),
    "median_mad": (
        MedianMadStrategy(),
        ThresholdConfig(strategy="median_mad", params={"n_mad": 3.0}),
    ),
    "seasonal": (
        SeasonalBaselineStrategy(),
        ThresholdConfig(strategy="seasonal", params={"n_sigma": 3.0}),
    ),
}


def run_all() -> dict[str, dict[str, ConfusionMatrix]]:
    """Run every strategy on every scenario."""
    return {
        scenario_name: {
            strategy_name: evaluate_strategy(points, strategy, config)
            for strategy_name, (strategy, config) in STRATEGIES_UNDER_TEST.items()
        }
        for scenario_name, points in ALL_SCENARIOS.items()
    }


def _format_rate(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


def _scenario_table(matrices: dict[str, ConfusionMatrix]) -> str:
    header = (
        "| Strategy | TP | FP | TN | FN | Skipped | FPR | FNR |\n"
        "|---|---|---|---|---|---|---|---|\n"
    )
    rows = "\n".join(
        f"| {name} | {m.true_positives} | {m.false_positives} | {m.true_negatives} | "
        f"{m.false_negatives} | {m.skipped} | {_format_rate(m.false_positive_rate)} | "
        f"{_format_rate(m.false_negative_rate)} |"
        for name, m in matrices.items()
    )
    return header + rows + "\n"


_SCENARIO_NARRATIVE: dict[str, str] = {
    "A_stable": (
        "30 stable days, no real anomaly anywhere. Every strategy is expected to pass "
        "everything -- the interesting number here is **false positives**, which should be "
        "0 across the board. Seasonal is the one exception: bucketing by day-of-week splits "
        "30 days into 7 buckets of only 4-5 points each, and that small a sample is itself "
        "enough to occasionally misjudge normal noise as out-of-bounds -- a real cost of "
        "seasonal bucketing (fewer points per comparison), not a bug, and a reason not to "
        "reach for Seasonal on data that isn't actually seasonal."
    ),
    "B_seasonal": (
        "6 weeks of a genuine weekday (~1000) / weekend (~500) pattern, all of it normal, "
        "plus one real anomaly (a Monday at 1300). This is the evaluation's central "
        "demonstration, and the numbers below are more textured than \"static bad, "
        "adaptive good\":\n\n"
        "- **Static** ([800, 1200]) flags every single weekend as a false positive (12 of "
        "them) -- it has no notion that ~500 is ever supposed to be normal.\n"
        "- **Percentage Deviation** is *worse*, not better: with no seasonality awareness "
        "and no tolerance for spread the way a standard deviation gives, its single blended "
        "baseline sits between the two clusters, so *both* weekdays and weekends routinely "
        "miss its narrow band -- 26 false positives, more than static.\n"
        "- **Statistical (global Mean/StdDev)** takes the opposite failure mode: mixing two "
        "genuinely different populations inflates its own standard deviation so much that "
        "its bounds balloon wide enough to swallow both clusters *and* the real anomaly -- "
        "0 false positives, but it's the one strategy that **misses the actual anomaly** "
        "(1 false negative). Quiet is not the same as correct.\n"
        "- **Median/MAD (global)** doesn't get dragged the way Mean/StdDev does -- but that "
        "same robustness means it locks onto the majority cluster (weekdays, 5 of 7 days) "
        "and rejects the minority cluster (weekends) almost as if it were a stream of "
        "outliers: 12 false positives, matching static almost exactly. Robust to a *rare* "
        "outlier is not the same property as aware of a *recurring* pattern.\n"
        "- **Seasonal** is the clear best result -- 2 false positives (both explainable by "
        "only having 4-6 samples in some buckets by this point) against 26 true negatives, "
        "and it's the only adaptive strategy that also **catches the real anomaly**.\n\n"
        "The takeaway isn't just \"seasonal beats static.\" It's that an adaptive strategy "
        "without a seasonality-aware baseline can fail in a *worse* way than a static one -- "
        "either by drowning out a real anomaly (Statistical) or by rejecting an entire "
        "legitimate recurring pattern (Median/MAD, Percentage Deviation)."
    ),
    "C_genuine_anomaly": (
        "The same stable history as Scenario A, plus one unambiguous spike (1800 against a "
        "baseline of ~1000). Every strategy correctly flags it (TP=1, FN=0) -- this scenario "
        "exists to confirm that going adaptive doesn't cost detection power on the easy case, "
        "not to differentiate the strategies from each other. Seasonal's one false positive "
        "is the same small-sample effect as Scenario A (it inherits the identical first 30 "
        "points), not something new to this scenario."
    ),
    "D_historical_outlier": (
        "A small worked history (1000, 1020, 980, 1010, 1005), then the "
        "same extreme value (5000) occurring twice in a row. The two occurrences aren't "
        "redundant -- they isolate a real failure mode:\n\n"
        "- **Statistical** catches the *first* 5000 (history is still clean: mean ~1003, a "
        "tight bound) but **misses the second** (the first 5000 is now inside its own "
        "history, and it alone drags the mean and standard deviation wide enough that a "
        "*repeat* of the same anomaly now falls within bounds) -- 1 true positive, 1 false "
        "negative.\n"
        "- **Median/MAD** catches both (2 true positives, 0 false negatives): one extreme "
        "value can shift a median by at most one rank position, so it never meaningfully "
        "widens the bounds the way it widens Mean/StdDev's.\n"
        "- **Static** and **Percentage Deviation** also catch both here, for a much simpler "
        "reason: 5000 is such an extreme value that a fixed bound and a mean-relative "
        "percentage both reject it regardless of the one earlier outlier -- this scenario "
        "isn't evidence those two are robust in general, only that this particular anomaly "
        "is large enough that it doesn't need robustness to be caught.\n"
        "- **Seasonal** is skipped entirely (7 for 7): 7 consecutive days means every "
        "weekday appears exactly once, so no bucket ever has a second occurrence to compare "
        "against. Seasonal isn't wrong here -- it's inapplicable, and correctly declines to "
        "guess (InsufficientHistoryError) rather than fabricate a verdict from zero same-"
        "weekday history."
    ),
}

_SCENARIO_TITLES: dict[str, str] = {
    "A_stable": "Scenario A -- Stable Data",
    "B_seasonal": "Scenario B -- Normal Seasonal Variation (+ one genuine anomaly)",
    "C_genuine_anomaly": "Scenario C -- Genuine Anomaly",
    "D_historical_outlier": "Scenario D -- Historical Outlier",
}


def render_markdown(results: dict[str, dict[str, ConfusionMatrix]]) -> str:
    sections = [
        "# Threshold Strategy Evaluation\n",
        "Generated by `experiments/threshold_intelligence/runner.py` "
        "(`python -m experiments.threshold_intelligence.runner` from the repo root "
        "regenerates this file). Every scenario is seeded (see `scenarios.py`) and every "
        "strategy below uses one fixed configuration across all four scenarios -- nothing "
        "here is tuned per scenario to flatter a particular result.\n",
    ]
    for scenario_name, matrices in results.items():
        sections.append(f"## {_SCENARIO_TITLES[scenario_name]}\n")
        sections.append(_SCENARIO_NARRATIVE[scenario_name] + "\n")
        sections.append(_scenario_table(matrices))
    return "\n".join(sections)


def main() -> None:
    results = run_all()
    markdown = render_markdown(results)
    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(markdown)
    print(f"Wrote {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
