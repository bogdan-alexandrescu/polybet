"""Tests for analytics.py - statistical computations."""

import json
import pytest

from analytics import (
    compute_calibration,
    compute_calibration_by_volume_tier,
    compute_histogram,
    compute_lorenz,
)


class TestComputeCalibration:
    def make_market(self, last_trade_price, snapshot_price, volume=10000):
        return {
            "last_trade_price": last_trade_price,
            "snapshot_prices": json.dumps([str(snapshot_price), str(1 - snapshot_price)]),
            "volume": volume,
        }

    def test_basic_calibration(self):
        # Perfectly calibrated: 0.8 predicted, resolved yes
        markets = [
            self.make_market(0.98, 0.8),  # Resolved yes, predicted 80%
            self.make_market(0.99, 0.7),  # Resolved yes, predicted 70%
            self.make_market(0.01, 0.2),  # Resolved no, predicted 20%
            self.make_market(0.02, 0.3),  # Resolved no, predicted 30%
        ]
        result = compute_calibration(markets)
        assert result["count"] == 4
        assert len(result["bins"]) == 10
        assert "brier_score" in result

    def test_empty_data(self):
        result = compute_calibration([])
        assert result["count"] == 0
        assert result["bins"] == []
        assert result["brier_score"] is None

    def test_no_valid_markets(self):
        # All ambiguous resolutions
        markets = [
            self.make_market(0.50, 0.5),
            self.make_market(0.45, 0.6),
        ]
        result = compute_calibration(markets)
        assert result["count"] == 0

    def test_missing_snapshot(self):
        markets = [
            {"last_trade_price": 0.98, "snapshot_prices": None, "volume": 1000},
        ]
        result = compute_calibration(markets)
        assert result["count"] == 0

    def test_brier_score_range(self):
        markets = [
            self.make_market(0.98, 0.8),
            self.make_market(0.02, 0.3),
        ]
        result = compute_calibration(markets)
        assert 0 <= result["brier_score"] <= 1

    def test_perfect_calibration(self):
        # If predicted 0.99 and resolved yes, brier should be very low
        markets = [self.make_market(0.99, 0.99)]
        result = compute_calibration(markets)
        assert result["brier_score"] < 0.01

    def test_bins_structure(self):
        markets = [
            self.make_market(0.98, 0.15),
            self.make_market(0.02, 0.85),
            self.make_market(0.99, 0.55),
        ]
        result = compute_calibration(markets, n_bins=5)
        assert len(result["bins"]) == 5
        for b in result["bins"]:
            assert "bin_start" in b
            assert "bin_end" in b
            assert "avg_predicted" in b
            assert "count" in b

    def test_invalid_json_snapshot(self):
        markets = [
            {"last_trade_price": 0.98, "snapshot_prices": "invalid json", "volume": 1000},
        ]
        result = compute_calibration(markets)
        assert result["count"] == 0

    def test_boundary_prices_excluded(self):
        """Predicted prices of 0 or 1 should be excluded."""
        markets = [
            self.make_market(0.98, 0.0),
            self.make_market(0.02, 1.0),
        ]
        result = compute_calibration(markets)
        assert result["count"] == 0

    def test_none_last_trade_price(self):
        markets = [
            {"last_trade_price": None, "snapshot_prices": json.dumps(["0.5", "0.5"]), "volume": 1000},
        ]
        result = compute_calibration(markets)
        assert result["count"] == 0


class TestComputeLorenz:
    def test_basic_lorenz(self):
        volumes = [1, 2, 3, 4, 5]
        result = compute_lorenz(volumes)
        assert "curve" in result
        assert "gini" in result
        assert len(result["curve"]) > 0
        # First point should be (0, 0)
        assert result["curve"][0]["x"] == 0
        assert result["curve"][0]["y"] == 0
        # Last point should be (1, 1)
        assert result["curve"][-1]["x"] == 1.0
        assert result["curve"][-1]["y"] == 1.0

    def test_perfect_equality(self):
        volumes = [100, 100, 100, 100, 100]
        result = compute_lorenz(volumes)
        assert result["gini"] == pytest.approx(0.0, abs=0.01)

    def test_high_inequality(self):
        volumes = [1, 1, 1, 1, 1000000]
        result = compute_lorenz(volumes)
        assert result["gini"] >= 0.8

    def test_empty_volumes(self):
        result = compute_lorenz([])
        assert result["gini"] == 0
        assert result["curve"] == []

    def test_zero_total(self):
        result = compute_lorenz([0, 0, 0])
        # All zeros: total is 0
        assert result["gini"] == 0

    def test_single_value(self):
        result = compute_lorenz([100])
        assert result["gini"] == pytest.approx(0.0, abs=0.01)
        assert len(result["curve"]) == 2

    def test_downsampling(self):
        """Large datasets should be downsampled."""
        volumes = list(range(1, 1001))
        result = compute_lorenz(volumes)
        # Should be downsampled to ~200 points
        assert len(result["curve"]) <= 210

    def test_gini_range(self):
        volumes = [10, 20, 30, 40, 50]
        result = compute_lorenz(volumes)
        assert 0 <= result["gini"] <= 1


class TestComputeHistogram:
    def test_basic_histogram(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = compute_histogram(values, n_bins=5)
        assert len(result) == 5
        total = sum(b["count"] for b in result)
        assert total == 10

    def test_empty_values(self):
        result = compute_histogram([])
        assert result == []

    def test_single_value(self):
        result = compute_histogram([5.0])
        assert len(result) == 1
        assert result[0]["count"] == 1

    def test_bin_structure(self):
        values = [1, 2, 3, 4, 5]
        result = compute_histogram(values, n_bins=3)
        for b in result:
            assert "lo" in b
            assert "hi" in b
            assert "count" in b

    def test_negative_values(self):
        values = [-5, -3, -1, 0, 1, 3, 5]
        result = compute_histogram(values, n_bins=4)
        total = sum(b["count"] for b in result)
        assert total == 7


class TestComputeCalibrationByVolumeTier:
    def make_market(self, last_trade_price, snapshot_price, volume):
        return {
            "last_trade_price": last_trade_price,
            "snapshot_prices": json.dumps([str(snapshot_price), str(1 - snapshot_price)]),
            "volume": volume,
        }

    def test_tier_separation(self):
        markets = [
            self.make_market(0.98, 0.7, 500),      # < $1K
            self.make_market(0.02, 0.3, 500),
            self.make_market(0.98, 0.6, 500),
            self.make_market(0.02, 0.4, 500),
            self.make_market(0.98, 0.7, 500),
            self.make_market(0.02, 0.3, 500),
            self.make_market(0.98, 0.6, 500),
            self.make_market(0.02, 0.4, 500),
            self.make_market(0.98, 0.7, 500),
            self.make_market(0.02, 0.3, 500),
            self.make_market(0.98, 0.6, 500),
            # 11 markets in < $1K tier
            self.make_market(0.98, 0.8, 5000),      # $1K - $10K
            self.make_market(0.02, 0.2, 5000),
            self.make_market(0.98, 0.7, 5000),
            self.make_market(0.02, 0.3, 5000),
            self.make_market(0.98, 0.6, 5000),
            self.make_market(0.02, 0.4, 5000),
            self.make_market(0.98, 0.8, 5000),
            self.make_market(0.02, 0.2, 5000),
            self.make_market(0.98, 0.7, 5000),
            self.make_market(0.02, 0.3, 5000),
            self.make_market(0.98, 0.6, 5000),
            # 11 markets in $1K-$10K tier
        ]
        result = compute_calibration_by_volume_tier(markets)
        assert isinstance(result, dict)
        # At least one tier should have enough data
        assert len(result) >= 1

    def test_empty_markets(self):
        result = compute_calibration_by_volume_tier([])
        assert isinstance(result, dict)

    def test_volume_none(self):
        """Markets without volume should not cause errors."""
        markets = [
            {"last_trade_price": 0.98, "snapshot_prices": json.dumps(["0.7", "0.3"]), "volume": None},
        ]
        result = compute_calibration_by_volume_tier(markets)
        assert isinstance(result, dict)
