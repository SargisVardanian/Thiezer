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
  });

  final String provider;
  final String objectId;
  final String name;
  final String objectClass;
  final String attribution;

  factory CelestialObject.fromJson(Map<String, dynamic> json) {
    final identifier = json['identifier'] as Map<String, dynamic>;
    return CelestialObject(
      provider: identifier['provider'] as String,
      objectId: identifier['object_id'] as String,
      name: json['name'] as String,
      objectClass: json['object_class'] as String,
      attribution: json['attribution'] as String,
    );
  }
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
        moonIllumination: (json['moon_illumination_fraction'] as num)
            .toDouble(),
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
        sourceProvider: (json['source_provider'] as String?) ?? 'unknown',
      );
}

class RecommendationResult {
  const RecommendationResult({
    required this.rank,
    required this.place,
    required this.distanceKm,
    required this.bestScore,
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
  ) => RecommendationResponse(
    results: (json['results'] as List<dynamic>)
        .map(
          (dynamic item) =>
              RecommendationResult.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false),
    warnings: (json['warnings'] as List<dynamic>? ?? const <dynamic>[])
        .map((dynamic item) => item as String)
        .toList(growable: false),
    sources: (json['discovery_sources'] as List<dynamic>? ?? const <dynamic>[])
        .map((dynamic item) => item as String)
        .toList(growable: false),
    countryCodes:
        (json['coverage_country_codes'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic item) => item as String)
            .toList(growable: false),
    radiusKm: (json['search_radius_km'] as num).toDouble(),
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
