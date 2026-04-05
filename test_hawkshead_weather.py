#!/usr/bin/env python3
"""
Tests for hawkshead_weather.py

Includes a live API test to verify that Open-Meteo returns data for dates
at least two weeks ago, plus unit tests for the computation functions.

Run: python -m pytest test_hawkshead_weather.py -v
  or: python test_hawkshead_weather.py
"""

import json
import unittest
import urllib.request
from datetime import datetime, timedelta

from hawkshead_weather import (
    ARCHIVE_API,
    HAWKSHEAD_LAT,
    HAWKSHEAD_LON,
    compute_statistics,
    compute_thermal_properties,
    fetch_weather_data,
)


class TestOpenMeteoAPIConnection(unittest.TestCase):
    """Live tests that verify the Open-Meteo API returns valid data."""

    def test_api_returns_data_for_two_weeks_ago(self):
        """Verify that ERA5 data is available for a date range ending at least
        two weeks before today. This is the key regression test — if this fails,
        either the API endpoint has changed or something is wrong with the request."""

        end_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")

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

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "HawksheadWeatherTest/1.0")
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())

        # Verify structure
        self.assertIn("daily", data, f"Response missing 'daily' key. Got: {list(data.keys())}")
        daily = data["daily"]
        self.assertIn("time", daily)
        self.assertIn("temperature_2m_max", daily)
        self.assertIn("temperature_2m_min", daily)
        self.assertIn("temperature_2m_mean", daily)

        # Verify we got the expected number of days (14 days inclusive = 15 entries)
        expected_days = (datetime.strptime(end_date, "%Y-%m-%d") -
                         datetime.strptime(start_date, "%Y-%m-%d")).days + 1
        self.assertEqual(len(daily["time"]), expected_days,
                         f"Expected {expected_days} days, got {len(daily['time'])}")

        # Verify data values are plausible temperatures for Hawkshead
        # (should be between -20 and +40 °C at any time of year)
        for temp_list_name in ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"]:
            for val in daily[temp_list_name]:
                if val is not None:
                    self.assertGreater(val, -20,
                                       f"{temp_list_name} value {val} implausibly low")
                    self.assertLess(val, 40,
                                    f"{temp_list_name} value {val} implausibly high")

        # Verify max >= mean >= min for each day
        for i in range(len(daily["time"])):
            t_max = daily["temperature_2m_max"][i]
            t_mean = daily["temperature_2m_mean"][i]
            t_min = daily["temperature_2m_min"][i]
            if all(v is not None for v in [t_max, t_mean, t_min]):
                self.assertGreaterEqual(t_max, t_mean,
                    f"Day {daily['time'][i]}: max ({t_max}) < mean ({t_mean})")
                self.assertGreaterEqual(t_mean, t_min,
                    f"Day {daily['time'][i]}: mean ({t_mean}) < min ({t_min})")

        print(f"  API test passed: {len(daily['time'])} days of data for "
              f"{start_date} to {end_date}")

    def test_api_returns_data_for_known_historical_period(self):
        """Test with a fixed historical date range that should always be available."""
        params = {
            "latitude": HAWKSHEAD_LAT,
            "longitude": HAWKSHEAD_LON,
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
            "timezone": "Europe/London",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{ARCHIVE_API}?{query}"

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "HawksheadWeatherTest/1.0")
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())

        self.assertIn("daily", data)
        self.assertEqual(len(data["daily"]["time"]), 7)
        print(f"  Historical data test passed: 7 days returned for Jan 2024")

    def test_fetch_weather_data_function(self):
        """Test the fetch_weather_data wrapper function with a known date range."""
        result = fetch_weather_data("2024-06-01", "2024-06-07")

        self.assertIn("dates", result)
        self.assertIn("temp_max", result)
        self.assertIn("temp_min", result)
        self.assertIn("temp_mean", result)
        self.assertEqual(len(result["dates"]), 7)
        self.assertEqual(len(result["temp_max"]), 7)

        # Summer temps in Hawkshead should be roughly 5-25°C
        for t in result["temp_mean"]:
            if t is not None:
                self.assertGreater(t, 0, "June mean temp should be above 0°C")
                self.assertLess(t, 30, "June mean temp should be below 30°C")


class TestComputeStatistics(unittest.TestCase):
    """Unit tests for compute_statistics — no network required."""

    def test_basic_stats(self):
        weather_data = {
            "dates": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "temp_max": [8.0, 10.0, 6.0],
            "temp_min": [2.0, 4.0, -1.0],
            "temp_mean": [5.0, 7.0, 2.5],
        }
        stats = compute_statistics(weather_data)

        self.assertAlmostEqual(stats["period_avg_temp"], (5.0 + 7.0 + 2.5) / 3, places=2)
        self.assertEqual(stats["period_max_temp"], 10.0)
        self.assertEqual(stats["period_min_temp"], -1.0)
        self.assertEqual(stats["num_frost_days"], 1)  # min < 0 on day 3
        self.assertEqual(stats["num_days"], 3)
        self.assertEqual(stats["num_days_below_5"], 1)  # mean=2.5 on day 3

    def test_handles_none_values(self):
        weather_data = {
            "dates": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "temp_max": [8.0, None, 6.0],
            "temp_min": [2.0, None, -1.0],
            "temp_mean": [5.0, None, 2.5],
        }
        stats = compute_statistics(weather_data)
        self.assertEqual(stats["num_days"], 2)  # Only 2 valid days
        self.assertAlmostEqual(stats["period_avg_temp"], (5.0 + 2.5) / 2, places=2)


class TestComputeThermalProperties(unittest.TestCase):
    """Unit tests for compute_thermal_properties — no network required."""

    def test_basic_thermal_calculation(self):
        """With known inputs, verify HLC calculation is correct."""
        # 30 days, constant 5°C outside, 20°C inside = 15°C delta
        weather_data = {
            "temp_mean": [5.0] * 30,
        }
        energy_kwh = 3000.0
        internal_temp = 20.0

        result = compute_thermal_properties(weather_data, energy_kwh, internal_temp)

        # degree_days = 15 * 30 = 450
        self.assertAlmostEqual(result["degree_days"], 450.0, places=1)

        # total_degree_hours = 450 * 24 = 10800
        self.assertAlmostEqual(result["total_degree_hours"], 10800.0, places=1)

        # HLC = 3000 * 1000 / 10800 = 277.78 W/K
        expected_hlc = 3_000_000 / 10800
        self.assertAlmostEqual(result["heat_loss_coefficient_w_per_k"],
                               round(expected_hlc, 2), places=1)

        # avg power = 3000 * 1000 / (30 * 24) = 4166.67 W
        expected_power = 3_000_000 / 720
        self.assertAlmostEqual(result["avg_power_w"], round(expected_power, 1), places=0)

        # energy per degree-day = 3000 / 450 = 6.667
        self.assertAlmostEqual(result["energy_per_degree_day_kwh"],
                               round(3000 / 450, 3), places=2)

    def test_no_heating_needed(self):
        """When outside temp >= inside temp, no heating demand."""
        weather_data = {
            "temp_mean": [25.0] * 10,
        }
        result = compute_thermal_properties(weather_data, 100.0, 20.0)
        # total_degree_hours should be 0, so HLC = 0
        self.assertEqual(result["heat_loss_coefficient_w_per_k"], 0)

    def test_mixed_heating_days(self):
        """Some days need heating, some don't."""
        weather_data = {
            "temp_mean": [5.0, 22.0, 10.0, 25.0],  # 2 heating days, 2 not
        }
        result = compute_thermal_properties(weather_data, 500.0, 20.0)

        # Heating days: delta=15 and delta=10, total degree_days = 25
        self.assertAlmostEqual(result["degree_days"], 25.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
