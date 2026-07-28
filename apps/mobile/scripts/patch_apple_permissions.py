#!/usr/bin/env python3
from __future__ import annotations

import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def update_plist(path: Path, values: dict[str, object]) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {path}; run flutter create first.")
    with path.open("rb") as handle:
        data = plistlib.load(handle)
    data.update(values)
    with path.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)


update_plist(
    ROOT / "ios" / "Runner" / "Info.plist",
    {
        "NSLocationWhenInUseUsageDescription": (
            "Thiezer uses your location to find nearby observation sites and stores."
        ),
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
update_plist(
    ROOT / "macos" / "Runner" / "Info.plist",
    {
        "NSLocationUsageDescription": (
            "Thiezer uses your location to find nearby observation sites and stores."
        ),
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
for entitlement_name in ("DebugProfile.entitlements", "Release.entitlements"):
    update_plist(
        ROOT / "macos" / "Runner" / entitlement_name,
        {
            "com.apple.security.personal-information.location": True,
            "com.apple.security.network.client": True,
        },
    )
