import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'models.dart';

class CelestialSearchField extends StatefulWidget {
  const CelestialSearchField({
    required this.api,
    required this.selected,
    required this.onSelected,
    super.key,
  });

  final ThiezerApiClient api;
  final CelestialObject? selected;
  final ValueChanged<CelestialObject?> onSelected;

  @override
  State<CelestialSearchField> createState() => _CelestialSearchFieldState();
}

class _CelestialSearchFieldState extends State<CelestialSearchField> {
  Timer? _debounce;
  int _request = 0;
  List<CelestialObject> _results = const [];
  String? _error;

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    final query = value.trim();
    if (query.length < 2) {
      setState(() {
        _results = const [];
        _error = null;
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 450), () async {
      final request = ++_request;
      try {
        final results = await widget.api.searchCelestialObjects(query);
        if (!mounted || request != _request) return;
        setState(() {
          _results = results;
          _error = null;
        });
      } on Object {
        if (!mounted || request != _request) return;
        setState(
          () => _error = 'Каталог временно недоступен. Можно выбрать preset.',
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          onChanged: _onChanged,
          decoration: const InputDecoration(
            labelText: 'Искать звезду, галактику или экзопланету',
            prefixIcon: Icon(Icons.search),
          ),
        ),
        if (widget.selected != null) ...[
          const SizedBox(height: 8),
          InputChip(
            label: Text(
              '${widget.selected!.name} · ${widget.selected!.objectClass}',
            ),
            onDeleted: () => widget.onSelected(null),
          ),
          Text(
            widget.selected!.attribution,
            style: const TextStyle(fontSize: 11, color: Colors.white60),
          ),
        ],
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        ..._results.map(
          (item) => ListTile(
            dense: true,
            title: Text(item.name),
            subtitle: Text('${item.objectClass} · ${item.attribution}'),
            onTap: () {
              widget.onSelected(item);
              setState(() => _results = const []);
            },
          ),
        ),
      ],
    );
  }
}
