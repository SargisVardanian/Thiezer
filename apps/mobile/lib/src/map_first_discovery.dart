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
  State<MapFirstDiscoveryScreen> createState() => _MapFirstDiscoveryScreenState();
}

class _MapFirstDiscoveryScreenState extends State<MapFirstDiscoveryScreen> {
  static const _fallbackTargets = <TargetOption>[
    TargetOption(id: 'moon', label: 'Луна'),
    TargetOption(id: 'milky_way', label: 'Млечный Путь'),
    TargetOption(id: 'jupiter', label: 'Юпитер'),
    TargetOption(id: 'saturn', label: 'Сатурн'),
    TargetOption(id: 'mars', label: 'Марс'),
    TargetOption(id: 'best_night_sky', label: 'Лучшее небо'),
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
    });
    try {
      if (_astronomicalPlan) {
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
              ? 'На выбранном горизонте нет астрономического окна для этой цели.'
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
          _error = 'Не удалось выполнить расчёт: $error';
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
        _error = 'Расчёт занял слишком много времени. Попробуйте меньший радиус.';
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

  LatLng get _mapCenter {
    final selected = _selected;
    if (selected == null) return LatLng(_location.latitude, _location.longitude);
    return LatLng(
      (selected.place.point.latitude + _location.latitude) / 2,
      (selected.place.point.longitude + _location.longitude) / 2,
    );
  }

  Future<void> _openUrl(String value) async {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) setState(() => _error = 'Не удалось открыть навигатор.');
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

  void _selectPreset(String target) {
    setState(() {
      _target = target;
      _catalogObject = null;
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
                Text('Что наблюдаем?', style: Theme.of(context).textTheme.headlineSmall),
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
                          selected: _catalogObject == null && _target == item.id,
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
                    setState(() => _catalogObject = object);
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
    var astronomicalPlan = _astronomicalPlan;
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
                Text('Параметры поиска', style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 14),
                Text('Радиус: ${radius.round()} км'),
                Slider(
                  value: radius,
                  min: 25,
                  max: 500,
                  divisions: 19,
                  onChanged: (value) => setSheetState(() => radius = value),
                ),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'country', label: Text('В моей стране')),
                    ButtonSegment(value: 'adaptive', label: Text('В радиусе')),
                    ButtonSegment(value: 'global', label: Text('По всему миру')),
                  ],
                  selected: {scope},
                  onSelectionChanged: (value) => setSheetState(() => scope = value.first),
                ),
                if (scope == 'country') ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _countryController,
                    textCapitalization: TextCapitalization.characters,
                    decoration: const InputDecoration(labelText: 'ISO-код страны'),
                  ),
                ],
                const SizedBox(height: 14),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 1, label: Text('1 день')),
                    ButtonSegment(value: 3, label: Text('3 дня')),
                    ButtonSegment(value: 7, label: Text('7 дней')),
                    ButtonSegment(value: 14, label: Text('14 дней')),
                  ],
                  selected: {days},
                  onSelectionChanged: (value) => setSheetState(() => days = value.first),
                ),
                const SizedBox(height: 14),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Астрономический план на год'),
                  subtitle: const Text('Без прогноза погоды: высота, азимут, Солнце и Луна.'),
                  value: astronomicalPlan,
                  onChanged: (value) => setSheetState(() => astronomicalPlan = value),
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
                        _astronomicalPlan = astronomicalPlan;
                      });
                      Navigator.pop(context);
                    },
                    child: const Text('Применить'),
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
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
          FilledButton(
            onPressed: () {
              _api.baseUrl = _apiController.text;
              Navigator.pop(context);
              _loadTargets();
            },
            child: const Text('Сохранить'),
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
                    child: Text('Техника поблизости', style: Theme.of(context).textTheme.titleLarge),
                  );
                }
                final store = stores[index - 1];
                return Card(
                  child: ListTile(
                    title: Text(store.name),
                    subtitle: Text([
                      if (store.distanceKm != null) '${store.distanceKm!.toStringAsFixed(1)} км',
                      store.categories.take(3).join(', '),
                    ].join(' · ')),
                    trailing: const Icon(Icons.open_in_new),
                    onTap: () => _openUrl(
                      store.routes.isNotEmpty ? store.routes.first.url : store.website,
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      );
    } on Object catch (error) {
      if (mounted) setState(() => _error = 'Не удалось загрузить магазины: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    return Scaffold(
      backgroundColor: const Color(0xFF071020),
      body: Stack(
        children: [
          Positioned.fill(
            child: FlutterMap(
              key: ValueKey('map-$_mapRevision-${selected?.place.id ?? 'origin'}'),
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
                const RichAttributionWidget(
                  attributions: [TextSourceAttribution('OpenStreetMap contributors')],
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
                    colors: [Colors.black.withValues(alpha: .48), Colors.transparent],
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
                  tooltip: 'Моя геолокация',
                  icon: _locating ? Icons.hourglass_top : Icons.my_location,
                  onPressed: _locating ? null : _useCurrentLocation,
                ),
                const SizedBox(height: 8),
                _MapAction(tooltip: 'Фильтры', icon: Icons.tune, onPressed: _showFilters),
                const SizedBox(height: 8),
                _MapAction(tooltip: 'Магазины', icon: Icons.storefront, onPressed: _showStores),
                const SizedBox(height: 8),
                _MapAction(tooltip: 'Настройки', icon: Icons.settings, onPressed: _showSettings),
              ],
            ),
          ),
          if (_loading) Positioned(left: 16, right: 16, top: 112, child: _progressCard()),
          if (!_loading && _error != null)
            Positioned(left: 16, right: 16, top: 112, child: _errorCard()),
          if (_planResults.isNotEmpty)
            Positioned(left: 16, right: 16, bottom: 18, child: _planCard(_planResults.first))
          else if (selected != null)
            Positioned(left: 16, right: 16, bottom: 18, child: _resultCard(selected))
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
          child: const Icon(Icons.my_location, size: 34, color: Color(0xFF64D8FF)),
        ),
        ..._results.asMap().entries.map((entry) {
          final selected = entry.key == _selectedResult;
          return Marker(
            point: LatLng(entry.value.place.point.latitude, entry.value.place.point.longitude),
            width: selected ? 58 : 46,
            height: selected ? 58 : 46,
            child: GestureDetector(
              onTap: () => setState(() {
                _selectedResult = entry.key;
                _mapRevision++;
              }),
              child: CircleAvatar(
                backgroundColor: selected ? const Color(0xFF91F2B6) : const Color(0xFF8AB4FF),
                foregroundColor: Colors.black,
                child: Text('${entry.key + 1}', style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            ),
          );
        }),
        ..._planResults.asMap().entries.map((entry) => Marker(
              point: LatLng(entry.value.place.point.latitude, entry.value.place.point.longitude),
              width: 52,
              height: 52,
              child: CircleAvatar(
                backgroundColor: const Color(0xFFB79CFF),
                foregroundColor: Colors.black,
                child: Text('${entry.key + 1}', style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            )),
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
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
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
                              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 17),
                            ),
                            Text(
                              '${_radiusKm.round()} км · ${_scopeLabel(_scope)} · ${_astronomicalPlan ? 'астроплан на год' : '$_horizonDays дн.'}',
                              style: const TextStyle(fontSize: 12, color: Colors.white70),
                            ),
                          ],
                        ),
                      ),
                      FilledButton.icon(
                        onPressed: _loading ? null : _startSearch,
                        icon: const Icon(Icons.travel_explore),
                        label: const Text('Найти'),
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
                  TextButton(onPressed: _cancelSearch, child: const Text('Отменить')),
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
                  TextButton(onPressed: _startSearch, child: const Text('Повторить')),
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
                  const Icon(Icons.nightlight_round, size: 32, color: Color(0xFFB3C9FF)),
                  const SizedBox(width: 14),
                  const Expanded(
                    child: Text(
                      'Выберите объект и нажмите «Найти». Карта останется доступной во время расчёта.',
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
                          Text(result.place.name, style: Theme.of(context).textTheme.titleMedium),
                          Text(
                            '${result.distanceKm.toStringAsFixed(1)} км · лучше $time',
                            style: const TextStyle(color: Colors.white70),
                          ),
                        ],
                      ),
                    ),
                    FilledButton.icon(
                      onPressed: () => _openPreferredRoute(result),
                      icon: const Icon(Icons.directions_car),
                      label: const Text('Поехать'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 14,
                  runSpacing: 8,
                  children: [
                    _Metric('Качество', '${(result.bestScore * 100).round()}%'),
                    _Metric('Облака', '${(result.conditions.cloud * 100).round()}%'),
                    _Metric('Высота цели', '${result.astronomy.altitudeDeg.toStringAsFixed(0)}°'),
                    _Metric('Ветер', '${result.conditions.windMps.toStringAsFixed(1)} м/с'),
                  ],
                ),
                if (result.warnings.isNotEmpty) ...[
                  const SizedBox(height: 9),
                  Text(
                    result.warnings.map(_warningLabel).join(' · '),
                    style: const TextStyle(fontSize: 12, color: Colors.amberAccent),
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
                                  ? 'Ближайшее хорошее'
                                  : '${entry.value.distanceKm.toStringAsFixed(0)} км · ${(entry.value.bestScore * 100).round()}%',
                            ),
                            onSelected: (_) => setState(() {
                              _selectedResult = entry.key;
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
    final time = DateFormat('EEEE, dd MMMM y, HH:mm', 'ru').format(result.bestTime);
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
                Text('Астрономический план — без прогноза погоды', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text(result.place.name),
                Text('${result.distanceKm.toStringAsFixed(1)} км · $time', style: const TextStyle(color: Colors.white70)),
                const SizedBox(height: 12),
                Wrap(spacing: 14, children: [
                  _Metric('Высота цели', '${result.altitudeDeg.toStringAsFixed(0)}°'),
                  _Metric('Азимут', '${result.azimuthDeg.toStringAsFixed(0)}°'),
                  _Metric('Геометрия', '${(result.score * 100).round()}%'),
                ]),
              ],
            ),
          ),
        ),
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
        child: IconButton(tooltip: tooltip, icon: Icon(icon), onPressed: onPressed),
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
          Text(label, style: const TextStyle(fontSize: 11, color: Colors.white60)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      );
}

String _targetLabel(String value) => switch (value) {
      'moon' => 'Луна',
      'milky_way' => 'Млечный Путь',
      'jupiter' => 'Юпитер',
      'saturn' => 'Сатурн',
      'mars' => 'Марс',
      'best_night_sky' => 'Лучшее ночное небо',
      _ => value,
    };

String _scopeLabel(String value) => switch (value) {
      'adaptive' => 'в заданном радиусе',
      'country' => 'только в моей стране',
      'global' => 'по всему миру',
      _ => value,
    };

String _stageLabel(String value) => switch (value) {
      'queued' => 'Подготавливаем запрос…',
      'resolving_target' => 'Уточняем небесный объект…',
      'generating_cells' => 'Ищем поверхности поблизости…',
      'fetching_elevation' => 'Проверяем рельеф…',
      'reading_surface_windows' => 'Оцениваем поверхность…',
      'applying_static_filters' => 'Отсеиваем неподходящие точки…',
      'fetching_weather' => 'Получаем прогноз погоды…',
      'calculating_astronomy' => 'Рассчитываем видимость…',
      'checking_access' => 'Проверяем подъезд…',
      'ranking' => 'Выбираем ближайший хороший вариант…',
      'expanding_horizon' => 'В ближайшие дни окна нет — проверяем две недели…',
      _ => 'Выполняем расчёт…',
    };

String _terminalMessage(String value) => switch (value) {
      'cancelled' => 'Расчёт отменён.',
      'expired' => 'Результат устарел. Запустите поиск снова.',
      _ => 'Расчёт завершился с ошибкой.',
    };

String _warningsMessage(List<String> warnings) {
  if (warnings.contains('target_not_visible_in_scope')) {
    return 'Объект не поднимается достаточно высоко в выбранной области. Измените регион или цель.';
  }
  if (warnings.contains('weather_unavailable')) {
    return 'Прогноз временно недоступен. Повторите запрос через несколько минут.';
  }
  if (warnings.contains('no_candidate_places')) {
    return 'В этом радиусе не найдено подходящей поверхности. Увеличьте радиус.';
  }
  if (warnings.contains('no_observation_window')) {
    return 'За две недели нет подтверждённого погодой окна: мешают горизонт, Солнце, Луна или облачность. Для более дальней даты нужен астрономический план без прогноза погоды.';
  }
  return warnings.isEmpty ? 'Подходящий результат не найден.' : warnings.join(' · ');
}

String _warningLabel(String value) => switch (value) {
      'unverified_place' => 'точка не проверена',
      'darkness_is_proxy' => 'темнота оценена приближённо',
      'low_confidence' => 'предварительный прогноз',
      'high_dew_risk' => 'возможна роса',
      'strong_wind' => 'сильный ветер',
      _ => value,
    };
