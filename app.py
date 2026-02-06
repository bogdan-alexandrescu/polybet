"""Polybet — Polymarket Analytics Web Application."""

import json

from flask import Flask, jsonify, render_template, request

from db import get_connection, init_analytics_db
from queries import (
    get_calibration_data,
    get_calibration_overview,
    get_categories,
    get_category_growth,
    get_category_resolution_rates,
    get_event,
    get_growth,
    get_market,
    get_market_history,
    get_markets,
    get_momentum_scatter,
    get_monthly_volume,
    get_movers,
    get_newest_markets,
    get_price_change_distribution,
    get_recent_events,
    get_resolution_breakdown,
    get_sibling_markets,
    get_stats,
    get_tags,
    get_top_markets_by_volume,
    get_volume_distribution,
    get_volume_lorenz,
    get_volume_scatter,
)
from analytics import (
    compute_calibration,
    compute_calibration_by_volume_tier,
    compute_histogram,
    compute_lorenz,
)

app = Flask(__name__)


def parse_tags(tags_json):
    """Jinja2 filter to extract tag labels from JSON."""
    if not tags_json:
        return []
    try:
        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        return [t.get("label", "") for t in tags if isinstance(t, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


app.jinja_env.filters["parse_tags"] = parse_tags


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/markets")
def markets_page():
    return render_template("markets.html", active_page="markets")


@app.route("/market/<market_id>")
def market_detail_page(market_id):
    conn = get_connection()
    try:
        market = get_market(conn, market_id)
        if not market:
            return "Market not found", 404
        return render_template("market_detail.html", market=market, active_page="markets")
    finally:
        conn.close()


@app.route("/event/<event_id>")
def event_detail_page(event_id):
    conn = get_connection()
    try:
        event = get_event(conn, event_id)
        if not event:
            return "Event not found", 404
        return render_template("event_detail.html", event=event, active_page="")
    finally:
        conn.close()


@app.route("/categories")
def categories_page():
    return render_template("categories.html", active_page="categories")


@app.route("/volume")
def volume_page():
    return render_template("volume.html", active_page="volume")


@app.route("/movers")
def movers_page():
    return render_template("movers.html", active_page="movers")


@app.route("/calibration")
def calibration_page():
    return render_template("calibration.html", active_page="calibration")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    conn = get_connection()
    try:
        return jsonify(get_stats(conn))
    finally:
        conn.close()


@app.route("/api/growth")
def api_growth():
    conn = get_connection()
    try:
        granularity = request.args.get("granularity", "month")
        return jsonify(get_growth(conn, granularity))
    finally:
        conn.close()


@app.route("/api/markets")
def api_markets():
    conn = get_connection()
    try:
        result = get_markets(
            conn,
            status=request.args.get("status"),
            tag=request.args.get("tag"),
            q=request.args.get("q"),
            sort=request.args.get("sort", "volume"),
            order=request.args.get("order", "desc"),
            page=_int(request.args.get("page", 1), 1),
            per_page=_int(request.args.get("per_page", 50), 50),
            volume_min=_float(request.args.get("volume_min")),
            volume_max=_float(request.args.get("volume_max")),
            liquidity_min=_float(request.args.get("liquidity_min")),
            liquidity_max=_float(request.args.get("liquidity_max")),
            spread_min=_float(request.args.get("spread_min")),
            spread_max=_float(request.args.get("spread_max")),
            price_min=_float(request.args.get("price_min")),
            price_max=_float(request.args.get("price_max")),
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
            outcome_type=request.args.get("outcome_type"),
            end_date_from=request.args.get("end_date_from"),
            end_date_to=request.args.get("end_date_to"),
        )
        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/market/<market_id>")
def api_market(market_id):
    conn = get_connection()
    try:
        market = get_market(conn, market_id)
        if not market:
            return jsonify({"error": "Not found"}), 404
        return jsonify(market)
    finally:
        conn.close()


@app.route("/api/market/<market_id>/history")
def api_market_history(market_id):
    conn = get_connection()
    try:
        return jsonify(get_market_history(conn, market_id))
    finally:
        conn.close()


@app.route("/api/market/<market_id>/siblings")
def api_market_siblings(market_id):
    conn = get_connection()
    try:
        market = get_market(conn, market_id)
        if not market:
            return jsonify([])
        return jsonify(get_sibling_markets(conn, market["event_id"]))
    finally:
        conn.close()


@app.route("/api/event/<event_id>")
def api_event(event_id):
    conn = get_connection()
    try:
        event = get_event(conn, event_id)
        if not event:
            return jsonify({"error": "Not found"}), 404
        return jsonify(event)
    finally:
        conn.close()


@app.route("/api/categories")
def api_categories():
    conn = get_connection()
    try:
        sort = request.args.get("sort", "volume")
        return jsonify(get_categories(conn, sort))
    finally:
        conn.close()


@app.route("/api/categories/growth")
def api_category_growth():
    conn = get_connection()
    try:
        return jsonify(get_category_growth(conn))
    finally:
        conn.close()


@app.route("/api/categories/resolution_rates")
def api_category_resolution_rates():
    conn = get_connection()
    try:
        return jsonify(get_category_resolution_rates(conn))
    finally:
        conn.close()


@app.route("/api/calibration")
def api_calibration():
    conn = get_connection()
    try:
        category = request.args.get("category")
        volume_min = _float(request.args.get("volume_min"))
        data = get_calibration_data(conn, category=category, volume_min=volume_min)
        result = compute_calibration(data)
        result["by_volume_tier"] = compute_calibration_by_volume_tier(data)
        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/calibration/overview")
def api_calibration_overview():
    conn = get_connection()
    try:
        overview = get_calibration_overview(conn)
        # Compute open market price histogram server-side
        open_prices = overview.pop("open_prices", [])
        overview["open_price_distribution"] = compute_histogram(open_prices, n_bins=20)
        return jsonify(overview)
    finally:
        conn.close()


@app.route("/api/volume/distribution")
def api_volume_distribution():
    conn = get_connection()
    try:
        return jsonify(get_volume_distribution(conn))
    finally:
        conn.close()


@app.route("/api/volume/scatter")
def api_volume_scatter():
    conn = get_connection()
    try:
        x = request.args.get("x", "volume")
        y = request.args.get("y", "liquidity")
        sample = int(request.args.get("sample", 5000))
        return jsonify(get_volume_scatter(conn, x, y, sample))
    finally:
        conn.close()


@app.route("/api/volume/lorenz")
def api_volume_lorenz():
    conn = get_connection()
    try:
        volumes = get_volume_lorenz(conn)
        return jsonify(compute_lorenz(volumes))
    finally:
        conn.close()


@app.route("/api/volume/monthly")
def api_volume_monthly():
    conn = get_connection()
    try:
        return jsonify(get_monthly_volume(conn))
    finally:
        conn.close()


@app.route("/api/volume/top")
def api_volume_top():
    conn = get_connection()
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify(get_top_markets_by_volume(conn, limit))
    finally:
        conn.close()


@app.route("/api/movers")
def api_movers():
    conn = get_connection()
    try:
        period = request.args.get("period", "1d")
        limit = int(request.args.get("limit", 50))
        return jsonify(get_movers(conn, period, limit))
    finally:
        conn.close()


@app.route("/api/movers/momentum")
def api_momentum():
    conn = get_connection()
    try:
        limit = int(request.args.get("limit", 2000))
        return jsonify(get_momentum_scatter(conn, limit))
    finally:
        conn.close()


@app.route("/api/movers/distribution")
def api_movers_distribution():
    conn = get_connection()
    try:
        period = request.args.get("period", "1d")
        changes = get_price_change_distribution(conn, period)
        return jsonify(compute_histogram(changes))
    finally:
        conn.close()


@app.route("/api/movers/newest")
def api_newest():
    conn = get_connection()
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify(get_newest_markets(conn, limit))
    finally:
        conn.close()


@app.route("/api/resolution")
def api_resolution():
    conn = get_connection()
    try:
        return jsonify(get_resolution_breakdown(conn))
    finally:
        conn.close()


@app.route("/api/recent_events")
def api_recent_events():
    conn = get_connection()
    try:
        limit = int(request.args.get("limit", 20))
        return jsonify(get_recent_events(conn, limit))
    finally:
        conn.close()


@app.route("/api/tags")
def api_tags():
    conn = get_connection()
    try:
        return jsonify(get_tags(conn))
    finally:
        conn.close()


def _float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


if __name__ == "__main__":
    init_analytics_db()
    app.run(host="0.0.0.0", port=5001, debug=True)
