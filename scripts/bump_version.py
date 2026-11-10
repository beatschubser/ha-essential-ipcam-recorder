#!/usr/bin/env python3
"""Set the version in all three places at once.

Usage: python3 scripts/bump_version.py 2.1.0          (release)
       python3 scripts/bump_version.py 2.1.0-beta.1   (pre-release / test build)
"""

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "custom_components" / "essential_ipcam_recorder"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


def main() -> None:
    if len(sys.argv) != 2 or not SEMVER.match(sys.argv[1]):
        sys.exit(__doc__)
    version = sys.argv[1]

    manifest = BASE / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = version
    manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for path, pattern, repl in [
        (BASE / "const.py", r'^VERSION = "[^"]+"', f'VERSION = "{version}"'),
        (BASE / "frontend" / "essential-ipcam-recorder-card.js", r'^const VERSION = "[^"]+";', f'const VERSION = "{version}";'),
    ]:
        text = path.read_text(encoding="utf-8")
        new, count = re.subn(pattern, repl, text, count=1, flags=re.M)
        if count != 1:
            sys.exit(f"Version not found in {path}")
        path.write_text(new, encoding="utf-8")

    print(f"Version set to {version}")


if __name__ == "__main__":
    main()
