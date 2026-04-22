"""HTML viewer generator for RTM pipeline batch outputs.

Public API:
    from autoqa.viewer import build_viewer, write_viewer
    write_viewer("logs/run-<ts>/outputs.jsonl")  # writes viewer.html next to it

CLI:
    uv run python -m autoqa.viewer logs/run-<ts>/outputs.jsonl [-o viewer.html]
"""

from autoqa.viewer.generator import build_viewer, write_viewer
from autoqa.viewer.template import HTML_TEMPLATE

__all__ = ["build_viewer", "write_viewer", "HTML_TEMPLATE"]
