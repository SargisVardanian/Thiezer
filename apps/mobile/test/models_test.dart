import 'package:flutter_test/flutter_test.dart';
import 'package:thiezer_app/src/models.dart';

void main() {
  test('recommendation response parses backend contract', () {
    final response = RecommendationResponse.fromJson(<String, dynamic>{
      'search_radius_km': 250,
      'coverage_country_codes': <String>['AM', 'GE'],
      'discovery_sources': <String>['openstreetmap_overpass'],
      'warnings': <String>['darkness_is_proxy'],
      'results': <Map<String, dynamic>>[
        <String, dynamic>{
          'rank': 1,
          'distance_km': 81.2,
          'utility': 0.74,
          'warnings': <String>['unverified_place'],
          'place': <String, dynamic>{
            'id': 'osm:node:1',
            'name': 'Test viewpoint',
            'country_code': 'GE',
            'region': 'Test',
            'point': <String, dynamic>{
              'latitude_deg': 41.0,
              'longitude_deg': 44.0,
            },
            'kind': 'viewpoint',
            'verification_status': 'unverified_discovered',
            'darkness_score': 0.82,
            'source_provider': 'openstreetmap_overpass',
          },
          'observation_window': <String, dynamic>{
            'start_utc': '2026-07-28T20:00:00Z',
            'end_utc': '2026-07-28T22:00:00Z',
            'best_time_utc': '2026-07-28T21:00:00Z',
            'best_score': 0.86,
            'mean_score': 0.80,
            'best_conditions': <String, dynamic>{
              'total_cloud_fraction': 0.1,
              'temperature_c': 12.0,
              'wind_speed_mps': 2.0,
              'visibility_m': 40000,
            },
            'best_astronomy': <String, dynamic>{
              'altitude_deg': 45.0,
              'azimuth_deg': 180.0,
              'sun_altitude_deg': -24.0,
              'moon_illumination_fraction': 0.1,
            },
          },
          'routes': <Map<String, dynamic>>[
            <String, dynamic>{
              'provider': 'google_maps',
              'url': 'https://www.google.com/maps/dir/?api=1',
            },
          ],
        },
      ],
    });

    expect(response.radiusKm, 250);
    expect(response.results.single.place.countryCode, 'GE');
    expect(response.results.single.bestScore, closeTo(0.86, 0.0001));
    expect(response.results.single.travelUtility, closeTo(0.74, 0.0001));
    expect(response.countryCodes, containsAll(<String>['AM', 'GE']));
  });

  test('celestial search parses metadata, warnings, and photometry', () {
    final response = CelestialSearchResponse.fromJson(<String, dynamic>{
      'source_attributions': <String>['SIMBAD', 'Gaia DR3'],
      'warnings': <String>['Gaia fallback'],
      'results': <Map<String, dynamic>>[
        <String, dynamic>{
          'identifier': <String, dynamic>{
            'provider': 'gaia',
            'object_id': '123',
          },
          'name': 'Sirius',
          'aliases': <String>['Alpha Canis Majoris'],
          'object_class': 'star',
          'photometry': <String, dynamic>{'gaia_g_magnitude': -1.4},
          'physical': null,
          'host_star': null,
          'attribution': 'SIMBAD; Gaia DR3',
          'warnings': <String>['fixture warning'],
        },
      ],
    });
    expect(response.results.single.apparentMagnitude, closeTo(-1.4, 0.001));
    expect(response.results.single.aliases, contains('Alpha Canis Majoris'));
    expect(response.warnings, contains('Gaia fallback'));
  });

  test('query job parses progress and completed result', () {
    final job = QueryJobStatus.fromJson(<String, dynamic>{
      'query_id': 'abc',
      'stage': 'ranking',
      'created_at_utc': '2026-07-28T20:00:00Z',
      'expires_at_utc': '2026-07-28T20:30:00Z',
      'error': null,
      'result': null,
    });
    expect(job.queryId, 'abc');
    expect(job.stage, 'ranking');
    expect(job.isTerminal, isFalse);
  });
}
