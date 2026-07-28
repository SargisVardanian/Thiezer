from __future__ import annotations

import argparse
import json

from common import ROOT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    with (ROOT / args.manifest).open() as handle:
        print(json.dumps(json.load(handle), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
