import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:thiezer_app/src/map_first_discovery.dart';

void main() {
  testWidgets('map-first discovery is the initial experience', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(home: MapFirstDiscoveryScreen()),
    );
    await tester.pump();

    expect(find.byType(MapFirstDiscoveryScreen), findsOneWidget);
    expect(find.byIcon(Icons.search), findsOneWidget);
    expect(find.text('Search'), findsOneWidget);
    expect(find.text('Moon'), findsOneWidget);
  });
}
