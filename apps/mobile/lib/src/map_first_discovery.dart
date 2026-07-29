import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'celestial_search.dart';
import 'location_service.dart';
import 'models.dart';

const _defaultApiUrl = String.fromEnvironment(
  'THIEZER_API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

class MapFirstDiscoveryScreen extends StatefulWidget {
  const MapFirstDiscoveryScreen({super.key});

  @override
  State<MapFirstDiscoveryScreen> createState() =>
      _MapFirstDiscoveryScreenState();
}

class _MapFirstDiscoveryScreenState extends State<MapFirstDiscoveryScreen> {
  static const _fallbackTargets = <TargetOption>[
    TargetOption(id: 'moon', label: 'Moon'),
    TargetOption(id: 'milky_way', label: 'Milky Way'),
    TargetOption(id: 'jupiter', label: 'Jupiter'),
    TargetOption(id: 'saturn', label: 'Saturn'),
    TargetOption(id: 'mars', label: 'Mars'),
    TargetOption(id: 'best_night_sky', label: 'Best night sky'),
  ];

  late final ThiezerApiClient _api;
  final _locationService = LocationService();
  final _apiController = TextEditingController(text: _defaultApiUrl);
  final _countryController = TextEditingController(text: 'AM');

  GeoPoint _location = const GeoPoint(40.1772, 44.5035);
  List<TargetOption> _targets = _fallbackTargets;
  List<RecommendationResult> _results = const [];
  List<AstronomicalPlanCandidate> _planResults = const [];
  CelestialObject? _catalogObject;
  String _target = 'moon';
  String _scope = 'country';
  double _radiusKm = 150;
  int _horizonDays = 7;
  bool _astronomicalPlan = false;
  int _selectedResult = 0;
  int _selectedPlanResult = 0;
  RoadRoute? _roadRoute;
  bool _routing = false;
  int _mapRevision = 0;
  String? _queryId;
  String? _stage;
  String? _error;
  bool _loading = false;
  bool _locating = false;
  bool _didAutoExpandHorizon = false;

  @override
  void initState() {
    super.initState();
    _api = ThiezerApiClient(baseUrl: _defaultApiUrl);
    _loadTargets();
  }

  @override
  void dispose() {
    _apiController.dispose();
    _countryController.dispose();
    super.dispose();
  }

  Future<void> _loadTargets() async {
    try {
      final targets = await _api.fetchTargets();
      if (mounted && targets.isNotEmpty) setState(() => _targets = targets);
    } on Object {
      // Presets remain usable while the local backend is starting.
    }
  }

  Future<void> _useCurrentLocation() async {
    setState(() {
      _locating = true;
      _error = null;
    });
    try {
      final point = await _locationService.currentLocation();
      if (!mounted) return;
      setState(() {
        _location = point;
        _mapRevision++;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _startSearch({bool resetAutoExpansion = true}) async {
    if (_loading) return;
    if (resetAutoExpansion) _didAutoExpandHorizon = false;
    setState(() {
      _loading = true;
      _error = null;
      _stage = 'queued';
      _queryId = null;
      _results = const [];
      _planResults = const [];
      _selectedResult = 0;
      _selectedPlanResult = 0;
      _roadRoute = null;
    });
    try {
      if (_astronomicalPlan && _target != 'best_night_sky') {
        final plan = await _api.planAstronomy(
          location: _location,
          target: _target,
          radiusKm: _radiusKm,
          scope: _scope,
          countryCode: _countryController.text.trim(),
          horizonDays: 365,
        );
        if (!mounted) return;
        setState(() {
          _planResults = plan.candidates;
          _loading = false;
          _stage = 'completed';
          _error = plan.candidates.isEmpty
              ? 'There is no astronomical window for this target within the selected horizon.'
              : null;
          _mapRevision++;
        });
        return;
      }
      final initial = await _api.startRecommendationJob(
        location: _location,
        target: _target,
        catalogObject: _catalogObject,
        radiusKm: _radiusKm,
        scope: _scope,
        countryCode: _countryController.text.trim(),
        horizon: Duration(days: _horizonDays),
      );
      _queryId = initial.queryId;
      await _pollJob(initial.queryId);
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _error = 'Could not complete the calculation: $error';
          _loading = false;
        });
      }
    }
  }

  Future<void> _pollJob(String queryId) async {
    for (var attempt = 0; attempt < 180; attempt++) {
      if (!mounted || _queryId != queryId) return;
      final status = await _api.fetchRecommendationJob(queryId);
      if (!mounted || _queryId != queryId) return;
      setState(() => _stage = status.stage);
      if (status.stage == 'completed') {
        final response = status.result;
        final results = response?.results ?? const <RecommendationResult>[];
        if (results.isEmpty && _horizonDays < 14 && !_didAutoExpandHorizon) {
          setState(() {
            _didAutoExpandHorizon = true;
            _horizonDays = 14;
            _loading = false;
            _stage = 'expanding_horizon';
          });
          await _startSearch(resetAutoExpansion: false);
          return;
        }
        setState(() {
          _results = results;
          _selectedResult = 0;
          _loading = false;
          _error = results.isEmpty
              ? _warningsMessage(response?.warnings ?? const <String>[])
              : null;
          _mapRevision++;
        });
        return;
      }
      if (status.stage == 'failed' ||
          status.stage == 'cancelled' ||
          status.stage == 'expired') {
        setState(() {
          _loading = false;
          _error = status.error ?? _terminalMessage(status.stage);
        });
        return;
      }
      await Future<void>.delayed(const Duration(milliseconds: 700));
    }
    if (mounted) {
      setState(() {
        _loading = false;
        _error = 'The calculation took too long. Try a smaller radius.';
      });
    }
  }

  Future<void> _cancelSearch() async {
    final queryId = _queryId;
    _queryId = null;
    if (queryId != null) {
      try {
        await _api.cancelRecommendationJob(queryId);
      } on Object {
        // Local state is cancelled even if the backend request has already completed.
      }
    }
    if (mounted) {
      setState(() {
        _loading = false;
        _stage = 'cancelled';
      });
    }
  }

  RecommendationResult? get _selected {
    if (_results.isEmpty) return null;
    return _results[_selectedResult.clamp(0, _results.length - 1)];
  }

  AstronomicalPlanCandidate? get _selectedPlan {
    if (_planResults.isEmpty) return null;
    return _planResults[_selectedPlanResult.clamp(0, _planResults.length - 1)];
  }

  GeoPoint? get _selectedDestination =>
      _selectedPlan?.place.point ?? _selected?.place.point;

  LatLng get _mapCenter {
    final destination = _selectedDestination;
    if (destination == null) {
      return LatLng(_location.latitude, _location.longitude);
    }
    return LatLng(
      (destination.latitude + _location.latitude) / 2,
      (destination.longitude + _location.longitude) / 2,
    );
  }

  Future<void> _openUrl(String value) async {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) {
        setState(() => _error = 'Could not open the navigation app.');
      }
    }
  }

  Future<void> _openPreferredRoute(RecommendationResult result) async {
    final routes = result.routes.where((route) => route.provider != 'geo_uri');
    final preferred = routes.cast<RouteHandoff?>().firstWhere(
          (route) => route?.provider == 'apple_maps',
          orElse: () => routes.isEmpty ? null : routes.first,
        );
    if (preferred != null) await _openUrl(preferred.url);
  }

  Future<void> _buildRoadRoute() async {
    final destination = _selectedDestination;
    if (destination == null || _routing) return;
    setState(() {
      _routing = true;
      _error = null;
    });
    try {
      final route = await _api.drivingRoute(
        origin: _location,
        destination: destination,
      );
      if (!mounted) return;
      setState(() {
        _roadRoute = route;
        _routing = false;
        _mapRevision++;
      });
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _routing = false;
          _error = 'Could not build a road route: $error';
        });
      }
    }
  }

  void _selectPreset(String target) {
    setState(() {
      _target = target;
      _catalogObject = null;
      if (target == 'best_night_sky') _astronomicalPlan = false;
    });
    Navigator.of(context).maybePop();
  }

  Future<void> _showTargetPicker() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF10192B),
      builder: (context) => SafeArea(
        child: Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 18,
            bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
          ),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('What would you like to observe?',
                    style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _targets
                      .where((item) => const {
                            'moon',
                            'milky_way',
                            'jupiter',
                            'saturn',
                            'mars',
                            'best_night_sky',
                          }.contains(item.id))
                      .map(
                        (item) => ChoiceChip(
                          selected:
                              _catalogObject == null && _target == item.id,
                          label: Text(item.label),
                          onSelected: (_) => _selectPreset(item.id),
                        ),
                      )
                      .toList(growable: false),
                ),
                const SizedBox(height: 16),
                CelestialSearchField(
                  api: _api,
                  point: _location,
                  selected: _catalogObject,
                  onSelected: (object) {
                    setState(() {
                      _catalogObject = object;
                      if (object != null) _astronomicalPlan = false;
                    });
                    if (object != null) Navigator.of(context).pop();
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _showFilters() async {
    var radius = _radiusKm;
    var scope = _scope;
    var days = _horizonDays;
    var astronomicalPlan = _astronomicalPlan && _target != 'best_night_sky';
    final canUseAstronomicalPlan =
        _target != 'best_night_sky' && _catalogObject == null;
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: const Color(0xFF10192B),
      builder: (context) => StatefulBuilder(
        builder: (context, setSheetState) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Search settings',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 14),
                Text('Radius: ${radius.round()} km'),
                Slider(
                  value: radius,
                  min: 25,
                  max: 500,
                  divisions: 19,
                  onChanged: (value) => setSheetState(() => radius = value),
                ),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(
                        value: 'country', label: Text('In my country')),
                    ButtonSegment(
                        value: 'adaptive', label: Text('Within radius')),
                    ButtonSegment(value: 'global', label: Text('Cross-border')),
                  ],
                  selected: {scope},
                  onSelectionChanged: (value) =>
                      setSheetState(() => scope = value.first),
                ),
                if (scope == 'global') ...[
                  const SizedBox(height: 8),
                  const Text(
                    'Cross-border search still uses the selected radius; it does not scan the entire planet.',
                    style: TextStyle(fontSize: 12, color: Colors.white70),
                  ),
                ],
                if (scope == 'country') ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _countryController,
                    textCapitalization: TextCapitalization.characters,
                    decoration:
                        const InputDecoration(labelText: 'Country ISO code'),
                  ),
                ],
                const SizedBox(height: 14),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 1, label: Text('1 day')),
                    ButtonSegment(value: 3, label: Text('3 days')),
                    ButtonSegment(value: 7, label: Text('7 days')),
                    ButtonSegment(value: 14, label: Text('14 days')),
                  ],
                  selected: {days},
                  onSelectionChanged: (value) =>
                      setSheetState(() => days = value.first),
                ),
                const SizedBox(height: 14),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('One-year astronomical plan'),
                  subtitle: Text(canUseAstronomicalPlan
                      ? 'For a celestial target only. It uses altitude, azimuth, Sun, and Moon — not weather.'
                      : 'Best night sky is a near-term destination search, so it always uses the forecast window.'),
                  value: astronomicalPlan,
                  onChanged: canUseAstronomicalPlan
                      ? (value) => setSheetState(() => astronomicalPlan = value)
                      : null,
                ),
                const SizedBox(height: 18),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: () {
                      setState(() {
                        _radiusKm = radius;
                        _scope = scope;
                        _horizonDays = days;
                        _astronomicalPlan =
                            canUseAstronomicalPlan && astronomicalPlan;
                      });
                      Navigator.pop(context);
                    },
                    child: const Text('Apply'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _showSettings() async {
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Backend API'),
        content: TextField(
          controller: _apiController,
          decoration: const InputDecoration(labelText: 'URL'),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel')),
          FilledButton(
            onPressed: () {
              _api.baseUrl = _apiController.text;
              Navigator.pop(context);
              _loadTargets();
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  Future<void> _showStores() async {
    try {
      final stores = await _api.searchStores(
        location: _location,
        radiusKm: _radiusKm,
        scope: _scope,
        countryCode: _countryController.text.trim(),
      );
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        backgroundColor: const Color(0xFF10192B),
        builder: (context) => SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(context).height * .72,
            child: ListView.builder(
              padding: const EdgeInsets.all(18),
              itemCount: stores.length + 1,
              itemBuilder: (context, index) {
                if (index == 0) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text('Equipment nearby',
                        style: Theme.of(context).textTheme.titleLarge),
                  );
                }
                final store = stores[index - 1];
                return Card(
                  child: ListTile(
                    title: Text(store.name),
                    subtitle: Text([
                      if (store.distanceKm != null)
                        '${store.distanceKm!.toStringAsFixed(1)} km',
                      store.categories.take(3).join(', '),
                    ].join(' · ')),
                    trailing: const Icon(Icons.open_in_new),
                    onTap: () => _openUrl(
                      store.routes.isNotEmpty
                          ? store.routes.first.url
                          : store.website,
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      );
    } on Object catch (error) {
      if (mounted) setState(() => _error = 'Could not load stores: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    final selectedPlan = _selectedPlan;
    return Scaffold(
      backgroundColor: const Color(0xFF071020),
      body: Stack(
        children: [
          Positioned.fill(
            child: FlutterMap(
              key: ValueKey(
                  'map-$_mapRevision-${selected?.place.id ?? 'origin'}'),
              options: MapOptions(
                initialCenter: _mapCenter,
                initialZoom: selected == null ? 8 : 7,
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.thiezer.app',
                ),
                MarkerLayer(markers: _markers()),
                if (_roadRoute != null)
                  PolylineLayer(
                    polylines: [
                      Polyline(
                        points: _roadRoute!.geometry
                            .map((point) =>
                                LatLng(point.latitude, point.longitude))
                            .toList(growable: false),
                        color: const Color(0xFFFFD166),
                        strokeWidth: 4,
                      ),
                    ],
                  ),
                const RichAttributionWidget(
                  attributions: [
                    TextSourceAttribution('OpenStreetMap contributors')
                  ],
                ),
              ],
            ),
          ),
          Positioned.fill(
            child: IgnorePointer(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.center,
                    colors: [
                      Colors.black.withValues(alpha: .48),
                      Colors.transparent
                    ],
                  ),
                ),
              ),
            ),
          ),
          SafeArea(child: _topBar()),
          Positioned(
            right: 16,
            top: MediaQuery.paddingOf(context).top + 88,
            child: Column(
              children: [
                _MapAction(
                  tooltip: 'My location',
                  icon: _locating ? Icons.hourglass_top : Icons.my_location,
                  onPressed: _locating ? null : _useCurrentLocation,
                ),
                const SizedBox(height: 8),
                _MapAction(
                    tooltip: 'Filters',
                    icon: Icons.tune,
                    onPressed: _showFilters),
                const SizedBox(height: 8),
                _MapAction(
                    tooltip: 'Stores',
                    icon: Icons.storefront,
                    onPressed: _showStores),
                const SizedBox(height: 8),
                _MapAction(
                    tooltip: 'Settings',
                    icon: Icons.settings,
                    onPressed: _showSettings),
              ],
            ),
          ),
          if (_loading)
            Positioned(left: 16, right: 16, top: 112, child: _progressCard()),
          if (!_loading && _error != null)
            Positioned(left: 16, right: 16, top: 112, child: _errorCard()),
          if (selectedPlan != null)
            Positioned(
                left: 16, right: 16, bottom: 18, child: _planCard(selectedPlan))
          else if (selected != null)
            Positioned(
                left: 16, right: 16, bottom: 18, child: _resultCard(selected))
          else if (!_loading)
            Positioned(left: 16, right: 16, bottom: 18, child: _welcomeCard()),
        ],
      ),
    );
  }

  List<Marker> _markers() => [
        Marker(
          point: LatLng(_location.latitude, _location.longitude),
          width: 48,
          height: 48,
          child:
              const Icon(Icons.my_location, size: 34, color: Color(0xFF64D8FF)),
        ),
        ..._results.asMap().entries.map((entry) {
          final selected = entry.key == _selectedResult;
          return Marker(
            point: LatLng(entry.value.place.point.latitude,
                entry.value.place.point.longitude),
            width: selected ? 58 : 46,
            height: selected ? 58 : 46,
            child: GestureDetector(
              onTap: () => setState(() {
                _selectedResult = entry.key;
                _roadRoute = null;
                _mapRevision++;
              }),
              child: CircleAvatar(
                backgroundColor: selected
                    ? const Color(0xFF91F2B6)
                    : const Color(0xFF8AB4FF),
                foregroundColor: Colors.black,
                child: Text('${entry.key + 1}',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            ),
          );
        }),
        ..._planResults.asMap().entries.map((entry) {
          final selected = entry.key == _selectedPlanResult;
          return Marker(
            point: LatLng(entry.value.place.point.latitude,
                entry.value.place.point.longitude),
            width: selected ? 60 : 52,
            height: selected ? 60 : 52,
            child: GestureDetector(
              onTap: () => setState(() {
                _selectedPlanResult = entry.key;
                _roadRoute = null;
                _mapRevision++;
              }),
              child: CircleAvatar(
                backgroundColor: selected
                    ? const Color(0xFFD7C8FF)
                    : const Color(0xFFB79CFF),
                foregroundColor: Colors.black,
                child: Text('${entry.key + 1}',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            ),
          );
        }),
      ];

  Widget _topBar() => Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Material(
              elevation: 12,
              color: const Color(0xEE111B2E),
              borderRadius: BorderRadius.circular(20),
              child: InkWell(
                borderRadius: BorderRadius.circular(20),
                onTap: _showTargetPicker,
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
                  child: Row(
                    children: [
                      const Icon(Icons.search, color: Color(0xFF9FC1FF)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              _catalogObject?.name ?? _targetLabel(_target),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  fontWeight: FontWeight.w700, fontSize: 17),
                            ),
                            Text(
                              '${_radiusKm.round()} km · ${_scopeLabel(_scope)} · ${_astronomicalPlan ? 'one-year plan' : '$_horizonDays days'}',
                              style: const TextStyle(
                                  fontSize: 12, color: Colors.white70),
                            ),
                          ],
                        ),
                      ),
                      FilledButton.icon(
                        onPressed: _loading ? null : _startSearch,
                        icon: const Icon(Icons.travel_explore),
                        label: const Text('Search'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      );

  Widget _progressCard() => Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: Card(
            color: const Color(0xF0111B2E),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  const SizedBox.square(
                    dimension: 24,
                    child: CircularProgressIndicator(strokeWidth: 2.5),
                  ),
                  const SizedBox(width: 14),
                  Expanded(child: Text(_stageLabel(_stage ?? 'queued'))),
                  TextButton(
                      onPressed: _cancelSearch, child: const Text('Cancel')),
                ],
              ),
            ),
          ),
        ),
      );

  Widget _errorCard() => Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: Card(
            color: const Color(0xF02A1820),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  const Icon(Icons.info_outline, color: Colors.orangeAccent),
                  const SizedBox(width: 12),
                  Expanded(child: Text(_error!)),
                  TextButton(
                      onPressed: _startSearch, child: const Text('Try again')),
                ],
              ),
            ),
          ),
        ),
      );

  Widget _welcomeCard() => Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: Card(
            color: const Color(0xE8111B2E),
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Row(
                children: [
                  const Icon(Icons.nightlight_round,
                      size: 32, color: Color(0xFFB3C9FF)),
                  const SizedBox(width: 14),
                  const Expanded(
                    child: Text(
                      'Choose a target and tap Search. The map stays available during the calculation.',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );

  Widget _resultCard(RecommendationResult result) {
    final time = DateFormat('dd MMM, HH:mm').format(result.bestTime);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 880),
        child: Card(
          color: const Color(0xF0111B2E),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      radius: 25,
                      backgroundColor: const Color(0xFF91F2B6),
                      foregroundColor: Colors.black,
                      child: Text('${(result.bestScore * 100).round()}'),
                    ),
                    const SizedBox(width: 13),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(result.place.name,
                              style: Theme.of(context).textTheme.titleMedium),
                          Text(
                            '${result.distanceKm.toStringAsFixed(1)} km · best $time',
                            style: const TextStyle(color: Colors.white70),
                          ),
                        ],
                      ),
                    ),
                    FilledButton.icon(
                      onPressed: () => _openPreferredRoute(result),
                      icon: const Icon(Icons.directions_car),
                      label: const Text('Navigate'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 14,
                  runSpacing: 8,
                  children: [
                    _Metric('Quality', '${(result.bestScore * 100).round()}%'),
                    _Metric('Clouds',
                        '${(result.conditions.cloud * 100).round()}%'),
                    if (_target == 'best_night_sky') ...[
                      _Metric('Darkness estimate',
                          '${(result.place.darknessScore * 100).round()}%'),
                      _Metric('Open horizon',
                          '${(result.place.horizonOpennessScore * 100).round()}%'),
                    ] else
                      _Metric('Target altitude',
                          '${result.astronomy.altitudeDeg.toStringAsFixed(0)}°'),
                    _Metric('Wind',
                        '${result.conditions.windMps.toStringAsFixed(1)} m/s'),
                  ],
                ),
                if (_target == 'best_night_sky')
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Text(
                      'Best night sky ranks darkness, terrain openness, access estimate, and the near-term forecast. It has no celestial target altitude or azimuth.',
                      style: TextStyle(fontSize: 12, color: Colors.white70),
                    ),
                  ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _routing ? null : _buildRoadRoute,
                  icon: _routing
                      ? const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.alt_route),
                  label: Text(_roadRoute == null
                      ? 'Build road route'
                      : 'Refresh road route'),
                ),
                if (_roadRoute != null) _RoadRouteSummary(route: _roadRoute!),
                if (result.warnings.isNotEmpty) ...[
                  const SizedBox(height: 9),
                  Text(
                    result.warnings.map(_warningLabel).join(' · '),
                    style: const TextStyle(
                        fontSize: 12, color: Colors.amberAccent),
                  ),
                ],
                if (_results.length > 1) ...[
                  const SizedBox(height: 10),
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: _results.asMap().entries.map((entry) {
                        return Padding(
                          padding: const EdgeInsets.only(right: 7),
                          child: ChoiceChip(
                            selected: entry.key == _selectedResult,
                            label: Text(
                              entry.key == 0
                                  ? 'Nearest good option'
                                  : '${entry.value.distanceKm.toStringAsFixed(0)} km · ${(entry.value.bestScore * 100).round()}%',
                            ),
                            onSelected: (_) => setState(() {
                              _selectedResult = entry.key;
                              _roadRoute = null;
                              _mapRevision++;
                            }),
                          ),
                        );
                      }).toList(growable: false),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _planCard(AstronomicalPlanCandidate result) {
    final time =
        DateFormat('EEEE, dd MMMM y, HH:mm', 'en').format(result.bestTime);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 880),
        child: Card(
          color: const Color(0xF0111B2E),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Astronomical plan — no weather forecast',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text(result.place.name),
                Text('${result.distanceKm.toStringAsFixed(1)} km · $time',
                    style: const TextStyle(color: Colors.white70)),
                const SizedBox(height: 12),
                Wrap(spacing: 14, children: [
                  _Metric('Target altitude',
                      '${result.altitudeDeg.toStringAsFixed(0)}°'),
                  _Metric(
                      'Azimuth', '${result.azimuthDeg.toStringAsFixed(0)}°'),
                  _Metric('Geometry', '${(result.score * 100).round()}%'),
                ]),
                const SizedBox(height: 8),
                const Text(
                  'Altitude is the target height above the horizon. Azimuth is its direction clockwise from north. Geometry combines target altitude, darkness, and Moon interference.',
                  style: TextStyle(fontSize: 12, color: Colors.white70),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _routing ? null : _buildRoadRoute,
                  icon: _routing
                      ? const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.alt_route),
                  label: Text(_roadRoute == null
                      ? 'Build road route'
                      : 'Refresh road route'),
                ),
                if (_roadRoute != null) _RoadRouteSummary(route: _roadRoute!),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RoadRouteSummary extends StatelessWidget {
  const _RoadRouteSummary({required this.route});

  final RoadRoute route;

  @override
  Widget build(BuildContext context) {
    final duration = Duration(seconds: route.durationS.round());
    final hours = duration.inHours;
    final minutes = duration.inMinutes.remainder(60);
    final time = hours == 0 ? '$minutes min' : '$hours h $minutes min';
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Text(
        'Road route: ${(route.distanceM / 1000).toStringAsFixed(1)} km · $time\n${route.attribution}',
        style: const TextStyle(fontSize: 12, color: Colors.white70),
      ),
    );
  }
}

class _MapAction extends StatelessWidget {
  const _MapAction({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => Material(
        color: const Color(0xE8111B2E),
        elevation: 8,
        shape: const CircleBorder(),
        child: IconButton(
            tooltip: tooltip, icon: Icon(icon), onPressed: onPressed),
      );
}

class _Metric extends StatelessWidget {
  const _Metric(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label,
              style: const TextStyle(fontSize: 11, color: Colors.white60)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      );
}

String _targetLabel(String value) => switch (value) {
      'moon' => 'Moon',
      'milky_way' => 'Milky Way',
      'jupiter' => 'Jupiter',
      'saturn' => 'Saturn',
      'mars' => 'Mars',
      'best_night_sky' => 'Best night sky',
      _ => value,
    };

String _scopeLabel(String value) => switch (value) {
      'adaptive' => 'within the selected radius',
      'country' => 'in my country only',
      'global' => 'cross-border',
      _ => value,
    };

String _stageLabel(String value) => switch (value) {
      'queued' => 'Preparing the request…',
      'resolving_target' => 'Resolving the celestial target…',
      'generating_cells' => 'Finding nearby surfaces…',
      'fetching_elevation' => 'Checking terrain…',
      'reading_surface_windows' => 'Evaluating the surface…',
      'applying_static_filters' => 'Filtering unsuitable locations…',
      'fetching_weather' => 'Fetching the weather forecast…',
      'calculating_astronomy' => 'Calculating visibility…',
      'checking_access' => 'Checking access…',
      'ranking' => 'Selecting the nearest good option…',
      'expanding_horizon' =>
        'No window in the next few days — checking two weeks…',
      _ => 'Calculating…',
    };

String _terminalMessage(String value) => switch (value) {
      'cancelled' => 'Calculation cancelled.',
      'expired' => 'The result expired. Run the search again.',
      _ => 'Calculation failed.',
    };

String _warningsMessage(List<String> warnings) {
  if (warnings.contains('target_not_visible_in_scope')) {
    return 'The target does not rise high enough in the selected area. Change the region or target.';
  }
  if (warnings.contains('weather_unavailable')) {
    return 'The forecast is temporarily unavailable. Try again in a few minutes.';
  }
  if (warnings.contains('no_candidate_places')) {
    return 'No suitable surface was found within this radius. Increase the radius.';
  }
  if (warnings.contains('no_observation_window')) {
    return 'There is no weather-confirmed window in the next two weeks: the horizon, Sun, Moon, or clouds interfere. Use the astronomical plan for a later date without weather forecasts.';
  }
  return warnings.isEmpty ? 'No suitable result found.' : warnings.join(' · ');
}

String _warningLabel(String value) => switch (value) {
      'unverified_place' => 'location is unverified',
      'darkness_is_proxy' => 'darkness is estimated',
      'low_confidence' => 'preliminary forecast',
      'high_dew_risk' => 'dew is possible',
      'strong_wind' => 'strong wind',
      _ => value,
    };
