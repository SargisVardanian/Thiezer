import 'package:geolocator/geolocator.dart';

import 'models.dart';

class LocationService {
  Future<GeoPoint> currentLocation() async {
    final enabled = await Geolocator.isLocationServiceEnabled();
    if (!enabled) {
      throw StateError('Геолокация выключена в системных настройках.');
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw StateError('Доступ к геолокации отклонён.');
    }
    if (permission == LocationPermission.deniedForever) {
      throw StateError(
        'Доступ к геолокации запрещён навсегда. Откройте настройки приложения.',
      );
    }

    const settings = LocationSettings(
      accuracy: LocationAccuracy.high,
      timeLimit: Duration(seconds: 15),
    );
    final position =
        await Geolocator.getCurrentPosition(locationSettings: settings);
    return GeoPoint(position.latitude, position.longitude);
  }
}
