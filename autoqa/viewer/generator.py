"""Build and write HTML viewer files from an RTM pipeline outputs.jsonl."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Iterable, Optional, Union

from autoqa.viewer.template import HTML_TEMPLATE

PathLike = Union[str, pathlib.Path]


def build_viewer(records: Iterable[dict], source_label: str, run_key: str) -> str:
    """Render the single-file HTML viewer for ``records``.

    ``source_label`` appears in the title/header (usually the JSONL path).
    ``run_key`` becomes part of the localStorage key that stores reviewer feedback,
    so the same run's ratings persist across re-opens of the same viewer.
    """
    data_json = json.dumps(list(records), ensure_ascii=False)
    data_json = data_json.replace("</", "<\\/")
    return (
        HTML_TEMPLATE
        .replace("{{DATA}}", data_json)
        .replace("{{SOURCE}}", _escape_html(source_label))
        .replace("{{TITLE}}", _escape_html(f"Batch output viewer — {source_label}"))
        .replace("{{RUN_KEY}}", _escape_html(run_key))
    )


def write_viewer(
    jsonl_path: PathLike,
    output_path: Optional[PathLike] = None,
) -> Optional[pathlib.Path]:
    """Read ``jsonl_path``, render the viewer, write to ``output_path``.

    Default output is ``<jsonl_dir>/viewer.html``. Returns the output path on
    success; returns ``None`` when the JSONL is empty (no viewer is written).
    Raises ``FileNotFoundError`` if the input path does not exist.
    """
    src = pathlib.Path(jsonl_path)
    if not src.exists():
        raise FileNotFoundError(src)

    records: list[dict] = []
    for i, line in enumerate(src.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{src}:{i}: invalid JSON ({e})") from e

    if not records:
        return None

    out = pathlib.Path(output_path) if output_path else src.parent / "viewer.html"
    run_key = src.parent.name or src.stem
    out.write_text(build_viewer(records, str(src), run_key), encoding="utf-8")
    return out


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl_path", help="Path to outputs.jsonl (one RTMReviewState per line)")
    ap.add_argument("-o", "--output", default=None,
                    help="Output HTML path. Default: <jsonl_dir>/viewer.html")
    args = ap.parse_args(argv)

    try:
        out = write_viewer(args.jsonl_path, args.output)
    except FileNotFoundError as e:
        print(f"error: {e} does not exist", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    if out is None:
        print(f"error: {args.jsonl_path} has no records", file=sys.stderr)
        return 4

    src = pathlib.Path(args.jsonl_path)
    n = sum(1 for line in src.read_text(encoding="utf-8").splitlines() if line.strip())
    print(f"wrote {out}  ({n} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
