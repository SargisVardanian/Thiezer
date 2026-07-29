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
        cardTheme: CardThemeData(
          color: const Color(0xF0121D32),
          elevation: 14,
          shadowColor: Colors.black54,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(24),
            side: const BorderSide(color: Color(0xFF263B5C)),
          ),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFF9FC1FF),
            foregroundColor: const Color(0xFF10233D),
            textStyle: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
        inputDecorationTheme: const InputDecorationTheme(
          filled: true,
          border: OutlineInputBorder(),
        ),
      ),
      home: const MapFirstDiscoveryScreen(),
    ),
  );
}
