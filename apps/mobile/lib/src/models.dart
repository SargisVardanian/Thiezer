class GeoPoint {
  const GeoPoint(this.latitude, this.longitude);

  final double latitude;
  final double longitude;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'latitude_deg': latitude,
        'longitude_deg': longitude,
      };

  factory GeoPoint.fromJson(Map<String, dynamic> json) => GeoPoint(
        (json['latitude_deg'] as num).toDouble(),
        (json['longitude_deg'] as num).toDouble(),
      );
}

class TargetOption {
  const TargetOption({required this.id, required this.label});

  final String id;
  final String label;

  factory TargetOption.fromJson(Map<String, dynamic> json) =>
      TargetOption(id: json['id'] as String, label: json['label'] as String);
}

class CelestialObject {
  const CelestialObject({
    required this.provider,
    required this.objectId,
    required this.name,
    required this.objectClass,
    required this.attribution,
    required this.aliases,
    required this.warnings,
    this.visualMagnitude,
    this.gaiaMagnitude,
    this.spectralType,
    this.redshift,
    this.orbitalPeriodDays,
    this.hostStarName,
  });

  final String provider;
  final String objectId;
  final String name;
  final String objectClass;
  final String attribution;
  final List<String> aliases;
  final List<String> warnings;
  final double? visualMagnitude;
  final double? gaiaMagnitude;
  final String? spectralType;
  final double? redshift;
  final double? orbitalPeriodDays;
  final String? hostStarName;

  factory CelestialObject.fromJson(Map<String, dynamic> json) {
    final identifier = json['identifier'] as Map<String, dynamic>;
    final photometry = json['photometry'] as Map<String, dynamic>?;
    final physical = json['physical'] as Map<String, dynamic>?;
    final hostStar = json['host_star'] as Map<String, dynamic>?;
    return CelestialObject(
      provider: identifier['provider'] as String,
      objectId: identifier['object_id'] as String,
      name: json['name'] as String,
      objectClass: json['object_class'] as String,
      attribution: json['attribution'] as String,
      aliases: (json['aliases'] as List<dynamic>? ?? const <dynamic>[])
          .map((dynamic item) => item as String)
          .toList(growable: false),
      warnings: (json['warnings'] as List<dynamic>? ?? const <dynamic>[])
          .map((dynamic item) => item as String)
          .toList(growable: false),
      visualMagnitude: (photometry?['visual_magnitude'] as num?)?.toDouble(),
      gaiaMagnitude: (photometry?['gaia_g_magnitude'] as num?)?.toDouble(),
      spectralType: physical?['spectral_type'] as String?,
      redshift: (physical?['redshift'] as num?)?.toDouble(),
      orbitalPeriodDays: (physical?['orbital_period_days'] as num?)?.toDouble(),
      hostStarName: hostStar?['object_id'] as String?,
    );
  }

  double? get apparentMagnitude => visualMagnitude ?? gaiaMagnitude;
}

class CelestialSearchResponse {
  const CelestialSearchResponse({
    required this.results,
    required this.attributions,
    required this.warnings,
  });

  final List<CelestialObject> results;
  final List<String> attributions;
  final List<String> warnings;

  factory CelestialSearchResponse.fromJson(Map<String, dynamic> json) =>
      CelestialSearchResponse(
        results: (json['results'] as List<dynamic>)
            .map(
              (dynamic item) =>
                  CelestialObject.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        attributions:
            (json['source_attributions'] as List<dynamic>? ?? const <dynamic>[])
                .map((dynamic item) => item as String)
                .toList(growable: false),
        warnings: (json['warnings'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic item) => item as String)
            .toList(growable: false),
      );
}

class CelestialVisibilityPreview {
  const CelestialVisibilityPreview({
    required this.altitudeDeg,
    required this.azimuthDeg,
    required this.aboveHorizon,
    required this.capability,
    required this.observationCapabilities,
    required this.attributions,
    required this.warnings,
    this.riseUtc,
    this.setUtc,
    this.culminationUtc,
    this.maximumAltitudeDeg,
  });

  final double altitudeDeg;
  final double azimuthDeg;
  final bool aboveHorizon;
  final String capability;
  final List<String> observationCapabilities;
  final List<String> attributions;
  final List<String> warnings;
  final DateTime? riseUtc;
  final DateTime? setUtc;
  final DateTime? culminationUtc;
  final double? maximumAltitudeDeg;

  factory CelestialVisibilityPreview.fromJson(Map<String, dynamic> json) =>
      CelestialVisibilityPreview(
        altitudeDeg: (json['altitude_deg'] as num).toDouble(),
        azimuthDeg: (json['azimuth_deg'] as num).toDouble(),
        aboveHorizon: json['above_horizon'] as bool,
        capability: json['capability'] as String,
        observationCapabilities:
            (json['observation_capabilities'] as List<dynamic>? ??
                    const <dynamic>[])
                .map((dynamic item) => item as String)
                .toList(growable: false),
        attributions:
            (json['source_attributions'] as List<dynamic>? ?? const <dynamic>[])
                .map((dynamic item) => item as String)
                .toList(growable: false),
        warnings: (json['warnings'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic item) => item as String)
            .toList(growable: false),
        riseUtc: _optionalDate(json['rise_utc']),
        setUtc: _optionalDate(json['set_utc']),
        culminationUtc: _optionalDate(json['culmination_utc']),
        maximumAltitudeDeg: (json['maximum_altitude_deg'] as num?)?.toDouble(),
      );
}

class RouteHandoff {
  const RouteHandoff({required this.provider, required this.url, this.note});

  final String provider;
  final String url;
  final String? note;

  factory RouteHandoff.fromJson(Map<String, dynamic> json) => RouteHandoff(
        provider: json['provider'] as String,
        url: json['url'] as String,
        note: json['note'] as String?,
      );
}

class SkyConditions {
  const SkyConditions({
    required this.cloud,
    required this.temperatureC,
    required this.windMps,
    required this.visibilityM,
  });

  final double cloud;
  final double temperatureC;
  final double windMps;
  final double? visibilityM;

  factory SkyConditions.fromJson(Map<String, dynamic> json) => SkyConditions(
        cloud: (json['total_cloud_fraction'] as num).toDouble(),
        temperatureC: (json['temperature_c'] as num).toDouble(),
        windMps: (json['wind_speed_mps'] as num).toDouble(),
        visibilityM: (json['visibility_m'] as num?)?.toDouble(),
      );
}

class AstronomySnapshot {
  const AstronomySnapshot({
    required this.altitudeDeg,
    required this.azimuthDeg,
    required this.sunAltitudeDeg,
    required this.moonIllumination,
  });

  final double altitudeDeg;
  final double azimuthDeg;
  final double sunAltitudeDeg;
  final double moonIllumination;

  factory AstronomySnapshot.fromJson(Map<String, dynamic> json) =>
      AstronomySnapshot(
        altitudeDeg: (json['altitude_deg'] as num).toDouble(),
        azimuthDeg: (json['azimuth_deg'] as num).toDouble(),
        sunAltitudeDeg: (json['sun_altitude_deg'] as num).toDouble(),
        moonIllumination:
            (json['moon_illumination_fraction'] as num).toDouble(),
      );
}

class ObservationPlace {
  const ObservationPlace({
    required this.id,
    required this.name,
    required this.point,
    required this.kind,
    required this.verificationStatus,
    required this.darknessScore,
    required this.horizonOpennessScore,
    required this.sourceProvider,
    this.countryCode,
    this.region,
  });

  final String id;
  final String name;
  final GeoPoint point;
  final String kind;
  final String verificationStatus;
  final double darknessScore;
  final double horizonOpennessScore;
  final String sourceProvider;
  final String? countryCode;
  final String? region;

  factory ObservationPlace.fromJson(Map<String, dynamic> json) =>
      ObservationPlace(
        id: json['id'] as String,
        name: json['name'] as String,
        countryCode: json['country_code'] as String?,
        region: json['region'] as String?,
        point: GeoPoint.fromJson(json['point'] as Map<String, dynamic>),
        kind: json['kind'] as String,
        verificationStatus: json['verification_status'] as String,
        darknessScore: (json['darkness_score'] as num).toDouble(),
        horizonOpennessScore:
            (json['horizon_openness_score'] as num?)?.toDouble() ?? 0.0,
        sourceProvider: (json['source_provider'] as String?) ?? 'unknown',
      );
}

class RecommendationResult {
  const RecommendationResult({
    required this.rank,
    required this.place,
    required this.distanceKm,
    required this.bestScore,
    required this.travelUtility,
    required this.meanScore,
    required this.bestTime,
    required this.windowStart,
    required this.windowEnd,
    required this.conditions,
    required this.astronomy,
    required this.routes,
    required this.warnings,
  });

  final int rank;
  final ObservationPlace place;
  final double distanceKm;
  final double bestScore;
  final double travelUtility;
  final double meanScore;
  final DateTime bestTime;
  final DateTime windowStart;
  final DateTime windowEnd;
  final SkyConditions conditions;
  final AstronomySnapshot astronomy;
  final List<RouteHandoff> routes;
  final List<String> warnings;

  factory RecommendationResult.fromJson(Map<String, dynamic> json) {
    final window = json['observation_window'] as Map<String, dynamic>;
    return RecommendationResult(
      rank: json['rank'] as int,
      place: ObservationPlace.fromJson(json['place'] as Map<String, dynamic>),
      distanceKm: (json['distance_km'] as num).toDouble(),
      bestScore: (window['best_score'] as num).toDouble(),
      travelUtility: (json['utility'] as num).toDouble(),
      meanScore: (window['mean_score'] as num).toDouble(),
      bestTime: DateTime.parse(window['best_time_utc'] as String).toLocal(),
      windowStart: DateTime.parse(window['start_utc'] as String).toLocal(),
      windowEnd: DateTime.parse(window['end_utc'] as String).toLocal(),
      conditions: SkyConditions.fromJson(
        window['best_conditions'] as Map<String, dynamic>,
      ),
      astronomy: AstronomySnapshot.fromJson(
        window['best_astronomy'] as Map<String, dynamic>,
      ),
      routes: (json['routes'] as List<dynamic>)
          .map(
            (dynamic item) =>
                RouteHandoff.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      warnings: (json['warnings'] as List<dynamic>)
          .map((dynamic item) => item as String)
          .toList(growable: false),
    );
  }
}

class RecommendationResponse {
  const RecommendationResponse({
    required this.results,
    required this.warnings,
    required this.sources,
    required this.countryCodes,
    required this.radiusKm,
  });

  final List<RecommendationResult> results;
  final List<String> warnings;
  final List<String> sources;
  final List<String> countryCodes;
  final double radiusKm;

  factory RecommendationResponse.fromJson(
    Map<String, dynamic> json,
  ) =>
      RecommendationResponse(
        results: (json['results'] as List<dynamic>)
            .map(
              (dynamic item) =>
                  RecommendationResult.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        warnings: (json['warnings'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic item) => item as String)
            .toList(growable: false),
        sources:
            (json['discovery_sources'] as List<dynamic>? ?? const <dynamic>[])
                .map((dynamic item) => item as String)
                .toList(growable: false),
        countryCodes: (json['coverage_country_codes'] as List<dynamic>? ??
                const <dynamic>[])
            .map((dynamic item) => item as String)
            .toList(growable: false),
        radiusKm: (json['search_radius_km'] as num).toDouble(),
      );
}

class AstronomicalPlanCandidate {
  const AstronomicalPlanCandidate({
    required this.place,
    required this.distanceKm,
    required this.bestTime,
    required this.altitudeDeg,
    required this.azimuthDeg,
    required this.score,
  });

  final ObservationPlace place;
  final double distanceKm;
  final DateTime bestTime;
  final double altitudeDeg;
  final double azimuthDeg;
  final double score;

  factory AstronomicalPlanCandidate.fromJson(Map<String, dynamic> json) =>
      AstronomicalPlanCandidate(
        place: ObservationPlace.fromJson(json['place'] as Map<String, dynamic>),
        distanceKm: (json['distance_km'] as num).toDouble(),
        bestTime: DateTime.parse(json['best_time_utc'] as String).toLocal(),
        altitudeDeg: (json['altitude_deg'] as num).toDouble(),
        azimuthDeg: (json['azimuth_deg'] as num).toDouble(),
        score: (json['deterministic_score'] as num).toDouble(),
      );
}

class AstronomicalPlanResponse {
  const AstronomicalPlanResponse({
    required this.bestTime,
    required this.horizonDays,
    required this.candidates,
    required this.warnings,
  });

  final DateTime? bestTime;
  final int horizonDays;
  final List<AstronomicalPlanCandidate> candidates;
  final List<String> warnings;

  factory AstronomicalPlanResponse.fromJson(Map<String, dynamic> json) =>
      AstronomicalPlanResponse(
        bestTime: _optionalDate(json['best_time_utc'])?.toLocal(),
        horizonDays: json['planning_horizon_days'] as int,
        candidates: (json['candidates'] as List<dynamic>)
            .map((item) => AstronomicalPlanCandidate.fromJson(
                item as Map<String, dynamic>))
            .toList(growable: false),
        warnings: (json['warnings'] as List<dynamic>? ?? const <dynamic>[])
            .map((item) => item as String)
            .toList(growable: false),
      );
}

class QueryJobStatus {
  const QueryJobStatus({
    required this.queryId,
    required this.stage,
    required this.expiresAt,
    this.error,
    this.result,
  });

  final String queryId;
  final String stage;
  final DateTime expiresAt;
  final String? error;
  final RecommendationResponse? result;

  bool get isTerminal => const {
        'completed',
        'failed',
        'cancelled',
        'expired',
      }.contains(stage);

  factory QueryJobStatus.fromJson(Map<String, dynamic> json) => QueryJobStatus(
        queryId: json['query_id'] as String,
        stage: json['stage'] as String,
        expiresAt: DateTime.parse(json['expires_at_utc'] as String),
        error: json['error'] as String?,
        result: json['result'] == null
            ? null
            : RecommendationResponse.fromJson(
                json['result'] as Map<String, dynamic>,
              ),
      );
}

class StoreResult {
  const StoreResult({
    required this.id,
    required this.name,
    required this.kind,
    required this.website,
    required this.categories,
    required this.routes,
    this.point,
    this.address,
    this.distanceKm,
  });

  final String id;
  final String name;
  final String kind;
  final String website;
  final List<String> categories;
  final List<RouteHandoff> routes;
  final GeoPoint? point;
  final String? address;
  final double? distanceKm;

  factory StoreResult.fromJson(Map<String, dynamic> json) {
    final store = json['store'] as Map<String, dynamic>;
    return StoreResult(
      id: store['id'] as String,
      name: store['name'] as String,
      kind: store['kind'] as String,
      website: store['website_url'] as String,
      categories: (store['categories'] as List<dynamic>)
          .map((dynamic item) => item as String)
          .toList(growable: false),
      routes: (json['routes'] as List<dynamic>)
          .map(
            (dynamic item) =>
                RouteHandoff.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      point: store['point'] == null
          ? null
          : GeoPoint.fromJson(store['point'] as Map<String, dynamic>),
      address: store['address'] as String?,
      distanceKm: (json['distance_km'] as num?)?.toDouble(),
    );
  }
}

DateTime? _optionalDate(dynamic value) =>
    value is String ? DateTime.parse(value).toLocal() : null;
