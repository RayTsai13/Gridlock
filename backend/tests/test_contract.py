"""End-to-end contract tests for the heatmap intermediary.

Covers the wire protocol from ``docs/heatmap-api-contract.md`` and the data
shape the frontend depends on per ``docs/frontend-heatmap.md``:

- SSE handshake order: ``config`` → ``scenario`` → ``frame``
- Monotonic event ids; correct ``text/event-stream`` headers
- ``config`` payload matches the source GeoJSON (bounds / rows / cols)
- ``frame`` cells are sparse ``[row, col, density]`` tuples with valid indices
  and density in ``[0, 1]``
- Centroid formula from the contract reconstructs the original polygon
  centroids in the GeoJSON (so the frontend's lookup will land on real cells)
- ``POST /api/scenario`` accepts the documented ids and rejects unknown ones
- ``POST /api/people`` validates bounds, persists, and affects future frames
- ``DELETE /api/people/{id}`` and ``DELETE /api/people`` follow contract codes

Plain HTTP routes are exercised through ``fastapi.testclient.TestClient``.
The SSE behavior is verified by driving the route's async generator directly
with a fake ``Request`` — that's how we actually consume an open-ended stream
without the HTTP stack buffering the whole infinite body.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import server
from backend.geo import haversine_m
from backend.state import DEFAULT_SCENARIO_ID, VALID_SCENARIO_IDS, State

GEOJSON_PATH = Path("seattle/data/processed/seattle_heatmap_grid.geojson")

CELL_ID_RE = re.compile(r"^r(\d+)_c(\d+)$")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Restore a clean :class:`State` before and after every test.

    Also shrinks the frame cadence so the SSE loop wakes quickly between
    iterations and notices the fake disconnect within the test's lifetime.
    """
    monkeypatch.setattr(server, "FRAME_INTERVAL_S", 0.02)
    server.STATE = State(server.GRID, frame_interval_seconds=server.FRAME_INTERVAL_S)
    yield
    server.STATE = State(server.GRID, frame_interval_seconds=server.FRAME_INTERVAL_S)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(server.app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Fake Request + SSE-stream driver
# ---------------------------------------------------------------------------


class FakeRequest:
    """Stand-in for :class:`fastapi.Request` exposing only the API the
    streaming endpoint touches: ``await is_disconnected()``."""

    def __init__(self) -> None:
        self._disconnected = False

    def disconnect(self) -> None:
        self._disconnected = True

    async def is_disconnected(self) -> bool:
        return self._disconnected


def _parse_sse_event(block: str) -> dict:
    """Parse one ``id:/event:/data:`` SSE record into a dict."""
    out: dict = {}
    for raw_line in block.splitlines():
        if raw_line.startswith("id:"):
            out["id"] = int(raw_line[3:].strip())
        elif raw_line.startswith("event:"):
            out["event"] = raw_line[6:].strip()
        elif raw_line.startswith("data:"):
            out["data"] = json.loads(raw_line[5:].strip())
    return out


async def drive_stream(
    request: FakeRequest,
    n: int,
    timeout: float = 5.0,
) -> list[dict]:
    """Pull ``n`` events from ``server._stream`` then disconnect cleanly."""

    async def _collect() -> list[dict]:
        events: list[dict] = []
        buffer = ""
        async for chunk in server._stream(request):
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if block.strip():
                    events.append(_parse_sse_event(block))
                    if len(events) >= n:
                        request.disconnect()
                        return events
        return events

    return await asyncio.wait_for(_collect(), timeout=timeout)


# ---------------------------------------------------------------------------
# Endpoint headers (StreamingResponse object — no body iteration needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_endpoint_returns_event_stream_headers() -> None:
    response = await server.heatmap_stream(FakeRequest())
    assert response.media_type == "text/event-stream"
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"


# ---------------------------------------------------------------------------
# Connection + handshake
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_initial_handshake_is_config_scenario_playback_then_frame() -> None:
    """Initial state on connect: config, scenario, playback, then a frame."""
    events = await drive_stream(FakeRequest(), n=4)
    assert [e["event"] for e in events] == ["config", "scenario", "playback", "frame"]
    assert [e["id"] for e in events] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_event_ids_are_monotonically_increasing() -> None:
    events = await drive_stream(FakeRequest(), n=4)
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


# ---------------------------------------------------------------------------
# Config payload alignment with the source GeoJSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_payload_matches_loaded_geojson() -> None:
    events = await drive_stream(FakeRequest(), n=1)
    config = events[0]["data"]

    assert set(config) == {"bounds", "rows", "cols"}
    assert set(config["bounds"]) == {"west", "south", "east", "north"}
    assert config["rows"] == server.GRID.rows
    assert config["cols"] == server.GRID.cols
    assert config["bounds"] == server.GRID.bounds.to_dict()


def test_config_bounds_form_uniform_canonical_grid() -> None:
    """The contract's centroid formula assumes uniform cell sizes. Verify the
    loader's bounds + ``rows`` × ``cols`` describe such a grid (i.e. cell
    width and cell height come out exactly the same as the source GeoJSON's
    canonical (0, 0) cell)."""
    bounds = server.GRID.bounds
    raw = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    f00 = next(
        f for f in raw["features"] if f["properties"]["cell_id"] == "r000_c000"
    )
    ring = f00["geometry"]["coordinates"][0]
    src_lons = [p[0] for p in ring]
    src_lats = [p[1] for p in ring]
    src_cell_w = max(src_lons) - min(src_lons)
    src_cell_h = max(src_lats) - min(src_lats)

    derived_cell_w = (bounds.east - bounds.west) / server.GRID.cols
    derived_cell_h = (bounds.north - bounds.south) / server.GRID.rows
    assert derived_cell_w == pytest.approx(src_cell_w)
    assert derived_cell_h == pytest.approx(src_cell_h)


# ---------------------------------------------------------------------------
# Scenario event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_scenario_event_uses_default_scenario() -> None:
    events = await drive_stream(FakeRequest(), n=2)
    assert events[1]["event"] == "scenario"
    assert events[1]["data"] == {"scenario_id": DEFAULT_SCENARIO_ID}


# ---------------------------------------------------------------------------
# Frame schema (used directly by the frontend GeoJSON conversion)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frame_payload_matches_documented_schema() -> None:
    events = await drive_stream(FakeRequest(), n=4)
    frame = events[3]
    assert frame["event"] == "frame"

    payload = frame["data"]
    assert set(payload) == {"timestamp", "state_version", "sim_time", "cells"}
    assert isinstance(payload["timestamp"], (int, float))
    assert isinstance(payload["state_version"], str)
    assert set(payload["sim_time"]) == {"day_of_week", "time_bin", "minute_of_week"}
    assert isinstance(payload["cells"], list)

    rows, cols = server.GRID.rows, server.GRID.cols
    for cell in payload["cells"]:
        assert isinstance(cell, list) and len(cell) == 3
        row, col, density = cell
        assert isinstance(row, int) and 0 <= row < rows
        assert isinstance(col, int) and 0 <= col < cols
        assert isinstance(density, (int, float))
        assert 0.0 <= float(density) <= 1.0


@pytest.mark.asyncio
async def test_frame_cells_are_sparse_no_zero_density() -> None:
    """Contract: cells with density == 0 may be omitted; we omit them."""
    events = await drive_stream(FakeRequest(), n=4)
    cells = events[3]["data"]["cells"]
    assert all(density > 0 for _, _, density in cells)


@pytest.mark.asyncio
async def test_frame_density_reaches_unit_after_normalization() -> None:
    """At least one cell should hit the top of the [0, 1] range."""
    events = await drive_stream(FakeRequest(), n=4)
    cells = events[3]["data"]["cells"]
    assert cells, "expected at least one nonzero cell from the source GeoJSON"
    assert max(density for _, _, density in cells) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Centroid math: contract formula must reconstruct real polygon centroids
# ---------------------------------------------------------------------------


def test_contract_centroid_formula_matches_geojson_polygon_centroids() -> None:
    """The frontend builds its centroid lookup from the contract formula
    ``lon = west + (col + 0.5) * cell_w``,
    ``lat = north - (row + 0.5) * cell_h``.

    For every full (non-partial) GeoJSON cell that the loader keeps, that
    formula must land on the polygon's geometric centroid — otherwise the
    rendered heatmap would be offset from the underlying data.

    The source file's ``row 0`` sits at the south, while the contract
    requires ``row 0`` at the north, so the loader flips rows. This test
    mirrors that flip to verify cell positions end up where the frontend
    expects them.
    """
    raw = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    bounds = server.GRID.bounds
    rows = server.GRID.rows
    cols = server.GRID.cols
    cell_w = (bounds.east - bounds.west) / cols
    cell_h = (bounds.north - bounds.south) / rows

    f00 = next(
        f for f in raw["features"] if f["properties"]["cell_id"] == "r000_c000"
    )
    src_lats_00 = [p[1] for p in f00["geometry"]["coordinates"][0]]
    f_top = next(
        f for f in raw["features"] if f["properties"]["cell_id"] == f"r{rows - 1:03d}_c000"
    )
    src_lats_top = [p[1] for p in f_top["geometry"]["coordinates"][0]]
    source_row_zero_is_north = max(src_lats_00) >= max(src_lats_top)

    checked = 0
    for feature in raw["features"]:
        match = CELL_ID_RE.match(feature["properties"]["cell_id"])
        assert match
        src_row, src_col = int(match.group(1)), int(match.group(2))
        if src_row >= rows or src_col >= cols:
            continue

        contract_row = src_row if source_row_zero_is_north else (rows - 1 - src_row)
        contract_col = src_col

        ring = feature["geometry"]["coordinates"][0]
        unique = ring[:-1] if ring[0] == ring[-1] else ring
        poly_lon = sum(p[0] for p in unique) / len(unique)
        poly_lat = sum(p[1] for p in unique) / len(unique)

        contract_lon = bounds.west + (contract_col + 0.5) * cell_w
        contract_lat = bounds.north - (contract_row + 0.5) * cell_h

        assert poly_lon == pytest.approx(contract_lon, abs=1e-9)
        assert poly_lat == pytest.approx(contract_lat, abs=1e-9)
        checked += 1

    assert checked == rows * cols, "expected every kept cell to be validated"


# ---------------------------------------------------------------------------
# POST /api/scenario
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario_id", sorted(VALID_SCENARIO_IDS))
def test_post_scenario_accepts_documented_ids(
    client: TestClient, scenario_id: str
) -> None:
    response = client.post("/api/scenario", json={"scenario_id": scenario_id})
    assert response.status_code == 200
    assert response.json() == {"scenario_id": scenario_id}
    assert server.STATE.scenario_id == scenario_id


def test_post_scenario_rejects_unknown_id(client: TestClient) -> None:
    response = client.post("/api/scenario", json={"scenario_id": "made-up"})
    assert response.status_code == 400


def test_post_scenario_rejects_missing_field(client: TestClient) -> None:
    response = client.post("/api/scenario", json={})
    assert response.status_code == 400


def test_post_scenario_accepts_active_network_payload(client: TestClient) -> None:
    payload = {
        "scenario_id": "line-1",
        "stops": [
            {
                "id": "custom-a",
                "name": "Custom A",
                "coordinates": [-122.36, 47.62],
            },
            {
                "id": "custom-b",
                "name": "Custom B",
                "coordinates": [-122.34, 47.62],
            },
        ],
        "lines": [
            {
                "id": "custom-line",
                "name": "Custom Line",
                "stopIds": ["custom-a", "custom-b"],
            },
        ],
    }
    response = client.post("/api/scenario", json=payload)
    assert response.status_code == 200
    assert response.json() == {"scenario_id": "line-1"}
    assert [stop.id for stop in server.STATE.active_network.stops] == [
        "custom-a",
        "custom-b",
    ]


@pytest.mark.asyncio
async def test_scenario_post_emits_new_event_on_open_stream() -> None:
    """Per contract ``Scenario change ordering``: when the scenario changes
    while a stream is open, the stream must emit a ``scenario`` event with
    the new id (before any frame from the new scenario)."""
    request = FakeRequest()
    events: list[dict] = []

    async def reader() -> None:
        buffer = ""
        async for chunk in server._stream(request):
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if block.strip():
                    events.append(_parse_sse_event(block))
                    new_seen = any(
                        e["event"] == "scenario"
                        and e["data"]["scenario_id"] == "line-1-2-ballard"
                        for e in events
                    )
                    if new_seen:
                        request.disconnect()
                        return

    async def changer() -> None:
        # Let the initial config + scenario + frame flow first.
        await asyncio.sleep(0.1)
        server.STATE.set_scenario("line-1-2-ballard")
        await server.STATE.notify_change()

    await asyncio.wait_for(asyncio.gather(reader(), changer()), timeout=5.0)

    scenario_events = [e for e in events if e["event"] == "scenario"]
    assert scenario_events[0]["data"]["scenario_id"] == DEFAULT_SCENARIO_ID
    assert any(
        e["data"]["scenario_id"] == "line-1-2-ballard" for e in scenario_events
    )


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------


def test_get_playback_returns_current_sim_time(client: TestClient) -> None:
    response = client.get("/api/playback")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_playing"] is True
    assert set(payload["sim_time"]) == {"day_of_week", "time_bin", "minute_of_week"}


def test_post_playback_updates_play_state(client: TestClient) -> None:
    response = client.post("/api/playback", json={"is_playing": False})
    assert response.status_code == 200
    assert response.json()["is_playing"] is False
    assert server.STATE.playback.is_playing is False


def test_seek_playback_moves_sim_time(client: TestClient) -> None:
    response = client.post(
        "/api/playback/seek",
        json={"day_of_week": 3, "time_bin": 18 * 60},
    )
    assert response.status_code == 200
    sim_time = response.json()["sim_time"]
    assert sim_time["day_of_week"] == 3
    assert sim_time["time_bin"] == 18 * 60


# ---------------------------------------------------------------------------
# /api/people
# ---------------------------------------------------------------------------


def _seattle_inbounds_point() -> dict:
    bounds = server.GRID.bounds
    return {
        "lat": (bounds.north + bounds.south) / 2,
        "lon": (bounds.east + bounds.west) / 2,
    }


def _cell_for_point(lat: float, lon: float) -> tuple[int, int]:
    bounds = server.GRID.bounds
    cell_w = (bounds.east - bounds.west) / server.GRID.cols
    cell_h = (bounds.north - bounds.south) / server.GRID.rows
    return (
        int((bounds.north - lat) / cell_h),
        int((lon - bounds.west) / cell_w),
    )


def _cell_centers() -> list[tuple[int, int, float, float]]:
    bounds = server.GRID.bounds
    cell_w = (bounds.east - bounds.west) / server.GRID.cols
    cell_h = (bounds.north - bounds.south) / server.GRID.rows
    centers: list[tuple[int, int, float, float]] = []
    for row in range(server.GRID.rows):
        lat = bounds.north - (row + 0.5) * cell_h
        for col in range(server.GRID.cols):
            lon = bounds.west + (col + 0.5) * cell_w
            centers.append((row, col, lat, lon))
    return centers


def _mean_density_near(
    cells: list[list[int | float]],
    *,
    lat: float,
    lon: float,
    radius_m: float,
) -> float:
    by_cell = {(int(row), int(col)): float(density) for row, col, density in cells}
    values = [
        by_cell.get((row, col), 0.0)
        for row, col, cell_lat, cell_lon in _cell_centers()
        if haversine_m(lat, lon, cell_lat, cell_lon) <= radius_m
    ]
    assert values, "test location should cover at least one grid cell"
    return sum(values) / len(values)


def _mean_abs_frame_delta(
    left: list[list[int | float]],
    right: list[list[int | float]],
) -> float:
    left_by_cell = {(int(row), int(col)): float(density) for row, col, density in left}
    right_by_cell = {(int(row), int(col)): float(density) for row, col, density in right}
    total = 0.0
    count = server.GRID.rows * server.GRID.cols
    for row in range(server.GRID.rows):
        for col in range(server.GRID.cols):
            total += abs(left_by_cell.get((row, col), 0.0) - right_by_cell.get((row, col), 0.0))
    return total / count


def test_post_people_returns_201_and_persists(client: TestClient) -> None:
    body = {**_seattle_inbounds_point(), "count": 25}
    response = client.post("/api/people", json=body)
    assert response.status_code == 201

    payload = response.json()
    assert set(payload) == {"id", "lat", "lon", "count"}
    assert payload["lat"] == body["lat"]
    assert payload["lon"] == body["lon"]
    assert payload["count"] == 25
    assert isinstance(payload["id"], str) and payload["id"]

    listing = client.get("/api/people").json()
    assert listing == {"people": [payload]}


def test_post_people_defaults_count_to_one(client: TestClient) -> None:
    response = client.post("/api/people", json=_seattle_inbounds_point())
    assert response.status_code == 201
    assert response.json()["count"] == 1


def test_post_people_accepts_visual_tuning_fields(client: TestClient) -> None:
    body = {
        **_seattle_inbounds_point(),
        "count": 10_000,
        "kind": "stadium",
        "duration_minutes": 240,
        "radius_m": 3200,
    }
    response = client.post("/api/people", json=body)
    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "stadium"
    assert payload["duration_minutes"] == 240
    assert payload["radius_m"] == 3200


def test_post_people_rejects_out_of_bounds(client: TestClient) -> None:
    response = client.post("/api/people", json={"lat": 0.0, "lon": 0.0, "count": 1})
    assert response.status_code == 400


def test_post_people_rejects_missing_coordinates(client: TestClient) -> None:
    response = client.post("/api/people", json={"count": 1})
    assert response.status_code == 400


def test_delete_single_person_returns_204(client: TestClient) -> None:
    created = client.post("/api/people", json=_seattle_inbounds_point()).json()
    response = client.delete(f"/api/people/{created['id']}")
    assert response.status_code == 204
    assert client.get("/api/people").json() == {"people": []}


def test_delete_unknown_person_returns_404(client: TestClient) -> None:
    response = client.delete("/api/people/p_does_not_exist")
    assert response.status_code == 404


def test_delete_all_people_returns_204_and_clears(client: TestClient) -> None:
    point = _seattle_inbounds_point()
    client.post("/api/people", json=point)
    client.post("/api/people", json=point)
    assert len(client.get("/api/people").json()["people"]) == 2

    response = client.delete("/api/people")
    assert response.status_code == 204
    assert client.get("/api/people").json() == {"people": []}


def test_added_person_boosts_density_in_their_cell() -> None:
    """The data path the frontend renders: a placed person must show up in
    the next composed frame at their cell's [row, col]."""
    point = _seattle_inbounds_point()
    baseline_cells = {(r, c): d for r, c, d in server.STATE.compose_frame_cells()}

    person = server.STATE.add_person(lat=point["lat"], lon=point["lon"], count=10)

    bounds = server.GRID.bounds
    cell_w = (bounds.east - bounds.west) / server.GRID.cols
    cell_h = (bounds.north - bounds.south) / server.GRID.rows
    expected_col = int((person.lon - bounds.west) / cell_w)
    expected_row = int((bounds.north - person.lat) / cell_h)

    after = {(r, c): d for r, c, d in server.STATE.compose_frame_cells()}
    boosted = after[(expected_row, expected_col)]
    baseline = baseline_cells.get((expected_row, expected_col), 0.0)
    assert boosted > baseline
    assert boosted <= 1.0


# ---------------------------------------------------------------------------
# Visual simulation behavior
# ---------------------------------------------------------------------------


def test_ballard_deployment_cools_new_station_catchment() -> None:
    server.STATE.playback.set_playing(False)
    server.STATE.seek_playback(day_of_week=2, time_bin=8 * 60)
    server.STATE.set_scenario("line-1")
    baseline = server.STATE.compose_frame_cells()

    server.STATE.set_scenario("line-1-2-ballard")
    expanded = server.STATE.compose_frame_cells()

    baseline_ballard = _mean_density_near(
        baseline,
        lat=47.6677,
        lon=-122.3765,
        radius_m=1000,
    )
    expanded_ballard = _mean_density_near(
        expanded,
        lat=47.6677,
        lon=-122.3765,
        radius_m=1000,
    )
    assert expanded_ballard < baseline_ballard * 0.75


def test_underserved_areas_remain_hotter_than_served_catchments() -> None:
    server.STATE.playback.set_playing(False)
    server.STATE.seek_playback(day_of_week=2, time_bin=8 * 60)
    server.STATE.set_scenario("line-1-2-ballard")
    cells = server.STATE.compose_frame_cells()

    served_ballard = _mean_density_near(
        cells,
        lat=47.6677,
        lon=-122.3765,
        radius_m=1000,
    )
    underserved_lake_city = _mean_density_near(
        cells,
        lat=47.7192,
        lon=-122.2950,
        radius_m=1000,
    )
    assert underserved_lake_city > served_ballard * 2.5


def test_crowd_drop_spikes_then_decays_and_spreads() -> None:
    lat = 47.6060
    lon = -122.3330
    row, col = _cell_for_point(lat, lon)

    server.STATE.playback.set_playing(False)
    server.STATE.seek_playback(day_of_week=2, time_bin=12 * 60)
    server.STATE.set_scenario("line-1")
    baseline = {(r, c): d for r, c, d in server.STATE.compose_frame_cells()}

    server.STATE.add_person(
        lat=lat,
        lon=lon,
        count=10_000,
        duration_minutes=240,
        radius_m=2800,
    )
    immediate = {(r, c): d for r, c, d in server.STATE.compose_frame_cells()}

    server.STATE.seek_playback(day_of_week=2, time_bin=14 * 60)
    later = {(r, c): d for r, c, d in server.STATE.compose_frame_cells()}

    assert immediate[(row, col)] > baseline.get((row, col), 0.0) + 0.25
    assert later[(row, col)] < immediate[(row, col)] - 0.20

    centers = _cell_centers()
    immediate_outer = 0
    later_outer = 0
    for cell_row, cell_col, cell_lat, cell_lon in centers:
        distance = haversine_m(lat, lon, cell_lat, cell_lon)
        if not 1600 <= distance <= 2800:
            continue
        baseline_density = baseline.get((cell_row, cell_col), 0.0)
        if immediate.get((cell_row, cell_col), 0.0) > baseline_density + 0.12:
            immediate_outer += 1
        if later.get((cell_row, cell_col), 0.0) > baseline_density + 0.12:
            later_outer += 1
    assert later_outer > immediate_outer


def test_time_profiles_produce_distinct_hotspot_distributions() -> None:
    server.STATE.playback.set_playing(False)
    server.STATE.set_scenario("line-1")

    frames: dict[str, list[list[int | float]]] = {}
    for name, day, time_bin in [
        ("am", 2, 8 * 60),
        ("midday", 2, 12 * 60),
        ("pm", 2, 18 * 60),
        ("evening", 2, 20 * 60),
        ("weekend", 6, 13 * 60),
    ]:
        server.STATE.seek_playback(day_of_week=day, time_bin=time_bin)
        frames[name] = server.STATE.compose_frame_cells()

    assert _mean_abs_frame_delta(frames["am"], frames["midday"]) > 0.08
    assert _mean_abs_frame_delta(frames["midday"], frames["pm"]) > 0.05
    assert _mean_abs_frame_delta(frames["pm"], frames["evening"]) > 0.06
    assert _mean_abs_frame_delta(frames["midday"], frames["weekend"]) > 0.03
