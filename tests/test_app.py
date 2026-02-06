"""Tests for app.py - Flask routes and API endpoints."""

import json
import pytest


class TestParseTagsFilter:
    def test_parse_valid_json(self):
        from app import parse_tags
        tags_json = json.dumps([{"label": "Politics"}, {"label": "Elections"}])
        result = parse_tags(tags_json)
        assert result == ["Politics", "Elections"]

    def test_parse_none(self):
        from app import parse_tags
        assert parse_tags(None) == []

    def test_parse_empty_string(self):
        from app import parse_tags
        assert parse_tags("") == []

    def test_parse_invalid_json(self):
        from app import parse_tags
        assert parse_tags("not json") == []

    def test_parse_list_input(self):
        from app import parse_tags
        result = parse_tags([{"label": "Test"}])
        assert result == ["Test"]

    def test_parse_missing_label(self):
        from app import parse_tags
        result = parse_tags(json.dumps([{"id": "1"}, {"label": "Test"}]))
        assert "" in result
        assert "Test" in result

    def test_parse_non_dict_items(self):
        from app import parse_tags
        result = parse_tags(json.dumps(["string1", "string2"]))
        assert result == []


class TestPageRoutes:
    def test_dashboard(self, app_client):
        resp = app_client.get("/")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.data

    def test_markets_page(self, app_client):
        resp = app_client.get("/markets")
        assert resp.status_code == 200
        assert b"Market Explorer" in resp.data

    def test_categories_page(self, app_client):
        resp = app_client.get("/categories")
        assert resp.status_code == 200
        assert b"Category Analytics" in resp.data

    def test_volume_page(self, app_client):
        resp = app_client.get("/volume")
        assert resp.status_code == 200
        assert b"Volume Analytics" in resp.data

    def test_movers_page(self, app_client):
        resp = app_client.get("/movers")
        assert resp.status_code == 200
        assert b"Movers" in resp.data

    def test_calibration_page(self, app_client):
        resp = app_client.get("/calibration")
        assert resp.status_code == 200
        assert b"Calibration" in resp.data

    def test_market_detail_page(self, app_client):
        resp = app_client.get("/market/mkt_1")
        assert resp.status_code == 200
        assert b"Will X win the election?" in resp.data

    def test_market_detail_not_found(self, app_client):
        resp = app_client.get("/market/nonexistent")
        assert resp.status_code == 404

    def test_event_detail_page(self, app_client):
        resp = app_client.get("/event/evt_1")
        assert resp.status_code == 200
        assert b"Will candidate X win?" in resp.data

    def test_event_detail_not_found(self, app_client):
        resp = app_client.get("/event/nonexistent")
        assert resp.status_code == 404


class TestApiStats:
    def test_stats(self, app_client):
        resp = app_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_events"] == 5
        assert data["total_markets"] == 7

    def test_stats_has_all_fields(self, app_client):
        data = app_client.get("/api/stats").get_json()
        for key in ["total_events", "total_markets", "total_volume", "open_markets", "avg_spread", "total_snapshots"]:
            assert key in data


class TestApiGrowth:
    def test_growth_monthly(self, app_client):
        resp = app_client.get("/api/growth?granularity=month")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0
        assert "period" in data[0]

    def test_growth_weekly(self, app_client):
        resp = app_client.get("/api/growth?granularity=week")
        data = resp.get_json()
        assert len(data) > 0


class TestApiMarkets:
    def test_markets_list(self, app_client):
        resp = app_client.get("/api/markets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "markets" in data
        assert "total" in data
        assert data["total"] == 7

    def test_markets_filter_open(self, app_client):
        data = app_client.get("/api/markets?status=open").get_json()
        assert data["total"] == 3
        assert all(m["closed"] == 0 for m in data["markets"])

    def test_markets_filter_closed(self, app_client):
        data = app_client.get("/api/markets?status=closed").get_json()
        assert data["total"] == 4

    def test_markets_filter_tag(self, app_client):
        data = app_client.get("/api/markets?tag=politics").get_json()
        assert data["total"] == 2

    def test_markets_search(self, app_client):
        data = app_client.get("/api/markets?q=BTC").get_json()
        assert data["total"] == 1

    def test_markets_sort(self, app_client):
        data = app_client.get("/api/markets?sort=volume&order=desc").get_json()
        volumes = [m["volume"] for m in data["markets"] if m["volume"] is not None]
        assert volumes == sorted(volumes, reverse=True)

    def test_markets_pagination(self, app_client):
        data = app_client.get("/api/markets?per_page=2&page=1").get_json()
        assert len(data["markets"]) == 2
        assert data["pages"] == 4

    def test_markets_volume_min(self, app_client):
        data = app_client.get("/api/markets?volume_min=1000000").get_json()
        assert all(m["volume"] >= 1000000 for m in data["markets"])

    def test_markets_price_min(self, app_client):
        data = app_client.get("/api/markets?price_min=0.50").get_json()
        assert data["total"] > 0
        assert all(m["last_trade_price"] >= 0.50 for m in data["markets"])

    def test_markets_price_max(self, app_client):
        data = app_client.get("/api/markets?price_max=0.10").get_json()
        assert data["total"] > 0
        assert all(m["last_trade_price"] <= 0.10 for m in data["markets"])

    def test_markets_price_range(self, app_client):
        data = app_client.get("/api/markets?price_min=0.30&price_max=0.50").get_json()
        assert data["total"] > 0
        for m in data["markets"]:
            assert 0.30 <= m["last_trade_price"] <= 0.50

    def test_markets_invalid_page(self, app_client):
        """Should handle non-integer page gracefully, defaulting to 1."""
        resp = app_client.get("/api/markets?page=abc")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["page"] == 1

    def test_markets_filter_end_date_from(self, app_client):
        data = app_client.get("/api/markets?end_date_from=2024-10-01T00:00:00Z").get_json()
        for m in data["markets"]:
            assert m["end_date"] is not None
            assert m["end_date"] >= "2024-10-01T00:00:00Z"

    def test_markets_filter_end_date_range(self, app_client):
        data = app_client.get(
            "/api/markets?end_date_from=2024-10-01T00:00:00Z&end_date_to=2024-12-01T00:00:00Z"
        ).get_json()
        assert data["total"] == 2

    def test_markets_sort_end_date(self, app_client):
        data = app_client.get("/api/markets?sort=end_date&order=asc").get_json()
        end_dates = [m["end_date"] for m in data["markets"] if m["end_date"] is not None]
        assert end_dates == sorted(end_dates)

    def test_markets_include_end_date_field(self, app_client):
        data = app_client.get("/api/markets").get_json()
        m = next(m for m in data["markets"] if m["id"] == "mkt_1")
        assert "end_date" in m
        assert m["end_date"] == "2024-11-01T00:00:00Z"

    def test_markets_sort_question(self, app_client):
        data = app_client.get("/api/markets?sort=question&order=asc").get_json()
        questions = [m["question"] for m in data["markets"]]
        assert questions == sorted(questions)

    def test_markets_sort_price(self, app_client):
        data = app_client.get("/api/markets?sort=price&order=desc").get_json()
        prices = [m["last_trade_price"] for m in data["markets"] if m["last_trade_price"] is not None]
        assert prices == sorted(prices, reverse=True)

    def test_markets_sort_closed(self, app_client):
        data = app_client.get("/api/markets?sort=closed&order=asc").get_json()
        statuses = [m["closed"] for m in data["markets"]]
        assert statuses == sorted(statuses)


class TestApiMarketDetail:
    def test_market_detail(self, app_client):
        resp = app_client.get("/api/market/mkt_1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["question"] == "Will X win the election?"

    def test_market_not_found(self, app_client):
        resp = app_client.get("/api/market/nonexistent")
        assert resp.status_code == 404


class TestApiMarketHistory:
    def test_history(self, app_client):
        resp = app_client.get("/api/market/mkt_1/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3

    def test_history_empty(self, app_client):
        resp = app_client.get("/api/market/mkt_6/history")
        data = resp.get_json()
        assert len(data) == 0

    def test_history_has_parsed_price(self, app_client):
        data = app_client.get("/api/market/mkt_1/history").get_json()
        assert data[0]["price"] == 0.55


class TestApiMarketSiblings:
    def test_siblings(self, app_client):
        resp = app_client.get("/api/market/mkt_1/siblings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_siblings_nonexistent(self, app_client):
        resp = app_client.get("/api/market/nonexistent/siblings")
        data = resp.get_json()
        assert data == []


class TestApiEvent:
    def test_event(self, app_client):
        resp = app_client.get("/api/event/evt_1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Will candidate X win?"
        assert len(data["markets"]) == 2

    def test_event_not_found(self, app_client):
        resp = app_client.get("/api/event/nonexistent")
        assert resp.status_code == 404


class TestApiCategories:
    def test_categories(self, app_client):
        resp = app_client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0

    def test_categories_sort_volume(self, app_client):
        data = app_client.get("/api/categories?sort=volume").get_json()
        volumes = [c["total_volume"] for c in data]
        assert volumes == sorted(volumes, reverse=True)

    def test_categories_sort_count(self, app_client):
        data = app_client.get("/api/categories?sort=count").get_json()
        counts = [c["market_count"] for c in data]
        assert counts == sorted(counts, reverse=True)


class TestApiCategoryGrowth:
    def test_category_growth(self, app_client):
        resp = app_client.get("/api/categories/growth")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "periods" in data
        assert "series" in data


class TestApiCategoryResolutionRates:
    def test_resolution_rates(self, app_client):
        resp = app_client.get("/api/categories/resolution_rates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestApiCalibration:
    def test_calibration(self, app_client):
        resp = app_client.get("/api/calibration")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "bins" in data
        assert "count" in data
        assert "by_volume_tier" in data

    def test_calibration_returns_data_with_snapshots(self, app_client):
        """Test data has pre-resolution snapshots for mkt_4 and mkt_5."""
        data = app_client.get("/api/calibration").get_json()
        # mkt_4 (resolved YES, snapshot at 0.70) and mkt_5 (resolved NO, snapshot at 0.30)
        assert data["count"] == 2

    def test_calibration_brier_score(self, app_client):
        data = app_client.get("/api/calibration").get_json()
        if data["count"] > 0:
            assert data["brier_score"] is not None
            assert 0 <= data["brier_score"] <= 1

    def test_calibration_with_category(self, app_client):
        resp = app_client.get("/api/calibration?category=sports")
        assert resp.status_code == 200

    def test_calibration_with_volume_min(self, app_client):
        resp = app_client.get("/api/calibration?volume_min=1000")
        assert resp.status_code == 200

    def test_calibration_empty_with_impossible_filter(self, app_client):
        """Very high volume min should return no data gracefully."""
        data = app_client.get("/api/calibration?volume_min=999999999").get_json()
        assert data["count"] == 0
        assert data["brier_score"] is None


class TestApiCalibrationOverview:
    def test_overview(self, app_client):
        resp = app_client.get("/api/calibration/overview")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_resolved" in data
        assert "total_open" in data
        assert "total_snapshots" in data

    def test_overview_has_resolution_distribution(self, app_client):
        data = app_client.get("/api/calibration/overview").get_json()
        assert "resolution_distribution" in data
        dist = data["resolution_distribution"]
        assert len(dist) == 11
        total = sum(d["count"] for d in dist)
        assert total > 0

    def test_overview_has_open_price_distribution(self, app_client):
        data = app_client.get("/api/calibration/overview").get_json()
        assert "open_price_distribution" in data
        dist = data["open_price_distribution"]
        assert isinstance(dist, list)

    def test_overview_counts(self, app_client):
        data = app_client.get("/api/calibration/overview").get_json()
        assert data["total_resolved"] == 4
        assert data["total_open"] == 3
        assert data["total_snapshots"] == 8

    def test_overview_has_snapshot_dates(self, app_client):
        data = app_client.get("/api/calibration/overview").get_json()
        assert data["first_snapshot"] is not None
        assert data["last_snapshot"] is not None


class TestApiVolumeDistribution:
    def test_distribution(self, app_client):
        resp = app_client.get("/api/volume/distribution")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0


class TestApiVolumeScatter:
    def test_scatter(self, app_client):
        resp = app_client.get("/api/volume/scatter?x=volume&y=liquidity&sample=100")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0
        assert "x" in data[0]

    def test_scatter_spread(self, app_client):
        resp = app_client.get("/api/volume/scatter?x=volume&y=spread")
        assert resp.status_code == 200


class TestApiVolumeLorenz:
    def test_lorenz(self, app_client):
        resp = app_client.get("/api/volume/lorenz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "curve" in data
        assert "gini" in data
        assert 0 <= data["gini"] <= 1


class TestApiVolumeMonthly:
    def test_monthly(self, app_client):
        resp = app_client.get("/api/volume/monthly")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0


class TestApiVolumeTop:
    def test_top(self, app_client):
        resp = app_client.get("/api/volume/top")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0

    def test_top_limit(self, app_client):
        data = app_client.get("/api/volume/top?limit=2").get_json()
        assert len(data) <= 2


class TestApiMovers:
    def test_movers_1d(self, app_client):
        resp = app_client.get("/api/movers?period=1d")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "gainers" in data
        assert "losers" in data

    def test_movers_1w(self, app_client):
        data = app_client.get("/api/movers?period=1w").get_json()
        assert "gainers" in data

    def test_movers_1m(self, app_client):
        data = app_client.get("/api/movers?period=1m").get_json()
        assert "gainers" in data

    def test_movers_limit(self, app_client):
        data = app_client.get("/api/movers?period=1d&limit=1").get_json()
        assert len(data["gainers"]) <= 1


class TestApiMomentum:
    def test_momentum(self, app_client):
        resp = app_client.get("/api/movers/momentum")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0


class TestApiMoversDistribution:
    def test_distribution(self, app_client):
        resp = app_client.get("/api/movers/distribution?period=1d")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_distribution_1w(self, app_client):
        resp = app_client.get("/api/movers/distribution?period=1w")
        assert resp.status_code == 200


class TestApiNewest:
    def test_newest(self, app_client):
        resp = app_client.get("/api/movers/newest")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0

    def test_newest_limit(self, app_client):
        data = app_client.get("/api/movers/newest?limit=1").get_json()
        assert len(data) <= 1


class TestApiResolution:
    def test_resolution(self, app_client):
        resp = app_client.get("/api/resolution")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resolved_yes"] == 1
        assert data["resolved_no"] == 1
        assert data["still_open"] == 3


class TestApiRecentEvents:
    def test_recent_events(self, app_client):
        resp = app_client.get("/api/recent_events")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0

    def test_recent_events_limit(self, app_client):
        data = app_client.get("/api/recent_events?limit=2").get_json()
        assert len(data) <= 2


class TestApiTags:
    def test_tags(self, app_client):
        resp = app_client.get("/api/tags")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0
        assert "tag_label" in data[0]
        assert "tag_slug" in data[0]


class TestFloatHelper:
    def test_valid_float(self):
        from app import _float
        assert _float("123.45") == 123.45

    def test_none(self):
        from app import _float
        assert _float(None) is None

    def test_invalid(self):
        from app import _float
        assert _float("abc") is None

    def test_integer_string(self):
        from app import _float
        assert _float("42") == 42.0
