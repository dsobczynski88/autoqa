"""HTML viewer generator for RTM and test-case pipeline batch outputs.

Public API:
    from autoqa.viewer import write_viewer, write_viewer_tc
    write_viewer("logs/run-<ts>/outputs.jsonl")        # RTM (test_suite_reviewer)
    write_viewer_tc("logs/run-<ts>/outputs.jsonl")     # test_case_reviewer

CLI:
    uv run python -m autoqa.viewer logs/run-<ts>/outputs.jsonl [-o viewer.html] [--type rtm|tc]
"""

from autoqa.viewer.generator import (
    build_viewer,
    build_viewer_tc,
    write_viewer,
    write_viewer_tc,
)
from autoqa.viewer.template import HTML_TEMPLATE
from autoqa.viewer.template_test_case import TC_HTML_TEMPLATE

__all__ = [
    "build_viewer",
    "build_viewer_tc",
    "write_viewer",
    "write_viewer_tc",
    "HTML_TEMPLATE",
    "TC_HTML_TEMPLATE",
]
