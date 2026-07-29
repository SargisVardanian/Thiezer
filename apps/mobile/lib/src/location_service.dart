import 'package:geolocator/geolocator.dart';

import 'models.dart';

class LocationService {
  Future<GeoPoint> currentLocation() async {
    final enabled = await Geolocator.isLocationServiceEnabled();
    if (!enabled) {
      throw StateError('Location services are disabled in system settings.');
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw StateError('Location permission was denied.');
    }
    if (permission == LocationPermission.deniedForever) {
      throw StateError(
        'Location permission is permanently denied. Open the app settings to allow it.',
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
