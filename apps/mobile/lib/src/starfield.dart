import 'dart:math';

import 'package:flutter/material.dart';

class StarfieldBackground extends StatelessWidget {
  const StarfieldBackground({
    required this.child,
    super.key,
  });

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: const _StarfieldPainter(),
      child: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(-0.35, -0.75),
            radius: 1.35,
            colors: <Color>[
              Color(0xFF243B68),
              Color(0xFF111A32),
              Color(0xFF060913),
            ],
          ),
        ),
        child: child,
      ),
    );
  }
}

class _StarfieldPainter extends CustomPainter {
  const _StarfieldPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final random = Random(41827);
    final paint = Paint()..style = PaintingStyle.fill;
    for (var index = 0; index < 180; index++) {
      final x = random.nextDouble() * size.width;
      final y = random.nextDouble() * size.height;
      final radius = 0.35 + random.nextDouble() * 1.25;
      paint.color = Colors.white.withValues(
        alpha: 0.25 + random.nextDouble() * 0.65,
      );
      canvas.drawCircle(Offset(x, y), radius, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StarfieldPainter oldDelegate) => false;
}
