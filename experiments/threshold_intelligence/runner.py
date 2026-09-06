"""Runs every registered adaptive strategy against every synthetic
scenario (sentinel.experiments equivalent — see scenarios.py), scores
each strategy's PASS/FAIL verdicts against the scenario's ground-truth
anomaly labels, and renders the result as a Markdown report.

This is Milestone 4's "Experimental Comparison" (docs/architecture/
0005-milestone-4-design.md Part 7) and its answer to "when does an
adaptive threshold outperform a static one" (Part 8 there): a real,
re-runnable measurement, not an assertion. Run it directly with
``python -m experiments.threshold_intelligence.runner`` from the repo
root to regenerate docs/experiments/milestone-4-results.md — doing so
should reproduce that file byte-for-byte, since every scenario is seeded
(see scenarios.py) and every strategy config below is fixed in this
module, not tuned per scenario.

Deliberately bypasses Rule, DataSource, ValidationOrchestrator, and every
persistence module: a strategy's ``evaluate()`` only needs a Metric, a
ThresholdConfig, and a history of prior Metrics (see
sentinel.thresholds.base.ThresholdStrategy), and this experiment is
entirely about that one method's behavior. Building a real Dataset/
DataSource/Policy around synthetic numbers that don't correspond to any
actual rule would add machinery without adding anything this comparison
needs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sentinel.domain import Status, ThresholdConfig
from sentinel.thresholds.base import InsufficientHistoryError, ThresholdStrategy
from sentinel.thresholds.median_mad import MedianMadStrategy
from sentinel.thresholds.percentage_deviation import PercentageDeviationStrategy
from sentinel.thresholds.seasonal import SeasonalBaselineStrategy
from sentinel.thresholds.statistical import StatisticalThresholdStrategy
from sentinel.thresholds.static import StaticThresholdStrategy

from experiments.threshold_intelligence.scenarios import ALL_SCENARIOS, ScenarioPoint

_RESULTS_PATH = Path(__file__).parents[2] / "docs" / "experiments" / "milestone-4-results.md"


@dataclass(frozen=True)
class ConfusionMatrix:
    """One strategy's scored verdicts against one scenario's ground truth.

    ``skipped`` (Milestone 4's own addition to the classic four cells) is
    every point a strategy declined to judge at all
    (InsufficientHistoryError) rather than judging incorrectly — kept
    separate from the four counted cells so a strategy that's merely
    "still warming up" on a short scenario (see Scenario D's Seasonal
    result) isn't scored as if it had guessed and guessed wrong.
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
        """None (not 0.0 or NaN) when no negative case was ever
        evaluated -- "zero false positives out of zero opportunities to
        have one" is not the same claim as "zero false positives out of
        thirty," and reporting a bare 0.0 for both would erase that
        difference."""
        denominator = self.false_positives + self.true_negatives
        return self.false_positives / denominator if denominator else None

    @property
    def false_negative_rate(self) -> float | None:
        denominator = self.false_negatives + self.true_positives
        return self.false_negatives / denominator if denominator else None


def evaluate_strategy(
    points: Sequence[ScenarioPoint], strategy: ThresholdStrategy, config: ThresholdConfig
) -> ConfusionMatrix:
    """Walks ``points`` in chronological order, evaluating each one
    against only the points strictly before it in the sequence (its
    "history so far" -- an expanding window, exactly mirroring how
    ValidationOrchestrator grows a dataset's real history one run at a
    time, never a fixed-size rolling window).

    A Status.FAIL verdict counts as "flagged"; PASS (the only other
    status any Milestone 4 strategy produces) counts as "not flagged."
    WARN is deliberately not treated as flagged here, since none of the
    five registered strategies ever return it -- if a future WARN-
    producing strategy is added to this comparison, this choice should
    be revisited rather than assumed to still be right.
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


# One fixed configuration per strategy, applied identically across every
# scenario -- deliberately not tuned per scenario to flatter any one
# strategy's result. `static`'s bound and `percentage_deviation`'s
# max_deviation have no default in the strategy code (both params are
# required), so a value has to be chosen here; every other value below
# already matches that strategy's own built-in default (see each
# strategy's own docstring) and is only spelled out for this module's own
# readability.
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
    """Every (scenario, strategy) combination -- the full Task 7
    comparison, run uniformly rather than only each scenario's intended
    "star" strategy, so a reader can also see where a strategy that
    isn't the point of a given scenario still lands (e.g. Seasonal
    against Scenario D, which has no repeated weekday to bucket by at
    all -- see the results file for what that produces)."""
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
        "plus one real anomaly (a Monday at 1300). This is the milestone's central "
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
        "The milestone brief's own worked history (1000, 1020, 980, 1010, 1005), then the "
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
        "# Milestone 4 -- Threshold Strategy Comparison\n",
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
