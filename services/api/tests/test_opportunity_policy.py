"""Synthetic policy tests; not evidence of live-provider or macOS correctness."""

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from thiezer.domain.opportunity_policy import (
    Evidence,
    Opportunity,
    Policy,
    Profile,
    Status,
    automatic_scope,
    earliest_first,
    evaluate,
)

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
START = NOW + timedelta(hours=8)
END = START + timedelta(hours=2)
UNITS = {'sun_max': 'deg', 'moon_upper_limb_max': 'deg', 'target_clearance_min': 'deg', 'darkness_min': 'index_0_1', 'cloud_max': 'fraction', 'precipitation_max': 'mm/h', 'wind_max': 'm/s', 'aod_max': 'dimensionless', 'pm25_max': 'ug/m3', 'drive_minutes': 'min'}
WEATHER = {'cloud_max', 'precipitation_max', 'wind_max', 'aod_max', 'pm25_max'}


def sample(**changes):
    values = {'sun_max': -25, 'moon_upper_limb_max': -5, 'target_clearance_min': 30, 'darkness_min': 0.85, 'cloud_max': 0.1, 'precipitation_max': 0, 'wind_max': 2, 'aod_max': 0.08, 'pm25_max': 5, 'drive_minutes': 90}
    metrics = {k: Evidence(v, UNITS[k], 'synthetic-test-fixture-v1', 'forecast' if k in WEATHER else 'computed', START, END, NOW) for k, v in values.items()}
    checks = {k: True for k in ('destination_in_scope', 'route_in_scope', 'route_found', 'access_allowed', 'hazards_clear')}
    return replace(Opportunity('fixture-site', Profile.DEEP_SKY, START, END, NOW, metrics, checks), **changes)


class OpportunityPolicyTests(unittest.TestCase):

    def changed(self, key, value, **kwargs):
        o = sample()
        return replace(o, metrics={**o.metrics, key: replace(o.metrics[key], value=value, **kwargs)})

    def test_complete_forecast(self):
        self.assertEqual(evaluate(sample(), Policy()).status, Status.FORECAST_BACKED)

    def test_strict_rejects_moon(self):
        self.assertIn('moon_upper_limb_max', evaluate(self.changed('moon_upper_limb_max', 1), Policy()).reasons)

    def test_explicit_moonlight_opt_out(self):
        self.assertEqual(evaluate(self.changed('moon_upper_limb_max', 1), Policy(strict_moonless=False)).status, Status.FORECAST_BACKED)

    def test_twilight_not_astronomical_night(self):
        self.assertIn('sun_max', evaluate(self.changed('sun_max', -17.9), Policy()).reasons)

    def test_moon_profile_does_not_reject_itself(self):
        o = replace(self.changed('moon_upper_limb_max', 30), profile=Profile.MOON)
        self.assertEqual(evaluate(o, Policy()).status, Status.FORECAST_BACKED)

    def test_sun_profile_does_not_require_night(self):
        o = replace(self.changed('sun_max', 35), profile=Profile.SUN)
        o = replace(o, checks={**o.checks, 'solar_safety_acknowledged': True})
        self.assertEqual(evaluate(o, Policy()).status, Status.FORECAST_BACKED)

    def test_solar_safety_missing(self):
        self.assertEqual(evaluate(sample(profile=Profile.SUN), Policy()).status, Status.NEEDS_VERIFICATION)

    def test_general_sky_has_no_target_altitude(self):
        o = sample(profile=Profile.DARK_SKY)
        o = replace(o, metrics={k: v for k, v in o.metrics.items() if k != 'target_clearance_min'})
        self.assertEqual(evaluate(o, Policy()).status, Status.FORECAST_BACKED)

    def test_target_behind_terrain(self):
        self.assertIn('target_clearance_min', evaluate(self.changed('target_clearance_min', -1), Policy()).reasons)

    def test_each_bad_weather_value_rejects(self):
        for key, value in {'cloud_max': 0.8, 'wind_max': 20, 'aod_max': 0.5, 'pm25_max': 40, 'precipitation_max': 1}.items():
            with self.subTest(key=key):
                self.assertIn(key, evaluate(self.changed(key, value), Policy()).reasons)

    def test_missing_weather_is_not_clear(self):
        o = sample()
        o = replace(o, metrics={k: v for k, v in o.metrics.items() if k != 'cloud_max'})
        self.assertEqual(evaluate(o, Policy()).status, Status.PARTIAL_FORECAST)

    def test_short_air_quality_horizon(self):
        o = self.changed('aod_max', 0.08, valid_to=END - timedelta(minutes=1))
        self.assertEqual(evaluate(o, Policy()).status, Status.PARTIAL_FORECAST)

    def test_midpoint_data_is_insufficient(self):
        o = self.changed('cloud_max', 0.1, valid_from=START + timedelta(minutes=30))
        self.assertIn('cloud_max', evaluate(o, Policy()).unknowns)

    def test_stale_forecast(self):
        o = self.changed('cloud_max', 0.1, issued_at=NOW - timedelta(hours=40))
        self.assertEqual(evaluate(o, Policy()).status, Status.PARTIAL_FORECAST)

    def test_future_issued_forecast(self):
        o = self.changed('cloud_max', 0.1, issued_at=NOW + timedelta(hours=1))
        self.assertIn('cloud_max', evaluate(o, Policy()).unknowns)

    def test_estimate_is_not_forecast(self):
        o = self.changed('cloud_max', 0.1, kind='estimated')
        self.assertIn('cloud_max', evaluate(o, Policy()).unknowns)

    def test_estimated_darkness_is_not_verified(self):
        o = self.changed('darkness_min', 0.9, kind='estimated')
        self.assertEqual(evaluate(o, Policy()).status, Status.NEEDS_VERIFICATION)

    def test_unit_mismatch_not_silent(self):
        o = self.changed('wind_max', 2, unit='km/h')
        self.assertIn('wind_max', evaluate(o, Policy()).unknowns)

    def test_out_of_range_fraction_unknown(self):
        self.assertIn('cloud_max', evaluate(self.changed('cloud_max', 80), Policy()).unknowns)

    def test_unknown_geometry_not_plan(self):
        o = sample(metrics={})
        self.assertEqual(evaluate(o, Policy()).status, Status.INSUFFICIENT_DATA)

    def test_known_wrong_country_rejected(self):
        o = sample()
        o = replace(o, checks={**o.checks, 'destination_in_scope': False})
        self.assertEqual(evaluate(o, Policy()).status, Status.REJECTED)

    def test_route_crossing_border_rejected(self):
        o = sample()
        o = replace(o, checks={**o.checks, 'route_in_scope': False})
        self.assertIn('route_in_scope', evaluate(o, Policy()).reasons)

    def test_unknown_access_keeps_conditional_candidate(self):
        o = sample()
        o = replace(o, checks={**o.checks, 'access_allowed': None})
        self.assertEqual(evaluate(o, Policy()).status, Status.NEEDS_VERIFICATION)

    def test_unknown_route_not_verified(self):
        o = sample()
        o = replace(o, checks={**o.checks, 'route_found': None})
        self.assertEqual(evaluate(o, Policy()).status, Status.NEEDS_VERIFICATION)

    def test_closed_access_rejected(self):
        o = sample()
        o = replace(o, checks={**o.checks, 'access_allowed': False})
        self.assertIn('access_allowed', evaluate(o, Policy()).reasons)

    def test_hazard_rejected(self):
        o = sample()
        o = replace(o, checks={**o.checks, 'hazards_clear': False})
        self.assertEqual(evaluate(o, Policy()).status, Status.REJECTED)

    def test_duration_whole_window(self):
        self.assertIn('duration', evaluate(sample(end_utc=START + timedelta(minutes=30)), Policy()).reasons)

    def test_past_window_rejected(self):
        self.assertIn('future_interval', evaluate(sample(as_of_utc=START + timedelta(minutes=1)), Policy()).reasons)

    def test_drive_budget(self):
        self.assertIn('drive_minutes', evaluate(self.changed('drive_minutes', 240), Policy()).reasons)

    def test_all_weather_unknown_is_astronomy_only(self):
        o = sample()
        o = replace(o, metrics={k: v for k, v in o.metrics.items() if k not in WEATHER})
        self.assertEqual(evaluate(o, Policy()).status, Status.ASTRONOMY_ONLY)

    def test_partial_forecast_preserves_known_checks(self):
        o = sample()
        o = replace(o, metrics={k: v for k, v in o.metrics.items() if k != 'aod_max'})
        result = evaluate(o, Policy())
        self.assertEqual(result.status, Status.PARTIAL_FORECAST)
        self.assertTrue(result.checks['cloud_max'])
        self.assertIsNone(result.checks['aod_max'])

    def test_nonfinite_rejected(self):
        for value in [float('nan'), float('inf'), -float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.changed('cloud_max', value)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            sample(start_utc=datetime(2026, 9, 6, 20))

    def test_empty_interval_rejected(self):
        with self.assertRaises(ValueError):
            sample(end_utc=START)

    def test_checks_reject_truthy_strings(self):
        with self.assertRaises(ValueError):
            sample(checks={'route_found': 'false'})

    def test_immutable_metrics(self):
        with self.assertRaises(TypeError):
            sample().metrics['sun_max'] = None

    def test_invalid_policy(self):
        for change in ({'max_cloud_fraction': 2}, {'min_duration_minutes': 0}, {'max_sun_altitude_deg': 10}, {'max_wind_mps': float('nan')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Policy(**change)

    def test_small_country_scope(self):
        s = automatic_scope(country_code='AM', region_id='AM-AG', country_area_km2=30000, country_extent_km=400, policy=Policy())
        self.assertEqual(s.mode, 'country')
        self.assertFalse(s.cross_border)

    def test_large_country_scope(self):
        s = automatic_scope(country_code='US', region_id='US-CA', country_area_km2=9000000, country_extent_km=4500, policy=Policy())
        self.assertEqual(s.mode, 'region')
        self.assertFalse(s.cross_border)

    def test_long_narrow_country_not_small(self):
        s = automatic_scope(country_code='CL', region_id=None, country_area_km2=200000, country_extent_km=2500, policy=Policy())
        self.assertEqual(s.mode, 'nearby_in_country')

    def test_unknown_country_not_worldwide(self):
        s = automatic_scope(country_code=None, region_id=None, country_area_km2=None, country_extent_km=None, policy=Policy())
        self.assertEqual(s.mode, 'location_required')

    def test_unknown_extent_local(self):
        s = automatic_scope(country_code='GE', region_id=None, country_area_km2=None, country_extent_km=None, policy=Policy())
        self.assertEqual(s.mode, 'nearby_in_country')

    def test_invalid_scope_metadata(self):
        with self.assertRaises(ValueError):
            automatic_scope(country_code='am', region_id=None, country_area_km2=None, country_extent_km=None, policy=Policy())

    def test_earliest_first_excludes_rejected(self):
        good = evaluate(sample(), Policy())
        later = replace(good, site_id='later', start_utc=START + timedelta(days=1))
        bad = replace(good, site_id='bad', status=Status.REJECTED)
        self.assertEqual([x.site_id for x in earliest_first([later, bad, good])], ['fixture-site', 'later'])

    def test_evidence_classes_not_mixed(self):
        good = evaluate(sample(), Policy())
        provisional = replace(good, site_id='provisional', status=Status.ASTRONOMY_ONLY, start_utc=START - timedelta(hours=1))
        self.assertEqual(earliest_first([provisional, good])[0].site_id, 'fixture-site')

if __name__ == '__main__':
    unittest.main()
