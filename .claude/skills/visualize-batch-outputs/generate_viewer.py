"""Thin CLI wrapper around ``autoqa.viewer`` for the skill entry point.

The implementation (HTML template, build_viewer, write_viewer) lives in the
``autoqa.viewer`` package so it can also be called from the pytest session
teardown (tests/conftest.py) and any other in-repo caller. Keeping this script
as a one-liner wrapper means the skill has exactly one invocation surface:

    uv run python .claude/skills/visualize-batch-outputs/generate_viewer.py \
        logs/run-<ts>/outputs.jsonl [-o viewer.html]

The equivalent module form ``uv run python -m autoqa.viewer ...`` works too.
"""

from __future__ import annotations

import sys

from autoqa.viewer.generator import main

if __name__ == "__main__":
    sys.exit(main())
