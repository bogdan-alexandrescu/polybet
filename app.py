"""Polybet — Polymarket Analytics Web Application."""

import json
import os
import threading
import time

from flask import Flask, Response, g, jsonify, render_template, request
from functools import wraps

from db import get_connection, return_connection, init_analytics_db
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
from refresh import get_job, get_logs, request_cancel, run_refresh, sse_generator

SETTINGS_PASSWORD = os.environ.get("SETTINGS_PASSWORD", "admin")


def parse_tags(tags_json):
    """Jinja2 filter to extract tag labels from JSON."""
    if not tags_json:
        return []
    try:
        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        return [t.get("label", "") for t in tags if isinstance(t, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


def require_auth(f):
    """Simple password auth decorator for settings endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("X-Settings-Password")
        if auth != SETTINGS_PASSWORD:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def get_db():
    """Get a database connection, storing it on Flask g for the request."""
    if "db" not in g:
        g.db = get_connection()
    return g.db


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


def create_app():
    app = Flask(__name__)
    app.jinja_env.filters["parse_tags"] = parse_tags

    @app.teardown_appcontext
    def close_db(exception):
        conn = g.pop("db", None)
        if conn is not None:
            return_connection(conn)

    with app.app_context():
        try:
            init_analytics_db()
        except Exception as e:
            print(f"Warning: DB init failed on startup: {e}")
            print("App will start anyway — tables will be created on first refresh.")

    # -------------------------------------------------------------------
    # Page routes
    # -------------------------------------------------------------------

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html", active_page="dashboard")

    @app.route("/markets")
    def markets_page():
        return render_template("markets.html", active_page="markets")

    @app.route("/market/<market_id>")
    def market_detail_page(market_id):
        conn = get_db()
        market = get_market(conn, market_id)
        if not market:
            return "Market not found", 404
        return render_template("market_detail.html", market=market, active_page="markets")

    @app.route("/event/<event_id>")
    def event_detail_page(event_id):
        conn = get_db()
        event = get_event(conn, event_id)
        if not event:
            return "Event not found", 404
        return render_template("event_detail.html", event=event, active_page="")

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

    @app.route("/settings")
    def settings_page():
        return render_template("settings.html", active_page="settings")

    # -------------------------------------------------------------------
    # API routes
    # -------------------------------------------------------------------

    @app.route("/api/stats")
    def api_stats():
        return jsonify(get_stats(get_db()))

    @app.route("/api/growth")
    def api_growth():
        granularity = request.args.get("granularity", "month")
        return jsonify(get_growth(get_db(), granularity))

    @app.route("/api/markets")
    def api_markets():
        result = get_markets(
            get_db(),
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

    @app.route("/api/market/<market_id>")
    def api_market(market_id):
        market = get_market(get_db(), market_id)
        if not market:
            return jsonify({"error": "Not found"}), 404
        return jsonify(market)

    @app.route("/api/market/<market_id>/history")
    def api_market_history(market_id):
        return jsonify(get_market_history(get_db(), market_id))

    @app.route("/api/market/<market_id>/siblings")
    def api_market_siblings(market_id):
        market = get_market(get_db(), market_id)
        if not market:
            return jsonify([])
        return jsonify(get_sibling_markets(get_db(), market["event_id"]))

    @app.route("/api/event/<event_id>")
    def api_event(event_id):
        event = get_event(get_db(), event_id)
        if not event:
            return jsonify({"error": "Not found"}), 404
        return jsonify(event)

    @app.route("/api/categories")
    def api_categories():
        sort = request.args.get("sort", "volume")
        return jsonify(get_categories(get_db(), sort))

    @app.route("/api/categories/growth")
    def api_category_growth():
        return jsonify(get_category_growth(get_db()))

    @app.route("/api/categories/resolution_rates")
    def api_category_resolution_rates():
        return jsonify(get_category_resolution_rates(get_db()))

    @app.route("/api/calibration")
    def api_calibration():
        conn = get_db()
        category = request.args.get("category")
        volume_min = _float(request.args.get("volume_min"))
        data = get_calibration_data(conn, category=category, volume_min=volume_min)
        result = compute_calibration(data)
        result["by_volume_tier"] = compute_calibration_by_volume_tier(data)
        return jsonify(result)

    @app.route("/api/calibration/overview")
    def api_calibration_overview():
        overview = get_calibration_overview(get_db())
        open_prices = overview.pop("open_prices", [])
        overview["open_price_distribution"] = compute_histogram(open_prices, n_bins=20)
        return jsonify(overview)

    @app.route("/api/volume/distribution")
    def api_volume_distribution():
        return jsonify(get_volume_distribution(get_db()))

    @app.route("/api/volume/scatter")
    def api_volume_scatter():
        x = request.args.get("x", "volume")
        y = request.args.get("y", "liquidity")
        sample = int(request.args.get("sample", 5000))
        return jsonify(get_volume_scatter(get_db(), x, y, sample))

    @app.route("/api/volume/lorenz")
    def api_volume_lorenz():
        volumes = get_volume_lorenz(get_db())
        return jsonify(compute_lorenz(volumes))

    @app.route("/api/volume/monthly")
    def api_volume_monthly():
        return jsonify(get_monthly_volume(get_db()))

    @app.route("/api/volume/top")
    def api_volume_top():
        limit = int(request.args.get("limit", 50))
        return jsonify(get_top_markets_by_volume(get_db(), limit))

    @app.route("/api/movers")
    def api_movers():
        period = request.args.get("period", "1d")
        limit = int(request.args.get("limit", 50))
        return jsonify(get_movers(get_db(), period, limit))

    @app.route("/api/movers/momentum")
    def api_momentum():
        limit = int(request.args.get("limit", 2000))
        return jsonify(get_momentum_scatter(get_db(), limit))

    @app.route("/api/movers/distribution")
    def api_movers_distribution():
        period = request.args.get("period", "1d")
        changes = get_price_change_distribution(get_db(), period)
        return jsonify(compute_histogram(changes))

    @app.route("/api/movers/newest")
    def api_newest():
        limit = int(request.args.get("limit", 50))
        return jsonify(get_newest_markets(get_db(), limit))

    @app.route("/api/resolution")
    def api_resolution():
        return jsonify(get_resolution_breakdown(get_db()))

    @app.route("/api/recent_events")
    def api_recent_events():
        limit = int(request.args.get("limit", 20))
        return jsonify(get_recent_events(get_db(), limit))

    @app.route("/api/tags")
    def api_tags():
        return jsonify(get_tags(get_db()))

    # -------------------------------------------------------------------
    # Settings API
    # -------------------------------------------------------------------

    @app.route("/api/settings", methods=["GET"])
    @require_auth
    def api_get_settings():
        conn = get_db()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return jsonify({r["key"]: r["value"] for r in rows})

    @app.route("/api/settings", methods=["POST"])
    @require_auth
    def api_update_settings():
        conn = get_db()
        data = request.get_json()
        for key, value in data.items():
            conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (%(key)s, %(value)s, NOW())
                ON CONFLICT (key) DO UPDATE SET value = %(value)s, updated_at = NOW()
            """, {"key": key, "value": value})
        conn.commit()
        return jsonify({"status": "ok"})

    # -------------------------------------------------------------------
    # Refresh API
    # -------------------------------------------------------------------

    @app.route("/api/refresh/start", methods=["POST"])
    @require_auth
    def api_refresh_start():
        conn = get_db()
        running = conn.execute(
            "SELECT id FROM refresh_jobs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if running:
            return jsonify({"error": "Refresh already running", "job_id": running["id"]}), 409
        t = threading.Thread(target=run_refresh, args=("web",), daemon=True)
        t.start()
        time.sleep(0.3)
        job = conn.execute("SELECT id FROM refresh_jobs ORDER BY id DESC LIMIT 1").fetchone()
        return jsonify({"status": "started", "job_id": job["id"] if job else None})

    @app.route("/api/refresh/cancel", methods=["POST"])
    @require_auth
    def api_refresh_cancel():
        job_id = request.get_json(silent=True) or {}
        request_cancel(job_id.get("job_id"))
        return jsonify({"status": "cancel_requested"})

    @app.route("/api/refresh/status")
    def api_refresh_status():
        job_id = request.args.get("job_id", type=int)
        after_line = request.args.get("after_line", 0, type=int)
        job = get_job(job_id)
        if not job:
            return jsonify({"running": False, "phase": ""})
        job["log_lines"] = get_logs(job["id"], after_id=after_line)
        return jsonify(job)

    @app.route("/api/refresh/stream")
    def api_refresh_stream():
        job_id = request.args.get("job_id", type=int)
        return Response(
            sse_generator(job_id),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
