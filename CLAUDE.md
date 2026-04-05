# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

A single-file Python tool that fetches historical weather data for Hawkshead, Lake District (High Crag) from the Open-Meteo ERA5 reanalysis API, computes temperature statistics and optional thermal/heating analysis, and generates a self-contained static HTML report with interactive Chart.js charts.

The generated `hawkshead_weather_report.html` (and its copy `index.html`) is published via GitHub Pages at `https://murraycutforth.github.io/hawkshead-weather/`.

## Commands

**Generate a report:**
```bash
python hawkshead_weather.py --start 2025-10-01 --end 2026-03-31
python hawkshead_weather.py --start 2025-10-01 --end 2026-03-31 --energy 5000 --internal-temp 20
python hawkshead_weather.py --start 2025-10-01 --end 2026-03-31 --serve   # opens browser
```

**Run all tests:**
```bash
python -m pytest test_hawkshead_weather.py -v
```

**Run a single test:**
```bash
python -m pytest test_hawkshead_weather.py::TestComputeStatistics::test_basic_stats -v
```

Note: `TestOpenMeteoAPIConnection` tests make live HTTP requests to `archive-api.open-meteo.com`. ERA5 data has a ~5-day lag, so dates within the last 5 days may fail.

## Architecture

Everything lives in two files:

- **`hawkshead_weather.py`** — the entire pipeline: CLI (`main`) → `fetch_weather_data` (HTTP to Open-Meteo) → `compute_statistics` → `compute_thermal_properties` (optional) → `generate_html`. The HTML output is self-contained: Chart.js is loaded from CDN and the weather data is JSON-embedded in a `<script>` block. The page also re-fetches data client-side (via `fetch()` in JS) when the user changes the date range, so Python only runs once.

- **`test_hawkshead_weather.py`** — `unittest`-based tests split into live API tests (`TestOpenMeteoAPIConnection`) and pure unit tests (`TestComputeStatistics`, `TestComputeThermalProperties`).

## Key thermal metric

The Heat Loss Coefficient (HLC, W/K) is the central output of the thermal analysis:

```
HLC = Total Energy (Wh) / Total Degree-Hours (°C·h)
```

Degree-hours are accumulated only on days where external mean temperature < internal setpoint. A UK well-insulated home is ~100–200 W/K; older/larger properties 200–400+ W/K.
