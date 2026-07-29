import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class ApiRequestCancelled implements Exception {
  const ApiRequestCancelled();
}

class ThiezerApiClient {
  ThiezerApiClient({required String baseUrl, http.Client? client})
      : _baseUrl = _normalizeBaseUrl(baseUrl),
        _client = client ?? http.Client();

  String _baseUrl;
  final http.Client _client;

  String get baseUrl => _baseUrl;

  set baseUrl(String value) {
    _baseUrl = _normalizeBaseUrl(value);
  }

  Future<List<TargetOption>> fetchTargets() async {
    final response = await _client
        .get(_uri('/v1/targets'))
        .timeout(const Duration(seconds: 15));
    final decoded = _decode(response);
    return (decoded as List<dynamic>)
        .map(
          (dynamic item) => TargetOption.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
  }

  Future<RecommendationResponse> searchRecommendations({
    required GeoPoint location,
    required String target,
    CelestialObject? catalogObject,
    required double radiusKm,
    required String scope,
    String? countryCode,
    Duration horizon = const Duration(days: 7),
  }) async {
    final payload = _recommendationPayload(
      location: location,
      target: target,
      catalogObject: catalogObject,
      radiusKm: radiusKm,
      scope: scope,
      countryCode: countryCode,
      horizon: horizon,
    );
    final response = await _client
        .post(
          _uri('/v1/recommendations/search'),
          headers: const <String, String>{'content-type': 'application/json'},
          body: jsonEncode(payload),
        )
        .timeout(const Duration(seconds: 60));
    return RecommendationResponse.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<QueryJobStatus> startRecommendationJob({
    required GeoPoint location,
    required String target,
    required double radiusKm,
    required String scope,
    CelestialObject? catalogObject,
    String? countryCode,
    Duration horizon = const Duration(days: 7),
  }) async {
    final response = await _client
        .post(
          _uri('/v1/search-jobs'),
          headers: const <String, String>{'content-type': 'application/json'},
          body: jsonEncode(
            _recommendationPayload(
              location: location,
              target: target,
              catalogObject: catalogObject,
              radiusKm: radiusKm,
              scope: scope,
              countryCode: countryCode,
              horizon: horizon,
            ),
          ),
        )
        .timeout(const Duration(seconds: 20));
    return QueryJobStatus.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<AstronomicalPlanResponse> planAstronomy({
    required GeoPoint location,
    required String target,
    required double radiusKm,
    required String scope,
    required int horizonDays,
    String? countryCode,
  }) async {
    final response = await _client
        .post(
          _uri('/v1/astronomy/plan'),
          headers: const <String, String>{'content-type': 'application/json'},
          body: jsonEncode(<String, dynamic>{
            'user_location': location.toJson(),
            'target': target,
            'start_utc': DateTime.now().toUtc().toIso8601String(),
            'horizon_days': horizonDays,
            'scope': scope,
            'country_code':
                scope == 'country' ? countryCode?.toUpperCase() : null,
            'max_distance_km': radiusKm,
            'max_candidates': 12,
            'max_results': 6,
          }),
        )
        .timeout(const Duration(seconds: 90));
    return AstronomicalPlanResponse.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<QueryJobStatus> fetchRecommendationJob(String queryId) async {
    final response = await _client
        .get(_uri('/v1/search-jobs/${Uri.encodeComponent(queryId)}'))
        .timeout(const Duration(seconds: 20));
    return QueryJobStatus.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<bool> cancelRecommendationJob(String queryId) async {
    final response = await _client
        .delete(_uri('/v1/search-jobs/${Uri.encodeComponent(queryId)}'))
        .timeout(const Duration(seconds: 20));
    final decoded = _decode(response) as Map<String, dynamic>;
    return decoded['cancelled'] as bool;
  }

  Future<CelestialSearchResponse> searchCelestialObjects(
    String query, {
    Set<String> types = const <String>{},
    Future<void>? abortTrigger,
  }) async {
    final parameters = <String, String>{'q': query, 'limit': '8'};
    if (types.isNotEmpty) parameters['types'] = types.join(',');
    final request = http.AbortableRequest(
      'GET',
      _uri('/v1/celestial-objects/search').replace(
        queryParameters: parameters,
      ),
      abortTrigger: abortTrigger,
    );
    try {
      final streamed =
          await _client.send(request).timeout(const Duration(seconds: 15));
      final response = await http.Response.fromStream(streamed);
      return CelestialSearchResponse.fromJson(
        _decode(response) as Map<String, dynamic>,
      );
    } on http.RequestAbortedException {
      throw const ApiRequestCancelled();
    }
  }

  Future<CelestialVisibilityPreview> celestialVisibility({
    required CelestialObject object,
    required GeoPoint point,
  }) async {
    final response = await _client
        .post(
          _uri('/v1/celestial-objects/visibility'),
          headers: const <String, String>{'content-type': 'application/json'},
          body: jsonEncode(<String, dynamic>{
            'provider': object.provider,
            'object_id': object.objectId,
            'point': point.toJson(),
            'timestamp_utc': DateTime.now().toUtc().toIso8601String(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    return CelestialVisibilityPreview.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<List<StoreResult>> searchStores({
    required GeoPoint location,
    required double radiusKm,
    required String scope,
    String? countryCode,
  }) async {
    final payload = <String, dynamic>{
      'user_location': location.toJson(),
      'scope': scope,
      'country_code':
          scope == 'country' && countryCode != null && countryCode.isNotEmpty
              ? countryCode.toUpperCase()
              : null,
      'max_distance_km': radiusKm,
      'max_results': 15,
    };
    final response = await _client
        .post(
          _uri('/v1/stores/search'),
          headers: const <String, String>{'content-type': 'application/json'},
          body: jsonEncode(payload),
        )
        .timeout(const Duration(seconds: 45));
    final decoded = _decode(response) as Map<String, dynamic>;
    return (decoded['results'] as List<dynamic>)
        .map(
          (dynamic item) => StoreResult.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
  }

  Uri _uri(String path) => Uri.parse('$_baseUrl$path');

  dynamic _decode(http.Response response) {
    dynamic body;
    try {
      body = jsonDecode(response.body);
    } on FormatException {
      throw ApiException(
        'The server returned a non-JSON response (${response.statusCode}).',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = body is Map<String, dynamic>
          ? body['detail']?.toString()
          : response.body;
      throw ApiException(
        detail ?? 'HTTP ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return body;
  }

  static String _normalizeBaseUrl(String value) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) {
      return 'http://127.0.0.1:8000';
    }
    return trimmed.endsWith('/')
        ? trimmed.substring(0, trimmed.length - 1)
        : trimmed;
  }

  Map<String, dynamic> _recommendationPayload({
    required GeoPoint location,
    required String target,
    required double radiusKm,
    required String scope,
    required Duration horizon,
    CelestialObject? catalogObject,
    String? countryCode,
  }) {
    final now = DateTime.now().toUtc();
    return <String, dynamic>{
      'user_location': location.toJson(),
      'target': catalogObject == null
          ? <String, dynamic>{'preset': target}
          : <String, dynamic>{
              'catalog_object': <String, dynamic>{
                'provider': catalogObject.provider,
                'object_id': catalogObject.objectId,
              },
            },
      'observation_mode': 'naked_eye',
      'start_utc': now.toIso8601String(),
      'end_utc': now.add(horizon).toIso8601String(),
      'scope': scope,
      'country_code':
          scope == 'country' && countryCode != null && countryCode.isNotEmpty
              ? countryCode.toUpperCase()
              : null,
      'max_distance_km': radiusKm,
      'max_candidates': 16,
      'max_results': 6,
      'minimum_score': 0.28,
      'include_unverified': true,
    };
  }
}
