import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
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
    TargetOption(id: 'milky_way', label: 'Млечный Путь'),
    TargetOption(id: 'best_night_sky', label: 'Лучшее ночное небо'),
    TargetOption(id: 'moon', label: 'Луна'),
    TargetOption(id: 'jupiter', label: 'Юпитер'),
    TargetOption(id: 'mars', label: 'Марс'),
    TargetOption(id: 'alpha_centauri', label: 'Альфа Центавра'),
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
  String _scope = 'adaptive';
  double _radiusKm = 250;
  bool _loading = false;
  String? _error;
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

  void _readManualCoordinates() {
    final latitude = double.tryParse(_latitudeController.text.trim());
    final longitude = double.tryParse(_longitudeController.text.trim());
    if (latitude == null || longitude == null || latitude.abs() > 90 || longitude.abs() > 180) {
      setState(() => _error = 'Проверьте широту и долготу.');
      return;
    }
    setState(() {
      _location = GeoPoint(latitude, longitude);
      _error = null;
    });
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
    _readManualCoordinates();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await _api.searchRecommendations(
        location: _location,
        target: _target,
        radiusKm: _radiusKm,
        scope: _scope,
        countryCode: _countryController.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _recommendations = response.results;
        if (response.results.isEmpty) {
          _error = _humanWarnings(response.warnings);
        }
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _searchStores() async {
    _readManualCoordinates();
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
          _error = 'В выбранном радиусе не найдено размеченных магазинов.';
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
    if (uri == null || !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) setState(() => _error = 'Не удалось открыть ссылку.');
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
          scope: _scope,
          radiusKm: _radiusKm,
          recommendations: _recommendations,
          loading: _loading,
          error: _error,
          onTargetChanged: (value) => setState(() => _target = value),
          onScopeChanged: (value) => setState(() => _scope = value),
          onRadiusChanged: (value) => setState(() => _radiusKm = value),
          onUseLocation: _useCurrentLocation,
          onSearch: _searchSky,
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
            NavigationDestination(icon: Icon(Icons.auto_awesome), label: 'Небо'),
            NavigationDestination(icon: Icon(Icons.camera_alt_outlined), label: 'Техника'),
            NavigationDestination(icon: Icon(Icons.settings_outlined), label: 'Настройки'),
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
    required this.scope,
    required this.radiusKm,
    required this.recommendations,
    required this.loading,
    required this.error,
    required this.onTargetChanged,
    required this.onScopeChanged,
    required this.onRadiusChanged,
    required this.onUseLocation,
    required this.onSearch,
    required this.onOpenUrl,
  });

  final GeoPoint location;
  final TextEditingController latitudeController;
  final TextEditingController longitudeController;
  final TextEditingController countryController;
  final List<TargetOption> targets;
  final String target;
  final String scope;
  final double radiusKm;
  final List<RecommendationResult> recommendations;
  final bool loading;
  final String? error;
  final ValueChanged<String> onTargetChanged;
  final ValueChanged<String> onScopeChanged;
  final ValueChanged<double> onRadiusChanged;
  final VoidCallback onUseLocation;
  final VoidCallback onSearch;
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
          scope: scope,
          radiusKm: radiusKm,
          loading: loading,
          error: error,
          onTargetChanged: onTargetChanged,
          onScopeChanged: onScopeChanged,
          onRadiusChanged: onRadiusChanged,
          onUseLocation: onUseLocation,
          onSearch: onSearch,
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
          children: [controls, const SizedBox(height: 16), SizedBox(height: 620, child: results)],
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
    required this.scope,
    required this.radiusKm,
    required this.loading,
    required this.error,
    required this.onTargetChanged,
    required this.onScopeChanged,
    required this.onRadiusChanged,
    required this.onUseLocation,
    required this.onSearch,
  });

  final TextEditingController latitudeController;
  final TextEditingController longitudeController;
  final TextEditingController countryController;
  final List<TargetOption> targets;
  final String target;
  final String scope;
  final double radiusKm;
  final bool loading;
  final String? error;
  final ValueChanged<String> onTargetChanged;
  final ValueChanged<String> onScopeChanged;
  final ValueChanged<double> onRadiusChanged;
  final VoidCallback onUseLocation;
  final VoidCallback onSearch;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      shrinkWrap: true,
      children: [
        Text('Что вы хотите увидеть?', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: target,
          decoration: const InputDecoration(labelText: 'Небесная цель'),
          items: targets
              .map((item) => DropdownMenuItem(value: item.id, child: Text(item.label)))
              .toList(growable: false),
          onChanged: (value) {
            if (value != null) onTargetChanged(value);
          },
        ),
        const SizedBox(height: 16),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'adaptive', label: Text('Рядом'), icon: Icon(Icons.radar)),
            ButtonSegment(value: 'country', label: Text('Страна'), icon: Icon(Icons.flag_outlined)),
            ButtonSegment(value: 'global', label: Text('Без границ'), icon: Icon(Icons.public)),
          ],
          selected: {scope},
          onSelectionChanged: (value) => onScopeChanged(value.first),
        ),
        if (scope == 'country') ...[
          const SizedBox(height: 12),
          TextField(
            controller: countryController,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(labelText: 'ISO-код страны, например AM'),
          ),
        ],
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: latitudeController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
                decoration: const InputDecoration(labelText: 'Широта'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: longitudeController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
                decoration: const InputDecoration(labelText: 'Долгота'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: loading ? null : onUseLocation,
          icon: const Icon(Icons.my_location),
          label: const Text('Использовать мою геолокацию'),
        ),
        const SizedBox(height: 14),
        Text('Радиус: ${radiusKm.round()} км'),
        Slider(
          value: radiusKm,
          min: 25,
          max: 500,
          divisions: 19,
          label: '${radiusKm.round()} км',
          onChanged: loading ? null : onRadiusChanged,
        ),
        const Text(
          'Радиус ограничивает вычисления. В маленькой стране adaptive-поиск может перейти границу; '
          'в большой стране он останется локальным.',
          style: TextStyle(color: Colors.white70),
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
          label: const Text('Найти лучшее небо'),
        ),
        if (error != null) ...[
          const SizedBox(height: 12),
          Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 12),
        const Text(
          'Динамические точки пока непроверенные: приложение не гарантирует законный доступ, '
          'состояние дороги, парковку или безопасность ночью.',
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
            'Здесь появятся лучшие точки, временные окна, прогноз и маршруты.',
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
                      child: const Icon(Icons.my_location, color: Colors.lightBlueAccent, size: 32),
                    ),
                    ...recommendations.map(
                      (item) => Marker(
                        point: LatLng(item.place.point.latitude, item.place.point.longitude),
                        width: 46,
                        height: 46,
                        child: Tooltip(
                          message: item.place.name,
                          child: CircleAvatar(
                            backgroundColor: _scoreColor(item.bestScore),
                            child: Text('${item.rank}', style: const TextStyle(color: Colors.black)),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const RichAttributionWidget(
                  attributions: [TextSourceAttribution('OpenStreetMap contributors')],
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
                      Text(item.place.name, style: Theme.of(context).textTheme.titleMedium),
                      Text(
                        '${item.distanceKm.toStringAsFixed(1)} км · $time · ${item.place.kind}',
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
                _Metric(label: 'Облака', value: '${(item.conditions.cloud * 100).round()}%'),
                _Metric(label: 'Ветер', value: '${item.conditions.windMps.toStringAsFixed(1)} м/с'),
                _Metric(label: 'Цель', value: '${item.astronomy.altitudeDeg.toStringAsFixed(0)}°'),
                _Metric(label: 'Темнота', value: '${(item.place.darknessScore * 100).round()}%'),
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
        Text('Техника поблизости', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 6),
        Text('Камеры, оптика, электроника и outdoor-магазины в радиусе ${radiusKm.round()} км.'),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: loading ? null : onSearch,
          icon: const Icon(Icons.search),
          label: const Text('Найти магазины'),
        ),
        if (error != null) ...[
          const SizedBox(height: 10),
          Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 12),
        ...stores.map(
          (store) => Card(
            child: ListTile(
              title: Text(store.name),
              subtitle: Text([
                if (store.distanceKm != null) '${store.distanceKm!.toStringAsFixed(1)} км',
                ...store.categories.take(3),
                if (store.address != null) store.address!,
              ].join(' · ')),
              trailing: PopupMenuButton<String>(
                onSelected: (value) => onOpenUrl(value),
                itemBuilder: (_) => [
                  PopupMenuItem(value: store.website, child: const Text('Открыть сайт')),
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
        Text('Подключение', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 12),
        TextField(
          controller: apiController,
          autocorrect: false,
          decoration: const InputDecoration(labelText: 'Thiezer API URL'),
        ),
        const SizedBox(height: 10),
        FilledButton(onPressed: onSave, child: const Text('Сохранить и проверить')),
        const SizedBox(height: 10),
        Text('Текущий адрес: $currentApiUrl'),
        const SizedBox(height: 24),
        const Text(
          'Для физического iPhone укажите LAN-адрес Mac, например '
          'http://192.168.1.20:8000, и запустите backend с --host 0.0.0.0.',
          style: TextStyle(color: Colors.white70),
        ),
        const SizedBox(height: 24),
        const Text(
          'Карта OpenStreetMap в этой сборке предназначена для локальной разработки. '
          'Перед публичным релизом нужен собственный PMTiles или коммерческий tile provider.',
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
      'unverified_place' => 'точка не проверена',
      'darkness_is_proxy' => 'темнота оценена приближённо',
      'low_confidence' => 'низкая уверенность прогноза',
      'high_dew_risk' => 'риск росы',
      'strong_wind' => 'сильный ветер',
      _ => warning.replaceAll('_', ' '),
    };

String _humanWarnings(List<String> warnings) {
  if (warnings.contains('target_not_visible_in_scope')) {
    return 'Эта цель не поднимается достаточно высоко в выбранной области и периоде.';
  }
  if (warnings.contains('weather_unavailable')) {
    return 'Не удалось получить погоду для найденных точек.';
  }
  if (warnings.contains('no_candidate_places')) {
    return 'В радиусе нет подходящих размеченных точек. Увеличьте радиус.';
  }
  if (warnings.contains('no_observation_window')) {
    return 'В выбранные дни нет достаточно хорошего окна. Попробуйте другой период или цель.';
  }
  return warnings.isEmpty ? 'Результаты не найдены.' : warnings.join(', ');
}
