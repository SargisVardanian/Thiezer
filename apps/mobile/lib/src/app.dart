import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'celestial_search.dart';
import 'location_service.dart';
import 'models.dart';
import 'starfield.dart';

const _defaultApiUrl = String.fromEnvironment(
  'THIEZER_API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

class ThiezerApp extends StatelessWidget {
  const ThiezerApp({super.key});

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF89B4FF),
      brightness: Brightness.dark,
    );
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Thiezer',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: scheme,
        scaffoldBackgroundColor: Colors.transparent,
        useMaterial3: true,
        inputDecorationTheme: const InputDecorationTheme(
          filled: true,
          border: OutlineInputBorder(),
        ),
      ),
      home: const DiscoveryScreen(),
    );
  }
}

class DiscoveryScreen extends StatefulWidget {
  const DiscoveryScreen({super.key});

  @override
  State<DiscoveryScreen> createState() => _DiscoveryScreenState();
}

class _DiscoveryScreenState extends State<DiscoveryScreen> {
  static const _fallbackTargets = <TargetOption>[
    TargetOption(id: 'milky_way', label: 'Milky Way'),
    TargetOption(id: 'best_night_sky', label: 'Best night sky'),
    TargetOption(id: 'moon', label: 'Moon'),
    TargetOption(id: 'jupiter', label: 'Jupiter'),
    TargetOption(id: 'mars', label: 'Mars'),
    TargetOption(id: 'alpha_centauri', label: 'Alpha Centauri'),
  ];

  late final ThiezerApiClient _api;
  final _locationService = LocationService();
  final _latitudeController = TextEditingController(text: '40.1772');
  final _longitudeController = TextEditingController(text: '44.5035');
  final _countryController = TextEditingController(text: 'AM');
  final _apiController = TextEditingController(text: _defaultApiUrl);

  GeoPoint _location = const GeoPoint(40.1772, 44.5035);
  List<TargetOption> _targets = _fallbackTargets;
  List<RecommendationResult> _recommendations = const [];
  List<StoreResult> _stores = const [];
  String _target = 'milky_way';
  CelestialObject? _catalogObject;
  String _scope = 'adaptive';
  double _radiusKm = 250;
  int _horizonDays = 7;
  bool _loading = false;
  String? _error;
  String? _queryId;
  String? _queryStage;
  bool _queryExpired = false;
  int _searchGeneration = 0;
  int _pageIndex = 0;

  @override
  void initState() {
    super.initState();
    _api = ThiezerApiClient(baseUrl: _defaultApiUrl);
    _loadTargets();
  }

  @override
  void dispose() {
    _latitudeController.dispose();
    _longitudeController.dispose();
    _countryController.dispose();
    _apiController.dispose();
    super.dispose();
  }

  Future<void> _loadTargets() async {
    try {
      final targets = await _api.fetchTargets();
      if (mounted && targets.isNotEmpty) {
        setState(() => _targets = targets);
      }
    } on Object {
      // The fallback list keeps the UI usable before the backend is started.
    }
  }

  bool _readManualCoordinates() {
    final latitude = double.tryParse(_latitudeController.text.trim());
    final longitude = double.tryParse(_longitudeController.text.trim());
    if (latitude == null ||
        longitude == null ||
        latitude.abs() > 90 ||
        longitude.abs() > 180) {
      setState(() => _error = 'Check the latitude and longitude.');
      return false;
    }
    setState(() {
      _location = GeoPoint(latitude, longitude);
      _error = null;
    });
    return true;
  }

  Future<void> _useCurrentLocation() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final point = await _locationService.currentLocation();
      if (!mounted) return;
      setState(() {
        _location = point;
        _latitudeController.text = point.latitude.toStringAsFixed(6);
        _longitudeController.text = point.longitude.toStringAsFixed(6);
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _searchSky() async {
    if (!_readManualCoordinates()) return;
    final generation = ++_searchGeneration;
    setState(() {
      _loading = true;
      _error = null;
      _queryExpired = false;
      _queryStage = 'queued';
      _recommendations = const [];
    });
    try {
      var job = await _api.startRecommendationJob(
        location: _location,
        target: _target,
        catalogObject: _catalogObject,
        radiusKm: _radiusKm,
        scope: _scope,
        countryCode: _countryController.text.trim(),
        horizon: Duration(days: _horizonDays),
      );
      if (!mounted || generation != _searchGeneration) return;
      setState(() {
        _queryId = job.queryId;
        _queryStage = job.stage;
      });
      while (mounted && generation == _searchGeneration && !job.isTerminal) {
        await Future<void>.delayed(const Duration(milliseconds: 350));
        job = await _api.fetchRecommendationJob(job.queryId);
        if (!mounted || generation != _searchGeneration) return;
        setState(() => _queryStage = job.stage);
      }
      if (!mounted || generation != _searchGeneration) return;
      if (job.stage == 'completed' && job.result != null) {
        final response = job.result!;
        setState(() {
          _recommendations = response.results;
          if (response.results.isEmpty) {
            _error = _humanWarnings(response.warnings);
          }
        });
      } else if (job.stage == 'cancelled') {
        setState(
          () => _error =
              'Search cancelled. You can change the settings and try again.',
        );
      } else {
        setState(() => _error = job.error ?? 'Search failed.');
      }
    } on ApiException catch (error) {
      if (!mounted || generation != _searchGeneration) return;
      if (error.statusCode == 404 && _queryId != null) {
        setState(() {
          _queryExpired = true;
          _queryStage = 'expired';
          _error = 'The result expired. Run the search again.';
        });
      } else {
        setState(() => _error = error.toString());
      }
    } on Object catch (error) {
      if (mounted && generation == _searchGeneration) {
        setState(() => _error = error.toString());
      }
    } finally {
      if (mounted && generation == _searchGeneration) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _cancelSearch() async {
    final queryId = _queryId;
    if (queryId == null) return;
    ++_searchGeneration;
    try {
      await _api.cancelRecommendationJob(queryId);
    } on Object {
      // The job may have completed between the tap and the DELETE request.
    }
    if (mounted) {
      setState(() {
        _loading = false;
        _queryStage = 'cancelled';
        _error = 'Search cancelled. You can change the settings and try again.';
      });
    }
  }

  Future<void> _searchStores() async {
    if (!_readManualCoordinates()) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await _api.searchStores(
        location: _location,
        radiusKm: _radiusKm,
        scope: _scope,
        countryCode: _countryController.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _stores = results;
        if (results.isEmpty) {
          _error = 'No mapped stores were found within the selected radius.';
        }
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openUrl(String value) async {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) setState(() => _error = 'Could not open the link.');
    }
  }

  void _saveApiUrl() {
    _api.baseUrl = _apiController.text;
    setState(() => _error = null);
    _loadTargets();
  }

  @override
  Widget build(BuildContext context) {
    final body = switch (_pageIndex) {
      0 => _DiscoveryPage(
          location: _location,
          latitudeController: _latitudeController,
          longitudeController: _longitudeController,
          countryController: _countryController,
          targets: _targets,
          target: _target,
          catalogObject: _catalogObject,
          api: _api,
          scope: _scope,
          radiusKm: _radiusKm,
          horizonDays: _horizonDays,
          recommendations: _recommendations,
          loading: _loading,
          error: _error,
          queryStage: _queryStage,
          queryExpired: _queryExpired,
          onTargetChanged: (value) => setState(() => _target = value),
          onCatalogChanged: (value) => setState(() => _catalogObject = value),
          onScopeChanged: (value) => setState(() => _scope = value),
          onRadiusChanged: (value) => setState(() => _radiusKm = value),
          onHorizonChanged: (value) => setState(() => _horizonDays = value),
          onUseLocation: _useCurrentLocation,
          onSearch: _searchSky,
          onCancelSearch: _cancelSearch,
          onOpenUrl: _openUrl,
        ),
      1 => _StoresPage(
          stores: _stores,
          loading: _loading,
          error: _error,
          radiusKm: _radiusKm,
          onSearch: _searchStores,
          onOpenUrl: _openUrl,
        ),
      _ => _SettingsPage(
          apiController: _apiController,
          currentApiUrl: _api.baseUrl,
          onSave: _saveApiUrl,
        ),
    };

    return StarfieldBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          title: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Thiezer', style: TextStyle(fontWeight: FontWeight.w700)),
              Text(
                'Find the sky worth traveling for',
                style: TextStyle(fontSize: 12, color: Colors.white70),
              ),
            ],
          ),
        ),
        body: SafeArea(child: body),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _pageIndex,
          onDestinationSelected: (index) => setState(() => _pageIndex = index),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.auto_awesome),
              label: 'Sky',
            ),
            NavigationDestination(
              icon: Icon(Icons.camera_alt_outlined),
              label: 'Equipment',
            ),
            NavigationDestination(
              icon: Icon(Icons.settings_outlined),
              label: 'Settings',
            ),
          ],
        ),
      ),
    );
  }
}

class _DiscoveryPage extends StatelessWidget {
  const _DiscoveryPage({
    required this.location,
    required this.latitudeController,
    required this.longitudeController,
    required this.countryController,
    required this.targets,
    required this.target,
    required this.catalogObject,
    required this.api,
    required this.scope,
    required this.radiusKm,
    required this.horizonDays,
    required this.recommendations,
    required this.loading,
    required this.error,
    required this.queryStage,
    required this.queryExpired,
    required this.onTargetChanged,
    required this.onCatalogChanged,
    required this.onScopeChanged,
    required this.onRadiusChanged,
    required this.onHorizonChanged,
    required this.onUseLocation,
    required this.onSearch,
    required this.onCancelSearch,
    required this.onOpenUrl,
  });

  final GeoPoint location;
  final TextEditingController latitudeController;
  final TextEditingController longitudeController;
  final TextEditingController countryController;
  final List<TargetOption> targets;
  final String target;
  final CelestialObject? catalogObject;
  final ThiezerApiClient api;
  final String scope;
  final double radiusKm;
  final int horizonDays;
  final List<RecommendationResult> recommendations;
  final bool loading;
  final String? error;
  final String? queryStage;
  final bool queryExpired;
  final ValueChanged<String> onTargetChanged;
  final ValueChanged<CelestialObject?> onCatalogChanged;
  final ValueChanged<String> onScopeChanged;
  final ValueChanged<double> onRadiusChanged;
  final ValueChanged<int> onHorizonChanged;
  final VoidCallback onUseLocation;
  final VoidCallback onSearch;
  final VoidCallback onCancelSearch;
  final ValueChanged<String> onOpenUrl;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 900;
        final controls = _SearchControls(
          latitudeController: latitudeController,
          longitudeController: longitudeController,
          countryController: countryController,
          targets: targets,
          target: target,
          catalogObject: catalogObject,
          api: api,
          point: location,
          scope: scope,
          radiusKm: radiusKm,
          horizonDays: horizonDays,
          loading: loading,
          error: error,
          queryStage: queryStage,
          queryExpired: queryExpired,
          onTargetChanged: onTargetChanged,
          onCatalogChanged: onCatalogChanged,
          onScopeChanged: onScopeChanged,
          onRadiusChanged: onRadiusChanged,
          onHorizonChanged: onHorizonChanged,
          onUseLocation: onUseLocation,
          onSearch: onSearch,
          onCancelSearch: onCancelSearch,
        );
        final results = _ResultsPane(
          location: location,
          recommendations: recommendations,
          onOpenUrl: onOpenUrl,
        );
        if (wide) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(width: 390, child: controls),
              const VerticalDivider(width: 1),
              Expanded(child: results),
            ],
          );
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            controls,
            const SizedBox(height: 16),
            SizedBox(height: 620, child: results),
          ],
        );
      },
    );
  }
}

class _SearchControls extends StatelessWidget {
  const _SearchControls({
    required this.latitudeController,
    required this.longitudeController,
    required this.countryController,
    required this.targets,
    required this.target,
    required this.catalogObject,
    required this.api,
    required this.point,
    required this.scope,
    required this.radiusKm,
    required this.horizonDays,
    required this.loading,
    required this.error,
    required this.queryStage,
    required this.queryExpired,
    required this.onTargetChanged,
    required this.onCatalogChanged,
    required this.onScopeChanged,
    required this.onRadiusChanged,
    required this.onHorizonChanged,
    required this.onUseLocation,
    required this.onSearch,
    required this.onCancelSearch,
  });

  final TextEditingController latitudeController;
  final TextEditingController longitudeController;
  final TextEditingController countryController;
  final List<TargetOption> targets;
  final String target;
  final CelestialObject? catalogObject;
  final ThiezerApiClient api;
  final GeoPoint point;
  final String scope;
  final double radiusKm;
  final int horizonDays;
  final bool loading;
  final String? error;
  final String? queryStage;
  final bool queryExpired;
  final ValueChanged<String> onTargetChanged;
  final ValueChanged<CelestialObject?> onCatalogChanged;
  final ValueChanged<String> onScopeChanged;
  final ValueChanged<double> onRadiusChanged;
  final ValueChanged<int> onHorizonChanged;
  final VoidCallback onUseLocation;
  final VoidCallback onSearch;
  final VoidCallback onCancelSearch;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      shrinkWrap: true,
      children: [
        Text(
          'What would you like to see?',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: target,
          decoration: const InputDecoration(labelText: 'Celestial target'),
          items: targets
              .map(
                (item) =>
                    DropdownMenuItem(value: item.id, child: Text(item.label)),
              )
              .toList(growable: false),
          onChanged: (value) {
            if (value != null) onTargetChanged(value);
          },
        ),
        const SizedBox(height: 12),
        CelestialSearchField(
          api: api,
          point: point,
          selected: catalogObject,
          onSelected: onCatalogChanged,
        ),
        const SizedBox(height: 16),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(
              value: 'adaptive',
              label: Text('Nearby'),
              icon: Icon(Icons.radar),
            ),
            ButtonSegment(
              value: 'country',
              label: Text('Country'),
              icon: Icon(Icons.flag_outlined),
            ),
            ButtonSegment(
              value: 'global',
              label: Text('Worldwide'),
              icon: Icon(Icons.public),
            ),
          ],
          selected: {scope},
          onSelectionChanged: (value) => onScopeChanged(value.first),
        ),
        if (scope == 'country') ...[
          const SizedBox(height: 12),
          TextField(
            controller: countryController,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(
              labelText: 'Country ISO code, e.g. AM',
            ),
          ),
        ],
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: latitudeController,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                  signed: true,
                ),
                decoration: const InputDecoration(labelText: 'Latitude'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: longitudeController,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                  signed: true,
                ),
                decoration: const InputDecoration(labelText: 'Longitude'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: loading ? null : onUseLocation,
          icon: const Icon(Icons.my_location),
          label: const Text('Use my location'),
        ),
        const SizedBox(height: 14),
        Text('Radius: ${radiusKm.round()} km'),
        Slider(
          value: radiusKm,
          min: 25,
          max: 500,
          divisions: 19,
          label: '${radiusKm.round()} km',
          onChanged: loading ? null : onRadiusChanged,
        ),
        const Text(
          'The radius bounds calculations. In a small country, adaptive search may cross the border; '
          'in a large country it remains local.',
          style: TextStyle(color: Colors.white70),
        ),
        const SizedBox(height: 14),
        Text('Search horizon: $horizonDays ${_dayLabel(horizonDays)}'),
        SegmentedButton<int>(
          segments: const [
            ButtonSegment(value: 1, label: Text('1 day')),
            ButtonSegment(value: 3, label: Text('3 days')),
            ButtonSegment(value: 7, label: Text('7 days')),
            ButtonSegment(value: 14, label: Text('14 days')),
          ],
          selected: {horizonDays},
          onSelectionChanged:
              loading ? null : (value) => onHorizonChanged(value.first),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: loading ? null : onSearch,
          icon: loading
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.travel_explore),
          label: const Text('Find the best sky'),
        ),
        if (loading && queryStage != null) ...[
          const SizedBox(height: 10),
          LinearProgressIndicator(value: _stageProgress(queryStage!)),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(child: Text(_stageLabel(queryStage!))),
              TextButton.icon(
                onPressed: onCancelSearch,
                icon: const Icon(Icons.cancel_outlined),
                label: const Text('Cancel'),
              ),
            ],
          ),
        ],
        if (error != null) ...[
          const SizedBox(height: 12),
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: loading ? null : onSearch,
            icon: Icon(queryExpired ? Icons.refresh : Icons.replay),
            label: Text(queryExpired ? 'Start again' : 'Try again'),
          ),
        ],
        const SizedBox(height: 12),
        const Text(
          'Dynamic locations are unverified: the app does not guarantee legal access, '
          'road condition, parking, or nighttime safety.',
          style: TextStyle(fontSize: 12, color: Colors.white60),
        ),
      ],
    );
  }
}

class _ResultsPane extends StatelessWidget {
  const _ResultsPane({
    required this.location,
    required this.recommendations,
    required this.onOpenUrl,
  });

  final GeoPoint location;
  final List<RecommendationResult> recommendations;
  final ValueChanged<String> onOpenUrl;

  @override
  Widget build(BuildContext context) {
    if (recommendations.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Text(
            'The best locations, time windows, forecasts, and routes will appear here.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 18, color: Colors.white70),
          ),
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          flex: 5,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(18),
            child: FlutterMap(
              options: MapOptions(
                initialCenter: LatLng(location.latitude, location.longitude),
                initialZoom: 6,
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.thiezer.app',
                ),
                MarkerLayer(
                  markers: [
                    Marker(
                      point: LatLng(location.latitude, location.longitude),
                      width: 38,
                      height: 38,
                      child: const Icon(
                        Icons.my_location,
                        color: Colors.lightBlueAccent,
                        size: 32,
                      ),
                    ),
                    ...recommendations.map(
                      (item) => Marker(
                        point: LatLng(
                          item.place.point.latitude,
                          item.place.point.longitude,
                        ),
                        width: 46,
                        height: 46,
                        child: Tooltip(
                          message: item.place.name,
                          child: CircleAvatar(
                            backgroundColor: _scoreColor(item.bestScore),
                            child: Text(
                              '${item.rank}',
                              style: const TextStyle(color: Colors.black),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const RichAttributionWidget(
                  attributions: [
                    TextSourceAttribution('OpenStreetMap contributors'),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          flex: 4,
          child: ListView.separated(
            itemCount: recommendations.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) => _RecommendationCard(
              item: recommendations[index],
              onOpenUrl: onOpenUrl,
            ),
          ),
        ),
      ],
    );
  }
}

class _RecommendationCard extends StatelessWidget {
  const _RecommendationCard({required this.item, required this.onOpenUrl});

  final RecommendationResult item;
  final ValueChanged<String> onOpenUrl;

  @override
  Widget build(BuildContext context) {
    final time = DateFormat('dd MMM, HH:mm').format(item.bestTime);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: _scoreColor(item.bestScore),
                  foregroundColor: Colors.black,
                  child: Text('${(item.bestScore * 100).round()}'),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.place.name,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(
                        '${item.distanceKm.toStringAsFixed(1)} km · $time · ${item.place.kind}',
                        style: const TextStyle(color: Colors.white70),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 12,
              runSpacing: 6,
              children: [
                _Metric(
                  label: 'SkyQuality',
                  value: '${(item.bestScore * 100).round()}%',
                ),
                _Metric(
                  label: 'TravelUtility',
                  value: '${(item.travelUtility * 100).round()}%',
                ),
                _Metric(
                  label: 'Clouds',
                  value: '${(item.conditions.cloud * 100).round()}%',
                ),
                _Metric(
                  label: 'Wind',
                  value: '${item.conditions.windMps.toStringAsFixed(1)} m/s',
                ),
                _Metric(
                  label: 'Target',
                  value: '${item.astronomy.altitudeDeg.toStringAsFixed(0)}°',
                ),
                _Metric(
                  label: 'Darkness',
                  value: '${(item.place.darknessScore * 100).round()}%',
                ),
              ],
            ),
            if (item.warnings.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                item.warnings.map(_warningLabel).join(' · '),
                style: const TextStyle(fontSize: 12, color: Colors.amberAccent),
              ),
            ],
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: item.routes
                  .where((route) => route.provider != 'geo_uri')
                  .map(
                    (route) => OutlinedButton(
                      onPressed: () => onOpenUrl(route.url),
                      child: Text(_routeLabel(route.provider)),
                    ),
                  )
                  .toList(growable: false),
            ),
          ],
        ),
      ),
    );
  }
}

class _StoresPage extends StatelessWidget {
  const _StoresPage({
    required this.stores,
    required this.loading,
    required this.error,
    required this.radiusKm,
    required this.onSearch,
    required this.onOpenUrl,
  });

  final List<StoreResult> stores;
  final bool loading;
  final String? error;
  final double radiusKm;
  final VoidCallback onSearch;
  final ValueChanged<String> onOpenUrl;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Equipment nearby',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 6),
        Text(
          'Cameras, optics, electronics, and outdoor stores within ${radiusKm.round()} km.',
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: loading ? null : onSearch,
          icon: const Icon(Icons.search),
          label: const Text('Find stores'),
        ),
        if (error != null) ...[
          const SizedBox(height: 10),
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ],
        const SizedBox(height: 12),
        ...stores.map(
          (store) => Card(
            child: ListTile(
              title: Text(store.name),
              subtitle: Text(
                [
                  if (store.distanceKm != null)
                    '${store.distanceKm!.toStringAsFixed(1)} km',
                  ...store.categories.take(3),
                  if (store.address != null) store.address!,
                ].join(' · '),
              ),
              trailing: PopupMenuButton<String>(
                onSelected: (value) => onOpenUrl(value),
                itemBuilder: (_) => [
                  PopupMenuItem(
                    value: store.website,
                    child: const Text('Open website'),
                  ),
                  ...store.routes.map(
                    (route) => PopupMenuItem(
                      value: route.url,
                      child: Text(_routeLabel(route.provider)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _SettingsPage extends StatelessWidget {
  const _SettingsPage({
    required this.apiController,
    required this.currentApiUrl,
    required this.onSave,
  });

  final TextEditingController apiController;
  final String currentApiUrl;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Connection', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 12),
        TextField(
          controller: apiController,
          autocorrect: false,
          decoration: const InputDecoration(labelText: 'Thiezer API URL'),
        ),
        const SizedBox(height: 10),
        FilledButton(
          onPressed: onSave,
          child: const Text('Save and test'),
        ),
        const SizedBox(height: 10),
        Text('Current address: $currentApiUrl'),
        const SizedBox(height: 24),
        const Text(
          'For a physical iPhone, enter the Mac LAN address, for example '
          'http://192.168.1.20:8000, and run the backend with --host 0.0.0.0.',
          style: TextStyle(color: Colors.white70),
        ),
        const SizedBox(height: 24),
        const Text(
          'The OpenStreetMap layer in this build is for local development. '
          'Before a public release, use self-hosted PMTiles or a commercial tile provider.',
          style: TextStyle(color: Colors.white60),
        ),
      ],
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Text('$label: $value', style: const TextStyle(fontSize: 12));
  }
}

Color _scoreColor(double score) {
  if (score >= 0.75) return const Color(0xFF7CE3A1);
  if (score >= 0.5) return const Color(0xFFFFD166);
  return const Color(0xFFFF8B8B);
}

String _routeLabel(String provider) => switch (provider) {
      'google_maps' => 'Google Maps',
      'apple_maps' => 'Apple Maps',
      'yandex_maps_web' => 'Yandex Maps',
      _ => provider,
    };

String _warningLabel(String warning) => switch (warning) {
      'unverified_place' => 'location is unverified',
      'darkness_is_proxy' => 'darkness is estimated',
      'low_confidence' => 'low forecast confidence',
      'high_dew_risk' => 'dew risk',
      'strong_wind' => 'strong wind',
      _ => warning.replaceAll('_', ' '),
    };

String _humanWarnings(List<String> warnings) {
  if (warnings.contains('target_not_visible_in_scope')) {
    return 'This target does not rise high enough in the selected area and period.';
  }
  if (warnings.contains('weather_unavailable')) {
    return 'Could not get weather data for the found locations.';
  }
  if (warnings.contains('no_candidate_places')) {
    return 'There are no suitable mapped locations in the radius. Increase the radius.';
  }
  if (warnings.contains('no_observation_window')) {
    return 'There is no good enough window on the selected days. Try another period or target.';
  }
  return warnings.isEmpty ? 'No results found.' : warnings.join(', ');
}

String _dayLabel(int value) => value == 1 ? 'day' : 'days';

double _stageProgress(String stage) {
  const stages = <String>[
    'queued',
    'resolving_target',
    'generating_cells',
    'fetching_elevation',
    'reading_surface_windows',
    'applying_static_filters',
    'checking_access',
    'fetching_weather',
    'calculating_astronomy',
    'ranking',
    'completed',
  ];
  final index = stages.indexOf(stage);
  return index < 0 ? 0 : index / (stages.length - 1);
}

String _stageLabel(String stage) => switch (stage) {
      'queued' => 'Search queued',
      'resolving_target' => 'Resolving celestial target',
      'generating_cells' => 'Generating H3 candidates',
      'fetching_elevation' => 'Fetching elevation',
      'reading_surface_windows' => 'Checking surface',
      'applying_static_filters' => 'Filtering unsuitable locations',
      'fetching_weather' => 'Fetching weather forecast',
      'calculating_astronomy' => 'Calculating visibility',
      'checking_access' => 'Checking local access',
      'ranking' => 'Ranking locations',
      'completed' => 'Search completed',
      'cancelled' => 'Search cancelled',
      'expired' => 'Result expired',
      'failed' => 'Search failed',
      _ => stage.replaceAll('_', ' '),
    };
