#!/usr/bin/env python3
"""Print the changes for a release from the git history (used by .github/workflows/release.yml).

Usage: python3 scripts/release_notes.py <git range, e.g. v2.2.0..HEAD or HEAD>

Every commit becomes a bullet with its subject line. Lines of the commit message
that start with "- " are added as sub-bullets, so one commit can describe several
changes. Version commits ("Essential IP Cam Recorder 0.2.0") are left out.
"""

import re
import subprocess
import sys

VERSION_COMMIT = re.compile(r"^Essential IP Cam Recorder \d")


def main() -> None:
    log = subprocess.run(
        ["git", "log", "--no-merges", "--format=%s%x1f%b%x1e", sys.argv[1]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for record in log.split("\x1e"):
        subject, _, body = record.strip("\n").partition("\x1f")
        if not subject or VERSION_COMMIT.match(subject):
            continue
        print(f"- {subject}")
        for line in body.splitlines():
            if line.startswith("- "):
                print(f"  {line}")


if __name__ == "__main__":
    main()
