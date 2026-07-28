import 'package:flutter/material.dart';

import 'src/map_first_discovery.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final scheme = ColorScheme.fromSeed(
    seedColor: const Color(0xFF89B4FF),
    brightness: Brightness.dark,
  );
  runApp(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Thiezer',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: scheme,
        scaffoldBackgroundColor: const Color(0xFF071020),
        useMaterial3: true,
        inputDecorationTheme: const InputDecorationTheme(
          filled: true,
          border: OutlineInputBorder(),
        ),
      ),
      home: const MapFirstDiscoveryScreen(),
    ),
  );
}
