"""Tests for queries.py - all SQL queries."""

import json
import pytest
import queries


class TestGetStats:
    def test_returns_all_kpis(self, test_conn):
        stats = queries.get_stats(test_conn)
        assert "total_events" in stats
        assert "total_markets" in stats
        assert "total_volume" in stats
        assert "open_markets" in stats
        assert "avg_spread" in stats
        assert "total_snapshots" in stats

    def test_correct_counts(self, test_conn):
        stats = queries.get_stats(test_conn)
        assert stats["total_events"] == 5
        assert stats["total_markets"] == 7
        assert stats["open_markets"] == 3  # mkt_1, mkt_2, mkt_3
        assert stats["total_snapshots"] == 8

    def test_volume_is_positive(self, test_conn):
        stats = queries.get_stats(test_conn)
        assert stats["total_volume"] > 0


class TestGetGrowth:
    def test_returns_periods(self, test_conn):
        growth = queries.get_growth(test_conn, "month")
        assert len(growth) > 0
        assert "period" in growth[0]
        assert "event_count" in growth[0]
        assert "cumulative_volume" in growth[0]

    def test_cumulative_volume_increases(self, test_conn):
        growth = queries.get_growth(test_conn, "month")
        for i in range(1, len(growth)):
            assert growth[i]["cumulative_volume"] >= growth[i - 1]["cumulative_volume"]

    def test_weekly_granularity(self, test_conn):
        growth = queries.get_growth(test_conn, "week")
        assert len(growth) > 0
        # Weekly format: YYYY-WW
        assert "-" in growth[0]["period"]


class TestGetMarkets:
    def test_returns_paginated(self, test_conn):
        result = queries.get_markets(test_conn)
        assert "markets" in result
        assert "total" in result
        assert "page" in result
        assert "pages" in result
        assert result["total"] == 7

    def test_filter_by_status_open(self, test_conn):
        result = queries.get_markets(test_conn, status="open")
        assert all(m["closed"] == 0 for m in result["markets"])
        assert result["total"] == 3

    def test_filter_by_status_closed(self, test_conn):
        result = queries.get_markets(test_conn, status="closed")
        assert all(m["closed"] == 1 for m in result["markets"])
        assert result["total"] == 4

    def test_filter_by_tag(self, test_conn):
        result = queries.get_markets(test_conn, tag="politics")
        assert result["total"] == 2  # mkt_1 and mkt_2 belong to evt_1

    def test_filter_by_search(self, test_conn):
        result = queries.get_markets(test_conn, q="BTC")
        assert result["total"] == 1
        assert "BTC" in result["markets"][0]["question"]

    def test_filter_by_volume_range(self, test_conn):
        result = queries.get_markets(test_conn, volume_min=1000000.0)
        assert all(m["volume"] >= 1000000.0 for m in result["markets"])

    def test_filter_by_volume_max(self, test_conn):
        result = queries.get_markets(test_conn, volume_max=500.0)
        assert all(m["volume"] <= 500.0 for m in result["markets"])

    def test_filter_by_price_min(self, test_conn):
        result = queries.get_markets(test_conn, price_min=0.50)
        assert result["total"] > 0
        assert all(m["last_trade_price"] >= 0.50 for m in result["markets"])

    def test_filter_by_price_max(self, test_conn):
        result = queries.get_markets(test_conn, price_max=0.10)
        assert result["total"] > 0
        assert all(m["last_trade_price"] <= 0.10 for m in result["markets"])

    def test_filter_by_price_range(self, test_conn):
        result = queries.get_markets(test_conn, price_min=0.30, price_max=0.50)
        assert result["total"] > 0
        for m in result["markets"]:
            assert 0.30 <= m["last_trade_price"] <= 0.50

    def test_sort_by_volume(self, test_conn):
        result = queries.get_markets(test_conn, sort="volume", order="desc")
        volumes = [m["volume"] for m in result["markets"] if m["volume"] is not None]
        assert volumes == sorted(volumes, reverse=True)

    def test_sort_by_created(self, test_conn):
        result = queries.get_markets(test_conn, sort="created", order="desc")
        assert len(result["markets"]) > 0

    def test_pagination(self, test_conn):
        result = queries.get_markets(test_conn, per_page=2, page=1)
        assert len(result["markets"]) == 2
        assert result["pages"] == 4  # 7 total / 2 per page = 4 pages

    def test_page_2(self, test_conn):
        result = queries.get_markets(test_conn, per_page=2, page=2)
        assert len(result["markets"]) == 2
        assert result["page"] == 2

    def test_includes_event_title(self, test_conn):
        result = queries.get_markets(test_conn)
        m = next(m for m in result["markets"] if m["id"] == "mkt_1")
        assert m["event_title"] == "Will candidate X win?"

    def test_filter_by_outcome_type(self, test_conn):
        result = queries.get_markets(test_conn, outcome_type="Up")
        assert result["total"] >= 1

    def test_filter_by_date_from(self, test_conn):
        result = queries.get_markets(test_conn, date_from="2024-03-01")
        assert all(m["created_at"] >= "2024-03-01" for m in result["markets"])

    def test_sort_ascending(self, test_conn):
        result = queries.get_markets(test_conn, sort="volume", order="asc")
        volumes = [m["volume"] for m in result["markets"] if m["volume"] is not None and m["volume"] > 0]
        assert volumes == sorted(volumes)

    def test_includes_end_date(self, test_conn):
        result = queries.get_markets(test_conn)
        m = next(m for m in result["markets"] if m["id"] == "mkt_1")
        assert "end_date" in m
        assert m["end_date"] == "2024-11-01T00:00:00Z"

    def test_filter_by_end_date_from(self, test_conn):
        result = queries.get_markets(test_conn, end_date_from="2024-10-01T00:00:00Z")
        for m in result["markets"]:
            assert m["end_date"] is not None
            assert m["end_date"] >= "2024-10-01T00:00:00Z"

    def test_filter_by_end_date_to(self, test_conn):
        result = queries.get_markets(test_conn, end_date_to="2024-06-01T00:00:00Z")
        for m in result["markets"]:
            assert m["end_date"] is not None
            assert m["end_date"] <= "2024-06-01T00:00:00Z"

    def test_filter_by_end_date_range(self, test_conn):
        result = queries.get_markets(
            test_conn,
            end_date_from="2024-10-01T00:00:00Z",
            end_date_to="2024-12-01T00:00:00Z",
        )
        # Only mkt_1 and mkt_2 (end_date = 2024-11-01)
        assert result["total"] == 2
        ids = {m["id"] for m in result["markets"]}
        assert ids == {"mkt_1", "mkt_2"}

    def test_filter_end_date_excludes_null(self, test_conn):
        """Markets without end_date should be excluded when filtering by end_date."""
        result = queries.get_markets(test_conn, end_date_from="2020-01-01T00:00:00Z")
        ids = {m["id"] for m in result["markets"]}
        # mkt_6, mkt_7 have NULL end_date
        assert "mkt_6" not in ids
        assert "mkt_7" not in ids

    def test_sort_by_end_date(self, test_conn):
        result = queries.get_markets(test_conn, sort="end_date", order="asc")
        end_dates = [m["end_date"] for m in result["markets"] if m["end_date"] is not None]
        assert end_dates == sorted(end_dates)

    def test_sort_by_question(self, test_conn):
        result = queries.get_markets(test_conn, sort="question", order="asc")
        questions = [m["question"] for m in result["markets"]]
        assert questions == sorted(questions)

    def test_sort_by_price(self, test_conn):
        result = queries.get_markets(test_conn, sort="price", order="desc")
        prices = [m["last_trade_price"] for m in result["markets"] if m["last_trade_price"] is not None]
        assert prices == sorted(prices, reverse=True)

    def test_sort_by_closed(self, test_conn):
        result = queries.get_markets(test_conn, sort="closed", order="asc")
        statuses = [m["closed"] for m in result["markets"]]
        assert statuses == sorted(statuses)


class TestGetMarket:
    def test_returns_market(self, test_conn):
        market = queries.get_market(test_conn, "mkt_1")
        assert market is not None
        assert market["question"] == "Will X win the election?"
        assert market["event_title"] == "Will candidate X win?"

    def test_not_found(self, test_conn):
        market = queries.get_market(test_conn, "nonexistent")
        assert market is None

    def test_includes_event_tags(self, test_conn):
        market = queries.get_market(test_conn, "mkt_1")
        assert market["event_tags"] is not None


class TestGetMarketHistory:
    def test_returns_snapshots(self, test_conn):
        history = queries.get_market_history(test_conn, "mkt_1")
        assert len(history) == 3

    def test_ordered_by_time(self, test_conn):
        history = queries.get_market_history(test_conn, "mkt_1")
        dates = [h["fetched_at"] for h in history]
        assert dates == sorted(dates)

    def test_parsed_price(self, test_conn):
        history = queries.get_market_history(test_conn, "mkt_1")
        assert history[0]["price"] == 0.55
        assert history[1]["price"] == 0.60
        assert history[2]["price"] == 0.65

    def test_no_snapshots(self, test_conn):
        history = queries.get_market_history(test_conn, "mkt_6")
        assert len(history) == 0


class TestGetSiblingMarkets:
    def test_returns_siblings(self, test_conn):
        siblings = queries.get_sibling_markets(test_conn, "evt_1")
        assert len(siblings) == 2
        ids = [s["id"] for s in siblings]
        assert "mkt_1" in ids
        assert "mkt_2" in ids

    def test_ordered_by_volume(self, test_conn):
        siblings = queries.get_sibling_markets(test_conn, "evt_1")
        volumes = [s["volume"] for s in siblings]
        assert volumes == sorted(volumes, reverse=True)


class TestGetEvent:
    def test_returns_event(self, test_conn):
        event = queries.get_event(test_conn, "evt_1")
        assert event is not None
        assert event["title"] == "Will candidate X win?"
        assert "markets" in event
        assert len(event["markets"]) == 2

    def test_not_found(self, test_conn):
        event = queries.get_event(test_conn, "nonexistent")
        assert event is None

    def test_markets_ordered_by_volume(self, test_conn):
        event = queries.get_event(test_conn, "evt_1")
        volumes = [m["volume"] for m in event["markets"]]
        assert volumes == sorted(volumes, reverse=True)


class TestGetCategories:
    def test_returns_categories(self, test_conn):
        cats = queries.get_categories(test_conn)
        assert len(cats) > 0
        assert "tag_label" in cats[0]
        assert "total_volume" in cats[0]

    def test_sort_by_volume(self, test_conn):
        cats = queries.get_categories(test_conn, sort="volume")
        volumes = [c["total_volume"] for c in cats]
        assert volumes == sorted(volumes, reverse=True)

    def test_sort_by_count(self, test_conn):
        cats = queries.get_categories(test_conn, sort="count")
        counts = [c["market_count"] for c in cats]
        assert counts == sorted(counts, reverse=True)

    def test_includes_resolved_count(self, test_conn):
        cats = queries.get_categories(test_conn)
        sports = next((c for c in cats if c["tag_slug"] == "sports"), None)
        assert sports is not None
        assert sports["resolved_count"] > 0


class TestGetCategoryGrowth:
    def test_returns_growth_data(self, test_conn):
        result = queries.get_category_growth(test_conn, limit=5)
        assert "periods" in result
        assert "tags" in result
        assert "series" in result
        assert len(result["series"]) > 0

    def test_series_match_tags(self, test_conn):
        result = queries.get_category_growth(test_conn, limit=3)
        assert len(result["series"]) <= 3

    def test_series_data_length_matches_periods(self, test_conn):
        result = queries.get_category_growth(test_conn, limit=5)
        for s in result["series"]:
            assert len(s["data"]) == len(result["periods"])


class TestGetVolumeDistribution:
    def test_returns_histogram(self, test_conn):
        dist = queries.get_volume_distribution(test_conn)
        assert len(dist) > 0
        assert "lo" in dist[0]
        assert "hi" in dist[0]
        assert "count" in dist[0]

    def test_buckets_count(self, test_conn):
        dist = queries.get_volume_distribution(test_conn, buckets=10)
        assert len(dist) == 10


class TestGetVolumeScatter:
    def test_returns_points(self, test_conn):
        data = queries.get_volume_scatter(test_conn, "volume", "liquidity", 100)
        assert len(data) > 0
        assert "x" in data[0]
        assert "y" in data[0]

    def test_invalid_column_defaults(self, test_conn):
        data = queries.get_volume_scatter(test_conn, "invalid_col", "liquidity", 100)
        assert len(data) > 0  # Defaults to volume

    def test_sample_limit(self, test_conn):
        data = queries.get_volume_scatter(test_conn, "volume", "liquidity", 2)
        assert len(data) <= 2


class TestGetMovers:
    def test_returns_gainers_and_losers(self, test_conn):
        result = queries.get_movers(test_conn, "1d")
        assert "gainers" in result
        assert "losers" in result

    def test_gainers_positive(self, test_conn):
        result = queries.get_movers(test_conn, "1d")
        if result["gainers"]:
            assert result["gainers"][0]["change"] >= 0

    def test_losers_negative(self, test_conn):
        result = queries.get_movers(test_conn, "1d")
        if result["losers"]:
            assert result["losers"][0]["change"] <= 0

    def test_1w_period(self, test_conn):
        result = queries.get_movers(test_conn, "1w")
        assert "gainers" in result

    def test_1m_period(self, test_conn):
        result = queries.get_movers(test_conn, "1m")
        assert "gainers" in result

    def test_limit(self, test_conn):
        result = queries.get_movers(test_conn, "1d", limit=1)
        assert len(result["gainers"]) <= 1


class TestGetMomentumScatter:
    def test_returns_data(self, test_conn):
        data = queries.get_momentum_scatter(test_conn)
        assert len(data) > 0
        assert "one_day_change" in data[0]
        assert "one_week_change" in data[0]

    def test_only_open_markets(self, test_conn):
        data = queries.get_momentum_scatter(test_conn)
        ids = [d["id"] for d in data]
        assert "mkt_4" not in ids
        assert "mkt_5" not in ids


class TestGetNewestMarkets:
    def test_returns_markets(self, test_conn):
        data = queries.get_newest_markets(test_conn)
        assert len(data) > 0

    def test_ordered_by_created(self, test_conn):
        data = queries.get_newest_markets(test_conn)
        dates = [d["created_at"] for d in data if d["created_at"]]
        assert dates == sorted(dates, reverse=True)

    def test_only_open(self, test_conn):
        data = queries.get_newest_markets(test_conn)
        ids = [d["id"] for d in data]
        assert "mkt_4" not in ids  # closed market


class TestGetResolutionBreakdown:
    def test_returns_counts(self, test_conn):
        data = queries.get_resolution_breakdown(test_conn)
        assert "resolved_yes" in data
        assert "resolved_no" in data
        assert "resolved_ambiguous" in data
        assert "still_open" in data

    def test_correct_values(self, test_conn):
        data = queries.get_resolution_breakdown(test_conn)
        assert data["resolved_yes"] == 1  # mkt_4
        assert data["resolved_no"] == 1  # mkt_5
        assert data["still_open"] == 3  # mkt_1, mkt_2, mkt_3


class TestGetRecentEvents:
    def test_returns_events(self, test_conn):
        events = queries.get_recent_events(test_conn)
        assert len(events) > 0
        assert "title" in events[0]
        assert "market_count" in events[0]

    def test_limit(self, test_conn):
        events = queries.get_recent_events(test_conn, limit=2)
        assert len(events) <= 2

    def test_includes_market_count(self, test_conn):
        events = queries.get_recent_events(test_conn)
        evt1 = next((e for e in events if e["id"] == "evt_1"), None)
        assert evt1 is not None
        assert evt1["market_count"] == 2


class TestGetTopMarketsByVolume:
    def test_returns_top_markets(self, test_conn):
        data = queries.get_top_markets_by_volume(test_conn)
        assert len(data) > 0

    def test_ordered_by_volume_desc(self, test_conn):
        data = queries.get_top_markets_by_volume(test_conn)
        volumes = [d["volume"] for d in data if d["volume"] is not None]
        assert volumes == sorted(volumes, reverse=True)

    def test_limit(self, test_conn):
        data = queries.get_top_markets_by_volume(test_conn, limit=2)
        assert len(data) <= 2


class TestGetTags:
    def test_returns_tags(self, test_conn):
        tags = queries.get_tags(test_conn)
        assert len(tags) > 0
        assert "tag_label" in tags[0]
        assert "tag_slug" in tags[0]
        assert "event_count" in tags[0]

    def test_ordered_by_count(self, test_conn):
        tags = queries.get_tags(test_conn)
        counts = [t["event_count"] for t in tags]
        assert counts == sorted(counts, reverse=True)


class TestGetCalibrationData:
    def test_returns_data_with_pre_resolution_snapshots(self, test_conn):
        data = queries.get_calibration_data(test_conn)
        assert len(data) >= 2

    def test_only_closed_markets(self, test_conn):
        data = queries.get_calibration_data(test_conn)
        for m in data:
            assert m["last_trade_price"] is not None

    def test_has_snapshot_prices(self, test_conn):
        """All returned rows should have snapshot data (INNER JOIN)."""
        data = queries.get_calibration_data(test_conn)
        for m in data:
            assert m["snapshot_prices"] is not None

    def test_excludes_post_resolution_snapshots(self, test_conn):
        """Markets whose only snapshot is at resolution price should be excluded."""
        data = queries.get_calibration_data(test_conn)
        mkt4 = next((m for m in data if m["id"] == "mkt_4"), None)
        if mkt4:
            prices = json.loads(mkt4["snapshot_prices"])
            assert float(prices[0]) == 0.70

    def test_filter_by_category(self, test_conn):
        data = queries.get_calibration_data(test_conn, category="sports")
        assert len(data) > 0
        event_ids = [d["event_id"] for d in data]
        assert "evt_3" in event_ids

    def test_filter_by_volume_min(self, test_conn):
        data = queries.get_calibration_data(test_conn, volume_min=500000)
        for m in data:
            assert m["volume"] >= 500000


class TestGetCalibrationOverview:
    def test_returns_overview_stats(self, test_conn):
        data = queries.get_calibration_overview(test_conn)
        assert "total_resolved" in data
        assert "total_open" in data
        assert "resolved_with_snapshots" in data
        assert "total_markets_with_snapshots" in data
        assert "total_snapshots" in data

    def test_correct_counts(self, test_conn):
        data = queries.get_calibration_overview(test_conn)
        assert data["total_resolved"] == 4
        assert data["total_open"] == 3
        assert data["total_snapshots"] == 8

    def test_has_resolution_distribution(self, test_conn):
        data = queries.get_calibration_overview(test_conn)
        assert "resolution_distribution" in data
        dist = data["resolution_distribution"]
        assert len(dist) == 11
        total = sum(d["count"] for d in dist)
        assert total > 0

    def test_has_open_prices(self, test_conn):
        data = queries.get_calibration_overview(test_conn)
        assert "open_prices" in data
        assert len(data["open_prices"]) > 0

    def test_has_snapshot_date_range(self, test_conn):
        data = queries.get_calibration_overview(test_conn)
        assert data["first_snapshot"] is not None
        assert data["last_snapshot"] is not None

    def test_resolution_distribution_labels(self, test_conn):
        data = queries.get_calibration_overview(test_conn)
        labels = [d["label"] for d in data["resolution_distribution"]]
        assert "0-5%" in labels
        assert "95-100%" in labels


class TestGetMonthlyVolume:
    def test_returns_monthly(self, test_conn):
        data = queries.get_monthly_volume(test_conn)
        assert len(data) > 0
        assert "period" in data[0]
        assert "total_volume" in data[0]

    def test_ordered_by_period(self, test_conn):
        data = queries.get_monthly_volume(test_conn)
        periods = [d["period"] for d in data]
        assert periods == sorted(periods)


class TestGetVolumeLorenz:
    def test_returns_sorted_volumes(self, test_conn):
        volumes = queries.get_volume_lorenz(test_conn)
        assert len(volumes) > 0
        assert volumes == sorted(volumes)

    def test_excludes_zero(self, test_conn):
        volumes = queries.get_volume_lorenz(test_conn)
        assert all(v > 0 for v in volumes)


class TestGetPriceChangeDistribution:
    def test_1d_changes(self, test_conn):
        changes = queries.get_price_change_distribution(test_conn, "1d")
        assert len(changes) > 0

    def test_1w_changes(self, test_conn):
        changes = queries.get_price_change_distribution(test_conn, "1w")
        assert len(changes) > 0


class TestGetCategoryResolutionRates:
    def test_returns_rates(self, test_conn):
        data = queries.get_category_resolution_rates(test_conn)
        assert isinstance(data, list)
        if data:
            assert "tag_label" in data[0]
            assert "resolved_yes" in data[0]
            assert "resolved_no" in data[0]
