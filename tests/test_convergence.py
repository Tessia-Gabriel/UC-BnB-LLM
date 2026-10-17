from ucbranch.convergence import trajectory_metrics


def test_trajectory_metrics_reward_early_convergence():
    fast = [
        {"wall_seconds": 0.0, "gap": 0.1},
        {"wall_seconds": 2.0, "gap": 0.0},
    ]
    slow = [
        {"wall_seconds": 0.0, "gap": 0.1},
        {"wall_seconds": 8.0, "gap": 0.0},
    ]
    assert trajectory_metrics(fast, 10)["mean_capped_gap"] == 0.02
    assert trajectory_metrics(slow, 10)["mean_capped_gap"] == 0.08
    assert trajectory_metrics(fast, 10)["mean_gap_ratio"] == 0.2
    assert trajectory_metrics(slow, 10)["mean_gap_ratio"] == 0.8


def test_trajectory_metrics_threshold_times():
    rows = [
        {"wall_seconds": 0.0, "gap": 1e-2},
        {"wall_seconds": 3.0, "gap": 1e-4},
        {"wall_seconds": 7.0, "gap": 0.0},
    ]
    result = trajectory_metrics(rows, 10)
    assert result["time_to_gap"]["1e-02"] == 0.0
    assert result["time_to_gap"]["1e-04"] == 3.0
    assert result["time_to_gap"]["0e+00"] == 7.0


def test_thresholds_ignore_points_after_horizon():
    rows = [
        {"wall_seconds": 0.0, "gap": 1e-2},
        {"wall_seconds": 10.1, "gap": 0.0},
    ]
    result = trajectory_metrics(rows, 10)
    assert result["gap_at_horizon"] == 1e-2
    assert result["time_to_gap"]["0e+00"] is None
