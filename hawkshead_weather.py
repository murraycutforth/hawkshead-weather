#!/usr/bin/env python3
"""
Hawkshead Weather Data Tool

Fetches historical weather data for Hawkshead, Lake District from Open-Meteo API
(ERA5 reanalysis), computes temperature statistics, and generates a static HTML
report with interactive charts and thermal property calculations.

Usage:
    python hawkshead_weather.py --start 2025-10-01 --end 2026-03-31
    python hawkshead_weather.py --start 2025-10-01 --end 2026-03-31 --energy 5000 --internal-temp 20
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# Hawkshead coordinates (village centre)
HAWKSHEAD_LAT = 54.375
HAWKSHEAD_LON = -2.999

# Open-Meteo Historical Weather API endpoint
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"


def fetch_weather_data(start_date: str, end_date: str) -> dict:
    """
    Fetch daily temperature data from Open-Meteo Historical API.
    Uses ERA5 reanalysis data at ~9km resolution.

    Returns dict with keys: dates, temp_max, temp_min, temp_mean
    """
    params = {
        "latitude": HAWKSHEAD_LAT,
        "longitude": HAWKSHEAD_LON,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
        "timezone": "Europe/London",
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{ARCHIVE_API}?{query}"

    print(f"Fetching weather data from Open-Meteo...")
    print(f"  Location: Hawkshead ({HAWKSHEAD_LAT}°N, {HAWKSHEAD_LON}°W)")
    print(f"  Period: {start_date} to {end_date}")
    print(f"  Source: ERA5 reanalysis via Open-Meteo")
    print(f"  URL: {url}")

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "HawksheadWeatherTool/1.0")
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
    except urllib.error.URLError as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing response: {e}")
        sys.exit(1)

    if "daily" not in data:
        print(f"Unexpected API response: {json.dumps(data, indent=2)[:500]}")
        sys.exit(1)

    daily = data["daily"]

    result = {
        "dates": daily["time"],
        "temp_max": daily["temperature_2m_max"],
        "temp_min": daily["temperature_2m_min"],
        "temp_mean": daily["temperature_2m_mean"],
        "api_latitude": data.get("latitude"),
        "api_longitude": data.get("longitude"),
    }

    # Filter out any None values (missing data)
    valid_count = sum(1 for t in result["temp_mean"] if t is not None)
    total_count = len(result["dates"])
    print(f"  Retrieved {total_count} days of data ({valid_count} with valid temperature readings)")

    return result


def compute_statistics(weather_data: dict) -> dict:
    """Compute summary statistics from the weather data."""
    means = [t for t in weather_data["temp_mean"] if t is not None]
    maxes = [t for t in weather_data["temp_max"] if t is not None]
    mins = [t for t in weather_data["temp_min"] if t is not None]

    if not means:
        return {"error": "No valid temperature data found"}

    stats = {
        "period_avg_temp": sum(means) / len(means),
        "period_max_temp": max(maxes) if maxes else None,
        "period_min_temp": min(mins) if mins else None,
        "period_avg_max": sum(maxes) / len(maxes) if maxes else None,
        "period_avg_min": sum(mins) / len(mins) if mins else None,
        "num_frost_days": sum(1 for t in mins if t < 0),
        "num_days": len(means),
        "num_days_below_5": sum(1 for t in means if t < 5),
        "num_days_below_0": sum(1 for t in means if t < 0),
    }

    return stats


def compute_thermal_properties(weather_data: dict, energy_kwh: float,
                                internal_temp: float,
                                temp_uncertainty: float = 1.0) -> dict:
    """
    Compute thermal properties of the house.

    Key metric: Heat loss coefficient (HLC) in W/K
    This represents the total heat loss rate per degree of temperature
    difference between inside and outside.

    HLC = Total Energy / (Total Degree-Hours) converted to appropriate units

    A confidence interval is computed by propagating temp_uncertainty (°C) on
    the internal temperature only as worst-case systematic bounds:
      - HLC lower bound: maximise ΔT (internal+δ) → more degree-hours
      - HLC upper bound: minimise ΔT (internal-δ) → fewer degree-hours

    Also computes:
    - Average power usage (W)
    - Degree-days (heating)
    - Specific heat loss rate (W/°C)
    """
    means = weather_data["temp_mean"]
    num_days = len([t for t in means if t is not None])

    if num_days == 0:
        return {"error": "No valid temperature data"}

    # Compute degree-days (base = internal temperature)
    # A degree-day is one day where outside temp is 1°C below the internal temp
    degree_days = 0.0
    total_degree_hours = 0.0
    total_degree_hours_high = 0.0  # internal+δ, external-δ → lower HLC bound
    total_degree_hours_low = 0.0   # internal-δ, external+δ → upper HLC bound
    for t_ext in means:
        if t_ext is not None:
            delta = internal_temp - t_ext
            if delta > 0:  # Only count when heating is needed
                degree_days += delta
                total_degree_hours += delta * 24  # hours in a day

            delta_high = (internal_temp + temp_uncertainty) - t_ext
            if delta_high > 0:
                total_degree_hours_high += delta_high * 24

            delta_low = (internal_temp - temp_uncertainty) - t_ext
            if delta_low > 0:
                total_degree_hours_low += delta_low * 24

    # Total energy in Wh
    energy_wh = energy_kwh * 1000

    # Period duration
    period_hours = num_days * 24

    # Average power (W)
    avg_power_w = energy_wh / period_hours if period_hours > 0 else 0

    # Heat Loss Coefficient (W/K) = Total Energy (Wh) / Total Degree-Hours (°C·h)
    hlc = energy_wh / total_degree_hours if total_degree_hours > 0 else 0
    hlc_low = energy_wh / total_degree_hours_high if total_degree_hours_high > 0 else 0
    hlc_high = energy_wh / total_degree_hours_low if total_degree_hours_low > 0 else None

    # Average temperature difference
    avg_temp_diff = degree_days / num_days if num_days > 0 else 0

    # Energy per degree-day (kWh/degree-day) — common metric for building energy
    energy_per_dd = energy_kwh / degree_days if degree_days > 0 else 0

    return {
        "energy_kwh": energy_kwh,
        "internal_temp": internal_temp,
        "temp_uncertainty": temp_uncertainty,
        "num_days": num_days,
        "degree_days": round(degree_days, 1),
        "total_degree_hours": round(total_degree_hours, 1),
        "avg_power_w": round(avg_power_w, 1),
        "heat_loss_coefficient_w_per_k": round(hlc, 2),
        "heat_loss_coefficient_w_per_k_low": round(hlc_low, 2),
        "heat_loss_coefficient_w_per_k_high": round(hlc_high, 2) if hlc_high is not None else None,
        "avg_temp_difference": round(avg_temp_diff, 1),
        "energy_per_degree_day_kwh": round(energy_per_dd, 3),
        "estimated_annual_hlc_cost_note": (
            f"At this HLC of {hlc:.0f} W/K, each 1°C reduction in thermostat "
            f"setting saves ~{hlc * 24 / 1000:.1f} kWh/day"
        ),
    }


def generate_html(weather_data: dict, stats: dict, thermal: dict | None,
                   start_date: str, end_date: str) -> str:
    """Generate a self-contained static HTML page with Chart.js plots."""

    # Prepare JSON data for embedding
    dates_json = json.dumps(weather_data["dates"])
    temp_max_json = json.dumps(weather_data["temp_max"])
    temp_min_json = json.dumps(weather_data["temp_min"])
    temp_mean_json = json.dumps(weather_data["temp_mean"])
    stats_json = json.dumps(stats, indent=2)
    thermal_json = json.dumps(thermal, indent=2) if thermal else "null"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hawkshead Weather Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
    <style>
        :root {{
            --bg: #f8f9fa;
            --card-bg: #ffffff;
            --text: #2c3e50;
            --text-muted: #6c757d;
            --accent: #3498db;
            --accent-warm: #e67e22;
            --accent-cool: #2980b9;
            --border: #dee2e6;
            --frost: #74b9ff;
            --max-red: #e74c3c;
            --min-blue: #2980b9;
            --mean-green: #27ae60;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 2rem 1rem;
        }}

        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}

        h1 {{
            font-size: 1.8rem;
            font-weight: 600;
            margin-bottom: 0.3rem;
            color: var(--text);
        }}

        .subtitle {{
            color: var(--text-muted);
            font-size: 0.95rem;
            margin-bottom: 2rem;
        }}

        .card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            border: 1px solid var(--border);
        }}

        .card h2 {{
            font-size: 1.15rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--text);
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
        }}

        .stat-item {{
            text-align: center;
            padding: 0.75rem;
            background: var(--bg);
            border-radius: 8px;
        }}

        .stat-value {{
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--accent);
        }}

        .stat-value.warm {{ color: var(--max-red); }}
        .stat-value.cool {{ color: var(--min-blue); }}
        .stat-value.frost {{ color: var(--frost); }}

        .stat-label {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.2rem;
        }}

        .chart-container {{
            position: relative;
            height: 400px;
            margin: 1rem 0;
        }}

        .form-section {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1rem;
            margin-bottom: 1rem;
        }}

        .form-group {{
            display: flex;
            flex-direction: column;
        }}

        .form-group label {{
            font-size: 0.85rem;
            font-weight: 500;
            margin-bottom: 0.3rem;
            color: var(--text-muted);
        }}

        .form-group input {{
            padding: 0.6rem 0.8rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.95rem;
            color: var(--text);
            background: var(--bg);
        }}

        .form-group input:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.15);
        }}

        .btn {{
            display: inline-block;
            padding: 0.65rem 1.5rem;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 0.95rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }}

        .btn:hover {{ background: #2980b9; }}
        .btn:disabled {{ background: #bdc3c7; cursor: not-allowed; }}

        .thermal-results {{
            display: none;
        }}

        .thermal-results.visible {{
            display: block;
        }}

        .thermal-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }}

        .thermal-item {{
            padding: 1rem;
            background: var(--bg);
            border-radius: 8px;
        }}

        .thermal-item .value {{
            font-size: 1.4rem;
            font-weight: 700;
            color: var(--accent-warm);
        }}

        .thermal-item .label {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.15rem;
        }}

        .thermal-item .explanation {{
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-top: 0.4rem;
            font-style: italic;
        }}

        .info-note {{
            font-size: 0.82rem;
            color: var(--text-muted);
            padding: 0.8rem;
            background: #edf7ff;
            border-radius: 6px;
            margin-top: 1rem;
            border-left: 3px solid var(--accent);
        }}

        .data-source {{
            font-size: 0.8rem;
            color: var(--text-muted);
            text-align: center;
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid var(--border);
        }}

        .data-source a {{
            color: var(--accent);
            text-decoration: none;
        }}

        #refetch-section {{
            margin-bottom: 1rem;
        }}

        #status-msg {{
            font-size: 0.85rem;
            margin-top: 0.5rem;
            color: var(--text-muted);
        }}

        @media (max-width: 600px) {{
            .form-section {{ grid-template-columns: 1fr; }}
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .chart-container {{ height: 280px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Hawkshead Weather Report</h1>
        <p class="subtitle">High Crag &mdash; temperature data and thermal analysis</p>

        <!-- Date selection form -->
        <div class="card" id="refetch-section">
            <h2>Select Date Range</h2>
            <div class="form-section">
                <div class="form-group">
                    <label for="inp-start">Start date</label>
                    <input type="date" id="inp-start" value="{start_date}">
                </div>
                <div class="form-group">
                    <label for="inp-end">End date</label>
                    <input type="date" id="inp-end" value="{end_date}">
                </div>
            </div>
            <button class="btn" id="btn-fetch" onclick="refetchData()">Fetch Weather Data</button>
            <div id="status-msg"></div>
        </div>

        <!-- Summary stats -->
        <div class="card" id="stats-card">
            <h2>Temperature Summary &mdash; <span id="period-label">{start_date} to {end_date}</span></h2>
            <div class="stats-grid" id="stats-grid">
                <!-- Filled by JS -->
            </div>
        </div>

        <!-- Temperature chart -->
        <div class="card">
            <h2>Daily Temperatures</h2>
            <div class="chart-container">
                <canvas id="tempChart"></canvas>
            </div>
        </div>

        <!-- Thermal properties section -->
        <div class="card">
            <h2>Thermal Analysis</h2>
            <p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:1rem;">
                Enter your heating energy usage and internal temperature to calculate
                thermal properties of your house over the selected period.
            </p>
            <div class="form-section">
                <div class="form-group">
                    <label for="inp-energy">Heating energy used (kWh)</label>
                    <input type="number" id="inp-energy" placeholder="e.g. 5000" step="1" min="0">
                </div>
                <div class="form-group">
                    <label for="inp-internal-temp">Average internal temperature (&deg;C)</label>
                    <input type="number" id="inp-internal-temp" placeholder="e.g. 20" step="0.1" min="0" max="35">
                </div>
                <div class="form-group">
                    <label for="inp-uncertainty">Inside temperature uncertainty (&deg;C)</label>
                    <input type="number" id="inp-uncertainty" value="1.0" step="0.1" min="0" max="10">
                </div>
            </div>
            <button class="btn" onclick="computeThermal()">Calculate Thermal Properties</button>

            <div class="thermal-results" id="thermal-results">
                <div style="margin-top:1rem;">
                    <div class="thermal-grid" id="thermal-grid">
                        <!-- Filled by JS -->
                    </div>
                    <div class="info-note" id="thermal-note"></div>
                </div>
            </div>
        </div>

        <div class="data-source">
            Data source: <a href="https://open-meteo.com/" target="_blank">Open-Meteo</a>
            ERA5 reanalysis &mdash;
            Location: Hawkshead, Lake District ({HAWKSHEAD_LAT}&deg;N, {abs(HAWKSHEAD_LON)}&deg;W)
            &mdash; Generated <span id="gen-time"></span>
        </div>
    </div>

    <script>
    // ---- Embedded data from Python ----
    let weatherDates = {dates_json};
    let tempMax = {temp_max_json};
    let tempMin = {temp_min_json};
    let tempMean = {temp_mean_json};
    let stats = {stats_json};
    let thermalData = {thermal_json};

    const LAT = {HAWKSHEAD_LAT};
    const LON = {HAWKSHEAD_LON};

    let chart = null;

    document.getElementById("gen-time").textContent = new Date().toLocaleDateString("en-GB");

    // ---- Stats display ----
    function renderStats(s) {{
        const grid = document.getElementById("stats-grid");
        grid.innerHTML = `
            <div class="stat-item">
                <div class="stat-value">${{s.period_avg_temp.toFixed(1)}}&deg;C</div>
                <div class="stat-label">Average temperature</div>
            </div>
            <div class="stat-item">
                <div class="stat-value warm">${{s.period_max_temp.toFixed(1)}}&deg;C</div>
                <div class="stat-label">Highest recorded</div>
            </div>
            <div class="stat-item">
                <div class="stat-value cool">${{s.period_min_temp.toFixed(1)}}&deg;C</div>
                <div class="stat-label">Lowest recorded</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${{s.num_days}}</div>
                <div class="stat-label">Days of data</div>
            </div>
            <div class="stat-item">
                <div class="stat-value frost">${{s.num_frost_days}}</div>
                <div class="stat-label">Frost days (min &lt; 0&deg;C)</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${{s.num_days_below_5}}</div>
                <div class="stat-label">Days mean &lt; 5&deg;C</div>
            </div>
        `;
    }}

    // ---- Chart rendering ----
    function renderChart(dates, tMax, tMin, tMean) {{
        const ctx = document.getElementById("tempChart").getContext("2d");

        if (chart) chart.destroy();

        chart = new Chart(ctx, {{
            type: "line",
            data: {{
                labels: dates,
                datasets: [
                    {{
                        label: "Max",
                        data: tMax,
                        borderColor: "#e74c3c",
                        backgroundColor: "rgba(231,76,60,0.08)",
                        fill: "+1",
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.3,
                    }},
                    {{
                        label: "Mean",
                        data: tMean,
                        borderColor: "#27ae60",
                        backgroundColor: "rgba(39,174,96,0.08)",
                        fill: false,
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.3,
                    }},
                    {{
                        label: "Min",
                        data: tMin,
                        borderColor: "#2980b9",
                        backgroundColor: "rgba(41,128,185,0.08)",
                        fill: "-1",
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.3,
                    }},
                ],
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: "index",
                    intersect: false,
                }},
                plugins: {{
                    tooltip: {{
                        callbacks: {{
                            label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y?.toFixed(1) ?? '—'}}\u00b0C`
                        }}
                    }},
                    legend: {{
                        labels: {{ usePointStyle: true, padding: 16 }}
                    }}
                }},
                scales: {{
                    x: {{
                        type: "category",
                        ticks: {{
                            maxTicksLimit: 12,
                            maxRotation: 45,
                        }},
                        grid: {{ display: false }},
                    }},
                    y: {{
                        title: {{ display: true, text: "Temperature (\u00b0C)" }},
                        grid: {{ color: "rgba(0,0,0,0.05)" }},
                    }}
                }}
            }}
        }});
    }}

    // ---- Thermal computation (client-side) ----
    function computeThermal() {{
        const energyKwh = parseFloat(document.getElementById("inp-energy").value);
        const internalTemp = parseFloat(document.getElementById("inp-internal-temp").value);
        const uncertainty = parseFloat(document.getElementById("inp-uncertainty").value) || 1.0;

        if (isNaN(energyKwh) || isNaN(internalTemp) || energyKwh <= 0) {{
            alert("Please enter valid energy usage (kWh) and internal temperature.");
            return;
        }}

        // Compute degree-days and degree-hours for nominal + CI bounds.
        // Systematic worst-case bounds: uncertainty applied to inside temperature only.
        //   High degree-hours (→ low HLC): inside+δ
        //   Low  degree-hours (→ high HLC): inside-δ
        let degreeDays = 0;
        let totalDegreeHours = 0;
        let totalDegreeHoursHigh = 0;
        let totalDegreeHoursLow = 0;
        let validDays = 0;

        for (let i = 0; i < tempMean.length; i++) {{
            if (tempMean[i] !== null) {{
                const delta = internalTemp - tempMean[i];
                if (delta > 0) {{
                    degreeDays += delta;
                    totalDegreeHours += delta * 24;
                }}
                const deltaHigh = (internalTemp + uncertainty) - tempMean[i];
                if (deltaHigh > 0) totalDegreeHoursHigh += deltaHigh * 24;
                const deltaLow = (internalTemp - uncertainty) - tempMean[i];
                if (deltaLow > 0) totalDegreeHoursLow += deltaLow * 24;
                validDays++;
            }}
        }}

        if (validDays === 0 || totalDegreeHours === 0) {{
            alert("No valid heating data for this period.");
            return;
        }}

        const energyWh = energyKwh * 1000;
        const periodHours = validDays * 24;
        const avgPower = energyWh / periodHours;
        const hlc = energyWh / totalDegreeHours;
        const hlcLow = totalDegreeHoursHigh > 0 ? energyWh / totalDegreeHoursHigh : 0;
        const hlcHigh = totalDegreeHoursLow > 0 ? energyWh / totalDegreeHoursLow : null;
        const avgDeltaT = degreeDays / validDays;
        const energyPerDD = energyKwh / degreeDays;
        const savingsPerDegree = hlc * 24 / 1000;

        const hlcCIStr = hlcHigh !== null
            ? `${{hlcLow.toFixed(0)}}&ndash;${{hlcHigh.toFixed(0)}} W/K`
            : `&ge;${{hlcLow.toFixed(0)}} W/K`;

        const grid = document.getElementById("thermal-grid");
        grid.innerHTML = `
            <div class="thermal-item">
                <div class="value">${{hlc.toFixed(0)}} W/K</div>
                <div class="label">Heat Loss Coefficient (HLC)</div>
                <div class="explanation">Total rate of heat loss per degree of
                inside-outside temperature difference. Includes fabric, ventilation,
                and all other losses.</div>
                <div class="explanation" style="margin-top:0.5rem;">
                    <strong>±${{uncertainty}}&deg;C uncertainty &rarr; ${{hlcCIStr}}</strong>
                </div>
            </div>
            <div class="thermal-item">
                <div class="value">${{avgPower.toFixed(0)}} W</div>
                <div class="label">Average heating power</div>
                <div class="explanation">Mean rate of energy consumption over the
                entire period.</div>
            </div>
            <div class="thermal-item">
                <div class="value">${{degreeDays.toFixed(0)}}</div>
                <div class="label">Heating degree-days</div>
                <div class="explanation">Cumulative daily temperature deficit below
                your internal setpoint of ${{internalTemp}}&deg;C. Higher = colder period.</div>
            </div>
            <div class="thermal-item">
                <div class="value">${{avgDeltaT.toFixed(1)}} &deg;C</div>
                <div class="label">Average &Delta;T</div>
                <div class="explanation">Mean difference between internal and external
                temperature over the period.</div>
            </div>
            <div class="thermal-item">
                <div class="value">${{energyPerDD.toFixed(2)}} kWh/DD</div>
                <div class="label">Energy per degree-day</div>
                <div class="explanation">How much energy is used per unit of heating
                demand. Lower is better.</div>
            </div>
            <div class="thermal-item">
                <div class="value">${{savingsPerDegree.toFixed(1)}} kWh/day</div>
                <div class="label">Savings per 1&deg;C reduction</div>
                <div class="explanation">Estimated daily energy saving if you lower
                the thermostat by 1&deg;C.</div>
            </div>
        `;

        document.getElementById("thermal-note").innerHTML =
            `<strong>Interpretation:</strong> Your house has a Heat Loss Coefficient of
            approximately <strong>${{hlc.toFixed(0)}} W/K</strong> (${{hlcCIStr}} accounting for
            &plusmn;${{uncertainty}}&deg;C uncertainty on both temperature readings). This means for every
            1&deg;C difference between inside and outside, the house loses ${{hlc.toFixed(0)}}
            watts of heat continuously. Over ${{validDays}} days with an average temperature
            deficit of ${{avgDeltaT.toFixed(1)}}&deg;C, this required ${{energyKwh.toLocaleString()}}
            kWh of heating energy. A typical well-insulated UK home has an HLC of 100&ndash;200 W/K;
            an older or larger property may be 200&ndash;400+ W/K.`;

        document.getElementById("thermal-results").classList.add("visible");
    }}

    // ---- Re-fetch data from Open-Meteo ----
    async function refetchData() {{
        const startDate = document.getElementById("inp-start").value;
        const endDate = document.getElementById("inp-end").value;

        if (!startDate || !endDate) {{
            alert("Please select both start and end dates.");
            return;
        }}

        const btn = document.getElementById("btn-fetch");
        const statusMsg = document.getElementById("status-msg");
        btn.disabled = true;
        statusMsg.textContent = "Fetching data from Open-Meteo...";

        const url = `https://archive-api.open-meteo.com/v1/archive?latitude=${{LAT}}&longitude=${{LON}}&start_date=${{startDate}}&end_date=${{endDate}}&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean&timezone=Europe/London`;

        try {{
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${{resp.status}}`);
            const data = await resp.json();

            if (!data.daily) throw new Error("No daily data in response");

            weatherDates = data.daily.time;
            tempMax = data.daily.temperature_2m_max;
            tempMin = data.daily.temperature_2m_min;
            tempMean = data.daily.temperature_2m_mean;

            // Recompute stats
            const means = tempMean.filter(t => t !== null);
            const maxes = tempMax.filter(t => t !== null);
            const mins = tempMin.filter(t => t !== null);

            stats = {{
                period_avg_temp: means.reduce((a,b) => a+b, 0) / means.length,
                period_max_temp: Math.max(...maxes),
                period_min_temp: Math.min(...mins),
                num_days: means.length,
                num_frost_days: mins.filter(t => t < 0).length,
                num_days_below_5: means.filter(t => t < 5).length,
            }};

            document.getElementById("period-label").textContent = `${{startDate}} to ${{endDate}}`;
            renderStats(stats);
            renderChart(weatherDates, tempMax, tempMin, tempMean);

            // Hide thermal results (dates changed, needs recalc)
            document.getElementById("thermal-results").classList.remove("visible");

            statusMsg.textContent = `Loaded ${{weatherDates.length}} days of data.`;
        }} catch (err) {{
            statusMsg.textContent = `Error: ${{err.message}}. The Historical API may not have data for very recent dates (up to 5 days lag).`;
        }} finally {{
            btn.disabled = false;
        }}
    }}

    // ---- Pre-fill thermal inputs if data was provided via Python ----
    if (thermalData) {{
        document.getElementById("inp-energy").value = thermalData.energy_kwh;
        document.getElementById("inp-internal-temp").value = thermalData.internal_temp;
        document.getElementById("inp-uncertainty").value = thermalData.temp_uncertainty ?? 1.0;
    }}

    // ---- Initial render ----
    renderStats(stats);
    renderChart(weatherDates, tempMax, tempMin, tempMean);
    </script>
</body>
</html>"""

    return html


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Hawkshead weather data and generate HTML report"
    )
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--energy", type=float, default=None,
                        help="Heating energy usage in kWh (optional)")
    parser.add_argument("--internal-temp", type=float, default=None,
                        help="Average internal temperature in °C (optional)")
    parser.add_argument("--temp-uncertainty", type=float, default=1.0,
                        help="Temperature measurement uncertainty in °C applied to both "
                             "inside and outside readings (default: 1.0)")
    parser.add_argument("--output", default=None,
                        help="Output HTML file path (default: hawkshead_weather_report.html)")
    parser.add_argument("--serve", action="store_true",
                        help="After generating the report, serve it on a local HTTP server")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port for local HTTP server (default: 8000)")

    args = parser.parse_args()

    # Validate dates
    try:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d")
        end_dt = datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError:
        print("Error: Dates must be in YYYY-MM-DD format")
        sys.exit(1)

    if end_dt <= start_dt:
        print("Error: End date must be after start date")
        sys.exit(1)

    # Fetch data
    weather_data = fetch_weather_data(args.start, args.end)

    # Compute statistics
    stats = compute_statistics(weather_data)
    print(f"\n--- Temperature Summary ---")
    print(f"  Average: {stats['period_avg_temp']:.1f}°C")
    print(f"  Max: {stats['period_max_temp']:.1f}°C")
    print(f"  Min: {stats['period_min_temp']:.1f}°C")
    print(f"  Frost days: {stats['num_frost_days']}")
    print(f"  Days with mean < 5°C: {stats['num_days_below_5']}")

    # Compute thermal properties if energy data provided
    thermal = None
    if args.energy is not None and args.internal_temp is not None:
        thermal = compute_thermal_properties(
            weather_data, args.energy, args.internal_temp,
            temp_uncertainty=args.temp_uncertainty
        )
        hlc = thermal['heat_loss_coefficient_w_per_k']
        hlc_low = thermal['heat_loss_coefficient_w_per_k_low']
        hlc_high = thermal['heat_loss_coefficient_w_per_k_high']
        ci_str = f"  (±{args.temp_uncertainty}°C uncertainty → {hlc_low:.0f}–{hlc_high:.0f} W/K)"
        print(f"\n--- Thermal Properties ---")
        print(f"  Heat Loss Coefficient: {hlc:.0f} W/K")
        print(ci_str)
        print(f"  Average power: {thermal['avg_power_w']:.0f} W")
        print(f"  Degree-days: {thermal['degree_days']:.0f}")
        print(f"  Energy per degree-day: {thermal['energy_per_degree_day_kwh']:.3f} kWh/DD")

    # Generate HTML
    html = generate_html(weather_data, stats, thermal, args.start, args.end)

    output_path = args.output or "hawkshead_weather_report.html"
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"\nReport saved to: {output_path}")

    if args.serve:
        import http.server
        import functools
        import os
        import webbrowser

        serve_dir = str(Path(output_path).parent.resolve())
        filename = Path(output_path).name
        port = args.port

        os.chdir(serve_dir)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=serve_dir)
        server = http.server.HTTPServer(("127.0.0.1", port), handler)
        url = f"http://localhost:{port}/{filename}"
        print(f"\nServing at {url}")
        print("Press Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

    return stats["period_avg_temp"]


if __name__ == "__main__":
    main()
