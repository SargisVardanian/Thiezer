import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.message);

  final String message;

  @override
  String toString() => message;
}

class ThiezerApiClient {
  ThiezerApiClient({
    required String baseUrl,
    http.Client? client,
  })  : _baseUrl = _normalizeBaseUrl(baseUrl),
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
          (dynamic item) =>
              TargetOption.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
  }

  Future<RecommendationResponse> searchRecommendations({
    required GeoPoint location,
    required String target,
    required double radiusKm,
    required String scope,
    String? countryCode,
    Duration horizon = const Duration(days: 7),
  }) async {
    final now = DateTime.now().toUtc();
    final payload = <String, dynamic>{
      'user_location': location.toJson(),
      'target': target,
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
          (dynamic item) =>
              StoreResult.fromJson(item as Map<String, dynamic>),
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
        'Сервер вернул не-JSON ответ (${response.statusCode}).',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = body is Map<String, dynamic>
          ? body['detail']?.toString()
          : response.body;
      throw ApiException(
        detail ?? 'HTTP ${response.statusCode}',
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
}
