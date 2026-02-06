"""All SQL queries for Polybet analytics."""

import json


def get_stats(conn):
    """Dashboard KPIs."""
    row = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM events) AS total_events,
            (SELECT COUNT(*) FROM markets) AS total_markets,
            (SELECT COALESCE(SUM(volume), 0) FROM markets) AS total_volume,
            (SELECT COUNT(*) FROM markets WHERE closed = 0) AS open_markets,
            (SELECT AVG(spread) FROM markets WHERE closed = 0 AND spread IS NOT NULL) AS avg_spread,
            (SELECT COUNT(*) FROM price_snapshots) AS total_snapshots
    """).fetchone()
    return dict(row)


def get_growth(conn, granularity="month"):
    """Events created per month + cumulative volume."""
    fmt = "%Y-%m" if granularity == "month" else "%Y-%W"
    rows = conn.execute(f"""
        SELECT strftime('{fmt}', created_at) AS period,
               COUNT(*) AS event_count,
               COALESCE(SUM(volume), 0) AS period_volume
        FROM events
        WHERE created_at IS NOT NULL
        GROUP BY period
        ORDER BY period
    """).fetchall()
    result = []
    cum_volume = 0
    for r in rows:
        cum_volume += r["period_volume"]
        result.append({
            "period": r["period"],
            "event_count": r["event_count"],
            "period_volume": r["period_volume"],
            "cumulative_volume": cum_volume,
        })
    return result


def get_markets(conn, status=None, tag=None, q=None, sort="volume",
                order="desc", page=1, per_page=50, volume_min=None,
                volume_max=None, liquidity_min=None, liquidity_max=None,
                spread_min=None, spread_max=None, date_from=None, date_to=None,
                outcome_type=None, end_date_from=None, end_date_to=None,
                price_min=None, price_max=None):
    """Filtered, sorted, paginated market list."""
    conditions = []
    params = {}

    if status == "open":
        conditions.append("m.closed = 0")
    elif status == "closed":
        conditions.append("m.closed = 1")

    if tag:
        conditions.append("EXISTS (SELECT 1 FROM event_tags et WHERE et.event_id = m.event_id AND et.tag_slug = :tag)")
        params["tag"] = tag

    if q:
        conditions.append("m.question LIKE :q")
        params["q"] = f"%{q}%"

    if volume_min is not None:
        conditions.append("m.volume >= :volume_min")
        params["volume_min"] = volume_min

    if volume_max is not None:
        conditions.append("m.volume <= :volume_max")
        params["volume_max"] = volume_max

    if liquidity_min is not None:
        conditions.append("m.liquidity >= :liquidity_min")
        params["liquidity_min"] = liquidity_min

    if liquidity_max is not None:
        conditions.append("m.liquidity <= :liquidity_max")
        params["liquidity_max"] = liquidity_max

    if spread_min is not None:
        conditions.append("m.spread >= :spread_min")
        params["spread_min"] = spread_min

    if spread_max is not None:
        conditions.append("m.spread <= :spread_max")
        params["spread_max"] = spread_max

    if price_min is not None:
        conditions.append("m.last_trade_price >= :price_min")
        params["price_min"] = price_min

    if price_max is not None:
        conditions.append("m.last_trade_price <= :price_max")
        params["price_max"] = price_max

    if date_from:
        conditions.append("m.created_at >= :date_from")
        params["date_from"] = date_from

    if date_to:
        conditions.append("m.created_at <= :date_to")
        params["date_to"] = date_to

    if outcome_type:
        conditions.append("m.outcomes LIKE :outcome_type")
        params["outcome_type"] = f"%{outcome_type}%"

    if end_date_from:
        conditions.append("m.end_date IS NOT NULL AND m.end_date >= :end_date_from")
        params["end_date_from"] = end_date_from

    if end_date_to:
        conditions.append("m.end_date IS NOT NULL AND m.end_date <= :end_date_to")
        params["end_date_to"] = end_date_to

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    allowed_sorts = {
        "volume": "m.volume", "liquidity": "m.liquidity", "spread": "m.spread",
        "price": "m.last_trade_price", "1d_change": "m.one_day_change",
        "1w_change": "m.one_week_change", "created": "m.created_at",
        "question": "m.question", "end_date": "m.end_date",
        "closed": "m.closed",
    }
    sort_col = allowed_sorts.get(sort, "m.volume")
    sort_dir = "ASC" if order == "asc" else "DESC"

    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    count = conn.execute(
        f"SELECT COUNT(*) FROM markets m {where}", params
    ).fetchone()[0]

    rows = conn.execute(f"""
        SELECT m.id, m.question, m.event_id, m.last_trade_price, m.volume,
               m.liquidity, m.spread, m.one_day_change, m.one_week_change,
               m.closed, m.outcomes, m.outcome_prices, m.created_at,
               m.end_date, e.title AS event_title
        FROM markets m
        LEFT JOIN events e ON e.id = m.event_id
        {where}
        ORDER BY {sort_col} {sort_dir} NULLS LAST
        LIMIT :limit OFFSET :offset
    """, params).fetchall()

    return {
        "markets": [dict(r) for r in rows],
        "total": count,
        "page": page,
        "per_page": per_page,
        "pages": (count + per_page - 1) // per_page,
    }


def get_market(conn, market_id):
    """Single market with event info."""
    row = conn.execute("""
        SELECT m.*, e.title AS event_title, e.slug AS event_slug,
               e.tags AS event_tags
        FROM markets m
        LEFT JOIN events e ON e.id = m.event_id
        WHERE m.id = :id
    """, {"id": market_id}).fetchone()
    return dict(row) if row else None


def get_market_history(conn, market_id):
    """Price snapshots for a market."""
    rows = conn.execute("""
        SELECT fetched_at, outcome_prices, volume, liquidity, spread,
               last_trade_price
        FROM price_snapshots
        WHERE market_id = :id
        ORDER BY fetched_at
    """, {"id": market_id}).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["outcome_prices"]:
            try:
                prices = json.loads(d["outcome_prices"])
                d["price"] = float(prices[0]) if prices else None
            except (json.JSONDecodeError, ValueError, IndexError):
                d["price"] = None
        else:
            d["price"] = None
        result.append(d)
    return result


def get_sibling_markets(conn, event_id, exclude_market_id=None):
    """Other markets in the same event."""
    rows = conn.execute("""
        SELECT id, question, last_trade_price, volume, liquidity, spread,
               outcomes, outcome_prices, closed
        FROM markets
        WHERE event_id = :event_id
        ORDER BY volume DESC
    """, {"event_id": event_id}).fetchall()
    return [dict(r) for r in rows]


def get_event(conn, event_id):
    """Single event with all its markets."""
    event = conn.execute(
        "SELECT * FROM events WHERE id = :id", {"id": event_id}
    ).fetchone()
    if not event:
        return None
    event = dict(event)
    markets = conn.execute("""
        SELECT id, question, last_trade_price, volume, liquidity, spread,
               outcomes, outcome_prices, closed, one_day_change, one_week_change,
               group_item_title
        FROM markets
        WHERE event_id = :id
        ORDER BY volume DESC
    """, {"id": event_id}).fetchall()
    event["markets"] = [dict(m) for m in markets]
    return event


def get_categories(conn, sort="volume"):
    """Category/tag statistics."""
    allowed_sorts = {
        "volume": "total_volume DESC",
        "count": "market_count DESC",
        "spread": "avg_spread ASC",
        "liquidity": "avg_liquidity DESC",
    }
    order = allowed_sorts.get(sort, "total_volume DESC")
    rows = conn.execute(f"""
        SELECT et.tag_label, et.tag_slug,
               COUNT(DISTINCT et.event_id) AS event_count,
               COUNT(DISTINCT m.id) AS market_count,
               COALESCE(SUM(m.volume), 0) AS total_volume,
               AVG(m.spread) AS avg_spread,
               AVG(m.liquidity) AS avg_liquidity,
               SUM(CASE WHEN m.closed = 1 THEN 1 ELSE 0 END) AS resolved_count
        FROM event_tags et
        JOIN markets m ON m.event_id = et.event_id
        GROUP BY et.tag_slug
        ORDER BY {order}
    """).fetchall()
    return [dict(r) for r in rows]


def get_category_growth(conn, limit=10):
    """Monthly volume by top tags."""
    top_tags = conn.execute("""
        SELECT et.tag_slug, et.tag_label
        FROM event_tags et
        JOIN markets m ON m.event_id = et.event_id
        GROUP BY et.tag_slug
        ORDER BY SUM(m.volume) DESC
        LIMIT :limit
    """, {"limit": limit}).fetchall()

    if not top_tags:
        return {"tags": [], "series": []}

    tag_slugs = [t["tag_slug"] for t in top_tags]
    tag_labels = [t["tag_label"] for t in top_tags]

    placeholders = ",".join(["?"] * len(tag_slugs))
    rows = conn.execute(f"""
        SELECT strftime('%Y-%m', e.created_at) AS period,
               et.tag_slug,
               COALESCE(SUM(m.volume), 0) AS period_volume
        FROM event_tags et
        JOIN events e ON e.id = et.event_id
        JOIN markets m ON m.event_id = et.event_id
        WHERE et.tag_slug IN ({placeholders})
          AND e.created_at IS NOT NULL
        GROUP BY period, et.tag_slug
        ORDER BY period
    """, tag_slugs).fetchall()

    periods = sorted(set(r["period"] for r in rows))
    series = {}
    for slug in tag_slugs:
        series[slug] = {p: 0 for p in periods}
    for r in rows:
        if r["tag_slug"] in series:
            series[r["tag_slug"]][r["period"]] = r["period_volume"]

    return {
        "periods": periods,
        "tags": tag_labels,
        "series": [
            {"tag": label, "slug": slug, "data": [series[slug].get(p, 0) for p in periods]}
            for slug, label in zip(tag_slugs, tag_labels)
        ]
    }


def get_volume_distribution(conn, buckets=30):
    """Volume histogram data."""
    rows = conn.execute("""
        SELECT volume FROM markets
        WHERE volume IS NOT NULL AND volume > 0
        ORDER BY volume
    """).fetchall()
    if not rows:
        return []
    volumes = [r["volume"] for r in rows]
    import math
    min_log = math.log10(max(volumes[0], 1))
    max_log = math.log10(volumes[-1])
    step = (max_log - min_log) / buckets
    histogram = []
    for i in range(buckets):
        lo = 10 ** (min_log + i * step)
        hi = 10 ** (min_log + (i + 1) * step)
        count = sum(1 for v in volumes if lo <= v < hi)
        histogram.append({"lo": round(lo, 2), "hi": round(hi, 2), "count": count})
    return histogram


def get_volume_scatter(conn, x="volume", y="liquidity", sample=5000):
    """Scatter plot data for volume analysis."""
    allowed = {"volume", "liquidity", "spread", "last_trade_price", "one_day_change"}
    x_col = x if x in allowed else "volume"
    y_col = y if y in allowed else "liquidity"
    rows = conn.execute(f"""
        SELECT {x_col} AS x, {y_col} AS y, question, volume
        FROM markets
        WHERE {x_col} IS NOT NULL AND {y_col} IS NOT NULL
          AND {x_col} > 0 AND {y_col} > 0
        ORDER BY RANDOM()
        LIMIT :limit
    """, {"limit": sample}).fetchall()
    return [dict(r) for r in rows]


def get_movers(conn, period="1d", limit=50):
    """Top price movers by period."""
    col_map = {"1d": "one_day_change", "1w": "one_week_change", "1m": "one_month_change"}
    col = col_map.get(period, "one_day_change")
    gainers = conn.execute(f"""
        SELECT m.id, m.question, m.last_trade_price, m.volume,
               m.{col} AS change, m.event_id, e.title AS event_title
        FROM markets m
        LEFT JOIN events e ON e.id = m.event_id
        WHERE m.closed = 0 AND m.{col} IS NOT NULL
        ORDER BY m.{col} DESC
        LIMIT :limit
    """, {"limit": limit}).fetchall()
    losers = conn.execute(f"""
        SELECT m.id, m.question, m.last_trade_price, m.volume,
               m.{col} AS change, m.event_id, e.title AS event_title
        FROM markets m
        LEFT JOIN events e ON e.id = m.event_id
        WHERE m.closed = 0 AND m.{col} IS NOT NULL
        ORDER BY m.{col} ASC
        LIMIT :limit
    """, {"limit": limit}).fetchall()
    return {
        "gainers": [dict(r) for r in gainers],
        "losers": [dict(r) for r in losers],
    }


def get_momentum_scatter(conn, limit=2000):
    """1w change vs 1d change scatter data."""
    rows = conn.execute("""
        SELECT m.id, m.question, m.one_day_change, m.one_week_change,
               m.volume, m.last_trade_price
        FROM markets m
        WHERE m.closed = 0
          AND m.one_day_change IS NOT NULL
          AND m.one_week_change IS NOT NULL
        ORDER BY m.volume DESC
        LIMIT :limit
    """, {"limit": limit}).fetchall()
    return [dict(r) for r in rows]


def get_newest_markets(conn, limit=50):
    """Most recently created markets."""
    rows = conn.execute("""
        SELECT m.id, m.question, m.last_trade_price, m.volume, m.liquidity,
               m.created_at, m.event_id, e.title AS event_title
        FROM markets m
        LEFT JOIN events e ON e.id = m.event_id
        WHERE m.closed = 0
        ORDER BY m.created_at DESC
        LIMIT :limit
    """, {"limit": limit}).fetchall()
    return [dict(r) for r in rows]


def get_resolution_breakdown(conn):
    """Resolution outcome counts."""
    rows = conn.execute("""
        SELECT
            SUM(CASE WHEN closed = 1 AND last_trade_price >= 0.95 THEN 1 ELSE 0 END) AS resolved_yes,
            SUM(CASE WHEN closed = 1 AND last_trade_price <= 0.05 THEN 1 ELSE 0 END) AS resolved_no,
            SUM(CASE WHEN closed = 1 AND last_trade_price > 0.05 AND last_trade_price < 0.95 THEN 1 ELSE 0 END) AS resolved_ambiguous,
            SUM(CASE WHEN closed = 0 THEN 1 ELSE 0 END) AS still_open
        FROM markets
    """).fetchone()
    return dict(rows)


def get_recent_events(conn, limit=20):
    """Most recently created events."""
    rows = conn.execute("""
        SELECT e.id, e.title, e.volume, e.liquidity, e.closed,
               e.created_at, e.tags,
               COUNT(m.id) AS market_count
        FROM events e
        LEFT JOIN markets m ON m.event_id = e.id
        GROUP BY e.id
        ORDER BY e.created_at DESC
        LIMIT :limit
    """, {"limit": limit}).fetchall()
    return [dict(r) for r in rows]


def get_top_markets_by_volume(conn, limit=50):
    """Top markets ranked by volume."""
    rows = conn.execute("""
        SELECT m.id, m.question, m.volume, m.liquidity, m.spread,
               m.last_trade_price, m.closed, m.event_id,
               e.title AS event_title
        FROM markets m
        LEFT JOIN events e ON e.id = m.event_id
        ORDER BY m.volume DESC
        LIMIT :limit
    """, {"limit": limit}).fetchall()
    return [dict(r) for r in rows]


def get_tags(conn):
    """All unique tags for dropdown filters."""
    rows = conn.execute("""
        SELECT tag_label, tag_slug, COUNT(*) AS event_count
        FROM event_tags
        GROUP BY tag_slug
        ORDER BY event_count DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_calibration_data(conn, category=None, volume_min=None):
    """Get resolved markets with pre-resolution snapshot prices for calibration.

    Uses INNER JOIN to only return markets that have meaningful snapshot data
    (price between 0.01 and 0.99, i.e. not already resolved at snapshot time).
    """
    conditions = ["m.closed = 1", "m.last_trade_price IS NOT NULL"]
    params = {}

    if category:
        conditions.append(
            "EXISTS (SELECT 1 FROM event_tags et WHERE et.event_id = m.event_id AND et.tag_slug = :category)"
        )
        params["category"] = category

    if volume_min is not None:
        conditions.append("m.volume >= :volume_min")
        params["volume_min"] = volume_min

    where = " AND ".join(conditions)

    rows = conn.execute(f"""
        SELECT m.id, m.question, m.last_trade_price, m.volume,
               m.event_id, ps.outcome_prices AS snapshot_prices,
               ps.fetched_at AS snapshot_time
        FROM markets m
        INNER JOIN (
            SELECT market_id, outcome_prices, fetched_at,
                   ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY fetched_at ASC) AS rn
            FROM price_snapshots
            WHERE outcome_prices IS NOT NULL
              AND outcome_prices NOT LIKE '%"0"%'
              AND outcome_prices NOT LIKE '%"1"%'
              AND outcome_prices NOT LIKE '%"0.0"%'
              AND outcome_prices NOT LIKE '%"1.0"%'
        ) ps ON ps.market_id = m.id AND ps.rn = 1
        WHERE {where}
        ORDER BY m.volume DESC
        LIMIT 50000
    """, params).fetchall()

    return [dict(r) for r in rows]


def get_calibration_overview(conn):
    """Get calibration data availability stats and supplementary analysis data."""
    stats = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM markets WHERE closed = 1) AS total_resolved,
            (SELECT COUNT(*) FROM markets WHERE closed = 0) AS total_open,
            (SELECT COUNT(DISTINCT ps.market_id)
             FROM price_snapshots ps
             JOIN markets m ON m.id = ps.market_id
             WHERE m.closed = 1) AS resolved_with_snapshots,
            (SELECT COUNT(DISTINCT market_id) FROM price_snapshots) AS total_markets_with_snapshots,
            (SELECT COUNT(*) FROM price_snapshots) AS total_snapshots,
            (SELECT MIN(fetched_at) FROM price_snapshots) AS first_snapshot,
            (SELECT MAX(fetched_at) FROM price_snapshots) AS last_snapshot
    """).fetchone()

    # Open market price distribution (always has data)
    open_price_rows = conn.execute("""
        SELECT last_trade_price
        FROM markets
        WHERE closed = 0
          AND last_trade_price IS NOT NULL
          AND last_trade_price > 0 AND last_trade_price < 1
    """).fetchall()
    open_prices = [r["last_trade_price"] for r in open_price_rows]

    # Resolution price distribution (always has data for closed markets)
    resolution_rows = conn.execute("""
        SELECT
            SUM(CASE WHEN last_trade_price <= 0.05 THEN 1 ELSE 0 END) AS p0_5,
            SUM(CASE WHEN last_trade_price > 0.05 AND last_trade_price <= 0.15 THEN 1 ELSE 0 END) AS p5_15,
            SUM(CASE WHEN last_trade_price > 0.15 AND last_trade_price <= 0.25 THEN 1 ELSE 0 END) AS p15_25,
            SUM(CASE WHEN last_trade_price > 0.25 AND last_trade_price <= 0.35 THEN 1 ELSE 0 END) AS p25_35,
            SUM(CASE WHEN last_trade_price > 0.35 AND last_trade_price <= 0.45 THEN 1 ELSE 0 END) AS p35_45,
            SUM(CASE WHEN last_trade_price > 0.45 AND last_trade_price <= 0.55 THEN 1 ELSE 0 END) AS p45_55,
            SUM(CASE WHEN last_trade_price > 0.55 AND last_trade_price <= 0.65 THEN 1 ELSE 0 END) AS p55_65,
            SUM(CASE WHEN last_trade_price > 0.65 AND last_trade_price <= 0.75 THEN 1 ELSE 0 END) AS p65_75,
            SUM(CASE WHEN last_trade_price > 0.75 AND last_trade_price <= 0.85 THEN 1 ELSE 0 END) AS p75_85,
            SUM(CASE WHEN last_trade_price > 0.85 AND last_trade_price <= 0.95 THEN 1 ELSE 0 END) AS p85_95,
            SUM(CASE WHEN last_trade_price > 0.95 THEN 1 ELSE 0 END) AS p95_100
        FROM markets
        WHERE closed = 1 AND last_trade_price IS NOT NULL
    """).fetchone()

    resolution_dist = [
        {"label": "0-5%", "count": resolution_rows["p0_5"] or 0},
        {"label": "5-15%", "count": resolution_rows["p5_15"] or 0},
        {"label": "15-25%", "count": resolution_rows["p15_25"] or 0},
        {"label": "25-35%", "count": resolution_rows["p25_35"] or 0},
        {"label": "35-45%", "count": resolution_rows["p35_45"] or 0},
        {"label": "45-55%", "count": resolution_rows["p45_55"] or 0},
        {"label": "55-65%", "count": resolution_rows["p55_65"] or 0},
        {"label": "65-75%", "count": resolution_rows["p65_75"] or 0},
        {"label": "75-85%", "count": resolution_rows["p75_85"] or 0},
        {"label": "85-95%", "count": resolution_rows["p85_95"] or 0},
        {"label": "95-100%", "count": resolution_rows["p95_100"] or 0},
    ]

    return {
        "total_resolved": stats["total_resolved"],
        "total_open": stats["total_open"],
        "resolved_with_snapshots": stats["resolved_with_snapshots"],
        "total_markets_with_snapshots": stats["total_markets_with_snapshots"],
        "total_snapshots": stats["total_snapshots"],
        "first_snapshot": stats["first_snapshot"],
        "last_snapshot": stats["last_snapshot"],
        "open_prices": open_prices,
        "resolution_distribution": resolution_dist,
    }


def get_monthly_volume(conn):
    """Monthly volume timeline from markets."""
    rows = conn.execute("""
        SELECT strftime('%Y-%m', created_at) AS period,
               COALESCE(SUM(volume), 0) AS total_volume,
               COUNT(*) AS market_count
        FROM markets
        WHERE created_at IS NOT NULL
        GROUP BY period
        ORDER BY period
    """).fetchall()
    return [dict(r) for r in rows]


def get_volume_lorenz(conn):
    """Get sorted volumes for Lorenz curve computation."""
    rows = conn.execute("""
        SELECT volume FROM markets
        WHERE volume IS NOT NULL AND volume > 0
        ORDER BY volume ASC
    """).fetchall()
    return [r["volume"] for r in rows]


def get_price_change_distribution(conn, period="1d"):
    """Price change distribution for histogram."""
    col_map = {"1d": "one_day_change", "1w": "one_week_change", "1m": "one_month_change"}
    col = col_map.get(period, "one_day_change")
    rows = conn.execute(f"""
        SELECT {col} AS change
        FROM markets
        WHERE closed = 0 AND {col} IS NOT NULL
        ORDER BY {col}
    """).fetchall()
    return [r["change"] for r in rows]


def get_category_resolution_rates(conn):
    """Resolution rates by category."""
    rows = conn.execute("""
        SELECT et.tag_label, et.tag_slug,
               COUNT(DISTINCT m.id) AS total_markets,
               SUM(CASE WHEN m.closed = 1 AND m.last_trade_price >= 0.95 THEN 1 ELSE 0 END) AS resolved_yes,
               SUM(CASE WHEN m.closed = 1 AND m.last_trade_price <= 0.05 THEN 1 ELSE 0 END) AS resolved_no,
               SUM(CASE WHEN m.closed = 1 THEN 1 ELSE 0 END) AS total_resolved
        FROM event_tags et
        JOIN markets m ON m.event_id = et.event_id
        GROUP BY et.tag_slug
        HAVING total_resolved > 10
        ORDER BY SUM(m.volume) DESC
    """).fetchall()
    return [dict(r) for r in rows]
