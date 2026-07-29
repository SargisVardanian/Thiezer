import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'api_client.dart';
import 'models.dart';

class CelestialSearchField extends StatefulWidget {
  const CelestialSearchField({
    required this.api,
    required this.point,
    required this.selected,
    required this.onSelected,
    super.key,
  });

  final ThiezerApiClient api;
  final GeoPoint point;
  final CelestialObject? selected;
  final ValueChanged<CelestialObject?> onSelected;

  @override
  State<CelestialSearchField> createState() => _CelestialSearchFieldState();
}

class _CelestialSearchFieldState extends State<CelestialSearchField> {
  static const _filters = <String, String>{
    'star': 'Stars',
    'galaxy': 'Galaxies',
    'nebula': 'Nebulae',
    'cluster': 'Clusters',
    'exoplanet': 'Exoplanets',
    'comet': 'Comets',
    'asteroid': 'Asteroids',
  };

  final _controller = TextEditingController();
  final _selectedTypes = <String>{};
  Timer? _debounce;
  Completer<void>? _abort;
  int _request = 0;
  List<CelestialObject> _results = const [];
  List<String> _providerWarnings = const [];
  String? _error;
  CelestialVisibilityPreview? _visibility;
  bool _searching = false;

  @override
  void dispose() {
    _debounce?.cancel();
    _cancelRequest();
    _controller.dispose();
    super.dispose();
  }

  void _cancelRequest() {
    final abort = _abort;
    if (abort != null && !abort.isCompleted) abort.complete();
    _abort = null;
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    _cancelRequest();
    final query = value.trim();
    if (query.length < 2) {
      setState(() {
        _results = const [];
        _providerWarnings = const [];
        _error = null;
        _searching = false;
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 450), () async {
      final request = ++_request;
      final abort = Completer<void>();
      _abort = abort;
      if (mounted) setState(() => _searching = true);
      try {
        final response = await widget.api.searchCelestialObjects(
          query,
          types: _selectedTypes,
          abortTrigger: abort.future,
        );
        if (!mounted || request != _request) return;
        setState(() {
          _results = response.results;
          _providerWarnings = response.warnings;
          _error = response.results.isEmpty
              ? 'No objects found. Change the filter or refine the name.'
              : null;
        });
      } on ApiRequestCancelled {
        // A new query superseded this request.
      } on Object {
        if (!mounted || request != _request) return;
        setState(
          () => _error =
              'The catalog is temporarily unavailable. You can select a preset.',
        );
      } finally {
        if (mounted && request == _request) {
          setState(() => _searching = false);
        }
      }
    });
  }

  void _toggleType(String type) {
    setState(() {
      if (!_selectedTypes.add(type)) _selectedTypes.remove(type);
    });
    _onChanged(_controller.text);
  }

  Future<void> _select(CelestialObject item) async {
    widget.onSelected(item);
    _controller.clear();
    setState(() {
      _results = const [];
      _visibility = null;
      _error = null;
    });
    try {
      final preview = await widget.api.celestialVisibility(
        object: item,
        point: widget.point,
      );
      if (!mounted || widget.selected?.objectId != item.objectId) return;
      setState(() => _visibility = preview);
    } on Object {
      if (mounted) {
        setState(
          () => _error = 'The visibility preview is temporarily unavailable.',
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: _controller,
          onChanged: _onChanged,
          decoration: InputDecoration(
            labelText: 'Search for a star, galaxy, comet, or exoplanet',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _searching
                ? const Padding(
                    padding: EdgeInsets.all(13),
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : null,
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: _filters.entries
              .map(
                (entry) => FilterChip(
                  label: Text(entry.value),
                  selected: _selectedTypes.contains(entry.key),
                  onSelected: (_) => _toggleType(entry.key),
                ),
              )
              .toList(growable: false),
        ),
        if (widget.selected != null) ...[
          const SizedBox(height: 8),
          InputChip(
            label: Text(
              '${widget.selected!.name} · ${_typeLabel(widget.selected!.objectClass)}',
            ),
            onPressed: () => _showDetails(context, widget.selected!),
            onDeleted: () {
              widget.onSelected(null);
              setState(() => _visibility = null);
            },
          ),
          Text(
            widget.selected!.attribution,
            style: const TextStyle(fontSize: 11, color: Colors.white60),
          ),
          if (widget.selected!.objectClass == 'exoplanet')
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text(
                'Showing host-star visibility; the exoplanet itself is not directly visible.',
                style: TextStyle(fontSize: 12, color: Colors.amberAccent),
              ),
            ),
          if (_visibility != null) _VisibilityCard(preview: _visibility!),
        ],
        if (_providerWarnings.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              _providerWarnings.join(' · '),
              style: const TextStyle(fontSize: 12, color: Colors.amberAccent),
            ),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        ..._results.map(
          (item) => Card(
            margin: const EdgeInsets.only(top: 6),
            child: ListTile(
              dense: true,
              title: Text(item.name),
              subtitle: Text(
                [
                  _typeLabel(item.objectClass),
                  if (item.apparentMagnitude != null)
                    'm ${item.apparentMagnitude!.toStringAsFixed(2)}',
                  if (item.aliases.isNotEmpty) item.aliases.take(2).join(', '),
                  item.attribution,
                ].join(' · '),
              ),
              trailing: IconButton(
                tooltip: 'Details',
                onPressed: () => _showDetails(context, item),
                icon: const Icon(Icons.info_outline),
              ),
              onTap: () => _select(item),
            ),
          ),
        ),
      ],
    );
  }
}

class _VisibilityCard extends StatelessWidget {
  const _VisibilityCard({required this.preview});

  final CelestialVisibilityPreview preview;

  @override
  Widget build(BuildContext context) {
    final format = DateFormat('dd MMM HH:mm');
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Now ${preview.altitudeDeg.toStringAsFixed(1)}° · '
              '${preview.aboveHorizon ? 'above the horizon' : 'below the horizon'}',
            ),
            Text('Azimuth ${preview.azimuthDeg.toStringAsFixed(1)}°'),
            if (preview.riseUtc != null)
              Text('Rise: ${format.format(preview.riseUtc!)}'),
            if (preview.setUtc != null)
              Text('Set: ${format.format(preview.setUtc!)}'),
            if (preview.culminationUtc != null)
              Text(
                'Culmination: ${format.format(preview.culminationUtc!)}'
                '${preview.maximumAltitudeDeg == null ? '' : ' · ${preview.maximumAltitudeDeg!.toStringAsFixed(1)}°'}',
              ),
            Text(
              'Modes: ${preview.observationCapabilities.map(_modeLabel).join(', ')}',
            ),
            if (preview.warnings.isNotEmpty)
              Text(
                preview.warnings.join(' · '),
                style: const TextStyle(fontSize: 11, color: Colors.amberAccent),
              ),
          ],
        ),
      ),
    );
  }
}

Future<void> _showDetails(BuildContext context, CelestialObject item) async {
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(item.name),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Type: ${_typeLabel(item.objectClass)}'),
            Text('Provider ID: ${item.provider}/${item.objectId}'),
            if (item.aliases.isNotEmpty)
              Text('Names: ${item.aliases.join(', ')}'),
            if (item.apparentMagnitude != null)
              Text(
                  'Apparent magnitude: ${item.apparentMagnitude!.toStringAsFixed(2)}'),
            if (item.spectralType != null)
              Text('Spectrum: ${item.spectralType}'),
            if (item.redshift != null) Text('Redshift: ${item.redshift}'),
            if (item.orbitalPeriodDays != null)
              Text('Orbital period: ${item.orbitalPeriodDays} days'),
            if (item.hostStarName != null)
              Text('Host star: ${item.hostStarName}'),
            const SizedBox(height: 10),
            Text(item.attribution),
            if (item.warnings.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                item.warnings.join('\n'),
                style: const TextStyle(color: Colors.amberAccent),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    ),
  );
}

String _typeLabel(String value) => switch (value) {
      'star' => 'star',
      'galaxy' => 'galaxy',
      'nebula' => 'nebula',
      'cluster' => 'cluster',
      'exoplanet' => 'exoplanet',
      'comet' => 'comet',
      'asteroid' => 'asteroid',
      'solar_system_body' => 'Solar System body',
      _ => value,
    };

String _modeLabel(String value) => switch (value) {
      'naked_eye' => 'naked eye',
      'binoculars' => 'binoculars',
      'telescope' => 'telescope',
      'camera' => 'camera',
      _ => value,
    };
