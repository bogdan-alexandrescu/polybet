"""Statistical computations for Polybet analytics."""

import json


def compute_calibration(markets, n_bins=10):
    """Compute calibration curve from resolved markets.

    Takes markets with snapshot_prices (first recorded price) and
    last_trade_price (resolution outcome).

    Returns bins with predicted probability vs actual resolution rate.
    """
    data_points = []
    for m in markets:
        resolution_price = m.get("last_trade_price")
        if resolution_price is None:
            continue

        # Determine actual outcome: resolved Yes (>=0.95) or No (<=0.05)
        if resolution_price >= 0.95:
            actual = 1.0
        elif resolution_price <= 0.05:
            actual = 0.0
        else:
            continue  # Skip ambiguous resolutions

        # Get earliest snapshot price as the "predicted" probability
        snapshot_prices = m.get("snapshot_prices")
        if snapshot_prices:
            try:
                prices = json.loads(snapshot_prices)
                predicted = float(prices[0])
            except (json.JSONDecodeError, ValueError, IndexError):
                continue
        else:
            continue

        if 0 < predicted < 1:
            data_points.append((predicted, actual))

    if not data_points:
        return {"bins": [], "count": 0, "brier_score": None}

    data_points.sort(key=lambda x: x[0])

    bin_size = 1.0 / n_bins
    bins = []
    for i in range(n_bins):
        lo = i * bin_size
        hi = (i + 1) * bin_size
        mid = (lo + hi) / 2
        in_bin = [(p, a) for p, a in data_points if lo <= p < hi]
        if in_bin:
            avg_predicted = sum(p for p, _ in in_bin) / len(in_bin)
            avg_actual = sum(a for _, a in in_bin) / len(in_bin)
            bins.append({
                "bin_start": round(lo, 2),
                "bin_end": round(hi, 2),
                "bin_mid": round(mid, 2),
                "avg_predicted": round(avg_predicted, 4),
                "avg_actual": round(avg_actual, 4),
                "count": len(in_bin),
            })
        else:
            bins.append({
                "bin_start": round(lo, 2),
                "bin_end": round(hi, 2),
                "bin_mid": round(mid, 2),
                "avg_predicted": round(mid, 4),
                "avg_actual": None,
                "count": 0,
            })

    # Brier score
    brier = sum((p - a) ** 2 for p, a in data_points) / len(data_points)

    return {
        "bins": bins,
        "count": len(data_points),
        "brier_score": round(brier, 4),
    }


def compute_lorenz(volumes):
    """Compute Lorenz curve and Gini coefficient from sorted volumes."""
    if not volumes:
        return {"curve": [], "gini": 0}

    n = len(volumes)
    total = sum(volumes)
    if total == 0:
        return {"curve": [], "gini": 0}

    cumulative = 0
    curve = [{"x": 0, "y": 0}]
    for i, v in enumerate(volumes):
        cumulative += v
        curve.append({
            "x": round((i + 1) / n, 4),
            "y": round(cumulative / total, 4),
        })

    # Gini coefficient = 1 - 2 * area under Lorenz curve
    # Area under curve using trapezoidal rule
    area = 0
    for i in range(1, len(curve)):
        area += (curve[i]["x"] - curve[i - 1]["x"]) * (curve[i]["y"] + curve[i - 1]["y"]) / 2

    gini = round(1 - 2 * area, 4)

    # Downsample curve for chart rendering (keep ~200 points)
    if len(curve) > 200:
        step = len(curve) // 200
        curve = curve[::step] + [curve[-1]]

    return {"curve": curve, "gini": gini}


def compute_histogram(values, n_bins=40):
    """Compute histogram bins from a list of values."""
    if not values:
        return []

    min_val = min(values)
    max_val = max(values)

    if min_val == max_val:
        return [{"lo": min_val, "hi": max_val, "count": len(values)}]

    step = (max_val - min_val) / n_bins
    bins = []
    for i in range(n_bins):
        lo = min_val + i * step
        hi = min_val + (i + 1) * step
        count = sum(1 for v in values if lo <= v < hi)
        bins.append({"lo": round(lo, 4), "hi": round(hi, 4), "count": count})

    # Add last value to final bin
    bins[-1]["count"] += sum(1 for v in values if v == max_val)

    return bins


def compute_calibration_by_category(conn, categories, volume_min=None):
    """Compute calibration for multiple categories."""
    from queries import get_calibration_data
    results = {}
    for cat in categories:
        data = get_calibration_data(conn, category=cat["tag_slug"], volume_min=volume_min)
        cal = compute_calibration(data)
        if cal["count"] > 20:
            results[cat["tag_label"]] = cal
    return results


def compute_calibration_by_volume_tier(markets):
    """Compute calibration split by volume tiers."""
    tiers = [
        ("< $1K", 0, 1000),
        ("$1K - $10K", 1000, 10000),
        ("$10K - $100K", 10000, 100000),
        ("$100K - $1M", 100000, 1000000),
        ("> $1M", 1000000, float("inf")),
    ]
    results = {}
    for label, lo, hi in tiers:
        tier_markets = [m for m in markets if m.get("volume") and lo <= m["volume"] < hi]
        cal = compute_calibration(tier_markets)
        if cal["count"] > 10:
            results[label] = cal
    return results
