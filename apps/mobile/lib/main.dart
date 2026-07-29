import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'src/map_first_discovery.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('en');
  final scheme = ColorScheme.fromSeed(
    seedColor: const Color(0xFF89B4FF),
    brightness: Brightness.dark,
  );
  runApp(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Thiezer',
      locale: const Locale('en'),
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
