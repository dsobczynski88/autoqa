---
name: manage-prompts
description: |
  Organize a repository's Jinja2 / text prompt templates into a versioned, hash-pinned,
  bundle-addressable registry that scales across model iterations and integrates cleanly
  with MLflow evaluation. Replaces flat-directory + filename-version-suffix conventions
  (which silently drift between prompt body and filename) with: per-role version
  directories, sidecar `meta.yaml` metadata, semver-flavour versioning, named prompt-set
  manifests for cross-component bundles, content-SHA256 provenance, render-time
  validation, and a CI-enforceable rule that published versions are immutable. Provides
  a phased migration path that lets a repo upgrade incrementally without breaking
  existing tests, plus reference loader code, pre-commit hook, and lint test stubs.
  Use when the user asks to "organize prompts", "set up prompt registry", "version
  prompts", "manage prompt versions", "prompt engineering best practices",
  "stop prompts from silently drifting", "bundle prompts into named sets",
  "promote a prompt set to production", or wants prompts that integrate cleanly with
  MLflow / experiment tracking. Sibling to evaluate-langgraph-mlflow (which scores
  pipelines using the prompt sets this skill defines) and the generate-*-dataset
  family (which produce labelled fixtures the evaluation runs against).
---

# manage-prompts

Establish a prompt-template registry inside a repository that supports versioning,
content-hash provenance, named bundles ("prompt sets"), render-time validation,
and clean MLflow integration. Targeted at projects that have already accumulated
3+ versions of any single prompt and are starting to feel pain comparing runs,
diffing changes, or knowing which prompts are wired in production.

## Mission

Move a repo's prompts from "flat directory of `<role>-v<n>.jinja2` files" to a
structured registry with five guarantees:

1. **Identity** — every prompt has a stable address (`role + version + content_sha256`).
2. **Provenance** — every prompt has metadata (author, date, parent, changelog,
   target component, content hash).
3. **Bundle-ability** — multiple prompts compose into named "sets" (the unit
   MLflow runs are pinned to and promoted on).
4. **Immutability** — published version directories are frozen; new behaviour
   requires a new version (no silent body edits).
5. **Validation** — Jinja2 syntax, required template variables, and manifest
   integrity are checked in CI on every PR that touches prompts.

## When to invoke

- "Organize prompts in this repo / set up a prompt registry"
- "We have 5 versions of `synthesizer.jinja2` and we don't know which is in prod"
- "How do I version prompts? / prompt engineering best practices"
- "Prompts get edited in place and we lose track of what changed"
- "Compare prompt set A vs B in MLflow / promote a prompt set"
- "Bundle prompts into named sets for A/B testing"
- "CI keeps failing because of bad Jinja2 — can we lint these?"

If the user asks to *evaluate* prompts, redirect to `evaluate-langgraph-mlflow`
(this skill defines the registry that skill consumes). If they want to
*generate* labelled datasets to evaluate against, redirect to
`generate-rtm-dataset` / `generate-tc-dataset`.

## Diagnose first (do this before recommending changes)

Run these checks against the target repo and report findings to the user
before proposing the migration:

| symptom | how to detect |
|---|---|
| Flat directory with mixed components | `ls autoqa/prompts/ \| wc -l` > 20 in one dir |
| Version-in-filename suffix | `*-v[0-9]*.jinja2` glob matches |
| Un-versioned alongside versioned | both `synthesizer.jinja2` AND `synthesizer-v6.jinja2` exist |
| Source-of-truth split | `grep "prompt_template:" nodes.py` AND `core/config.py::PromptConfig` both list defaults |
| No metadata sidecar | no `*.yaml` next to the `*.jinja2` files |
| No content hashing | no SHA references in any tooling |
| Implicit prompt sets | filenames spread across PromptConfig in code; no manifest |

State which pain points apply before proposing the target architecture, so the
user can confirm priorities.

## Six organizational axes — pick deliberately

### Axis A: Directory structure

| option | shape | pick when |
|---|---|---|
| Flat | `prompts/synthesizer-v6.jinja2` | <10 prompts total, no version churn |
| By component | `prompts/test_suite_reviewer/synthesizer-v6.jinja2` | Components share zero prompts |
| **Per-role version directory ★** | `prompts/synthesizer/v6.0.0/template.jinja2` | 3+ versions of any role; want metadata + tests alongside |
| By prompt set | `prompts/sets/rtm-v6/synthesizer.jinja2` | Sets are mostly disjoint; OK with version duplication across sets |

**Recommend per-role version directory** for any repo that has 3+ versions of
any single role. The version directory becomes a natural home for the template
body, sidecar metadata, and (optionally) snapshot test fixtures.

### Axis B: Metadata location

| option | shape | trade-off |
|---|---|---|
| Filename only | `synthesizer-v6.jinja2` | Loses everything except the version string |
| Jinja2 frontmatter | `{# --- name: ... #}` block | Self-contained but Jinja2's comment syntax is awkward for non-trivial YAML |
| **Sidecar `meta.yaml` ★** | `synthesizer/v6.0.0/meta.yaml` | Standard YAML; easy to validate; MLflow logs as artifact |
| Central registry | `prompts/registry.yaml` | One file = merge-conflict magnet on every prompt change |

### Axis C: Versioning scheme

| option | example | pick when |
|---|---|---|
| Sequential | v1 → v2 → v3 | Simple repos; team OK with opaque change scope |
| **Semver-flavour ★** | `v6.0.0` major / `v6.1.0` minor / `v6.0.1` patch | Want to communicate blast radius — major = output-schema change, minor = behavioural shift, patch = wording tweak |
| Named | `synthesizer/cautious` | Memorable but collision-prone over time |
| Date-stamped | `synthesizer/2026-04-27` | Lineage in name; harder to reference |

Semver maps cleanly to the impact taxonomy:
- **Major** — breaks consumers (changes JSON output schema, drops a field, renames a key, changes the Pydantic model the response is parsed against).
- **Minor** — changes verdicts/behaviour but output schema is stable (new rule, tightened threshold, restructured rationale guidance).
- **Patch** — wording / typo / formatting only; verdicts and behaviour unchanged.

### Axis D: Prompt-set bundling

A **prompt set** is the load-bearing concept for MLflow. A run is comparable
to another run only when both are tagged with a stable, named stack.

```yaml
# prompts/sets/rtm-v6.yaml
name: rtm-v6
component: test_suite_reviewer
description: Production stack as of 2026-04-27. Drops partial field; tightens triple-axis prompt.
prompts:
  decomposer:  v4.0.0
  summarizer:  v2.0.0
  coverage:    v6.0.0
  synthesizer: v6.0.0
status: production       # one of: experimental | candidate | production | deprecated
parent_set: rtm-v5
authored: 2026-04-27
```

Then `PromptConfig.from_set("rtm-v6")` reads this manifest, resolves to actual
templates, and exposes a single `prompt_set_name` param + `prompt_set_sha`
(SHA of the manifest YAML) for MLflow.

### Axis E: Content-hash provenance

The hidden bug is **filename pinned, body silently edited**. Three layered
mitigations (apply all three):

1. **Compute SHA256 at evaluation time** — write into `meta.yaml::content_sha256`;
   log to MLflow as `prompt_<role>_sha`.
2. **Pre-commit hook** — auto-update `meta.yaml::content_sha256` whenever the
   template body changes. Prevents drift at the source.
3. **CI lint enforces immutability** — once a version directory's
   `template.jinja2` SHA is registered (in git history of `meta.yaml`), it
   cannot change. New behaviour ⇒ new version directory.

### Axis F: Validation

Three checks that should run in CI on every prompt change:

1. **Jinja2 syntax** — `Environment.parse(body)` does not raise.
2. **Required template variables** — render with `meta.yaml::required_template_vars`
   bound to placeholders; ensure no `UndefinedError`.
3. **Output-schema round-trip** (where applicable) — for prompts whose response
   is parsed by a Pydantic model: render with example payload, run a fixed
   sample LLM-shaped response through `model_validate()`, ensure round-trip.

A `tests/unit/test_prompt_registry.py` walks every `meta.yaml`, exercises
checks (1) and (2), and asserts manifest integrity. Cheap; catches a class of
bugs MLflow can't detect post-hoc.

## Recommended target architecture

```
autoqa/prompts/
├── README.md                        # versioning conventions, status meanings
├── _registry.py                     # PromptConfig.from_set("rtm-v6") loader
├── sets/                            # named bundles — the MLflow handle
│   ├── rtm-v5.yaml
│   ├── rtm-v6.yaml
│   ├── rtm-experimental.yaml
│   ├── tc-v3.yaml
│   ├── tc-v4.yaml
│   └── hazard-v1.yaml
├── decomposer/
│   ├── v3.0.0/
│   │   ├── template.jinja2
│   │   └── meta.yaml
│   └── v4.0.0/
│       ├── template.jinja2
│       └── meta.yaml
├── summarizer/v2.0.0/...
├── coverage_evaluator/{v4.0.0, v5.0.0, v6.0.0}/...
├── synthesizer/{v2.0.0, v3.0.0, v4.0.0, v5.0.0, v6.0.0}/...
├── single_test_aggregator/{v3.0.0, v4.0.0}/...
├── single_test_coverage_eval/v3.0.0/...
├── single_test_logical_steps/v3.0.0/...
├── single_test_prereqs/v3.0.0/...
└── hazard_synthesizer/v1.0.0/...
```

### `meta.yaml` schema

```yaml
# Required
role: synthesizer                       # logical role (matches PromptConfig field)
version: v6.0.0                         # semver-flavour
component: test_suite_reviewer          # which graph this serves
authored: 2026-04-27                    # ISO-8601 date
content_sha256: <auto>                  # SHA256 of template.jinja2 body
status: published                       # one of: draft | published | deprecated

# Strongly recommended
parent_version: v5.0.0                  # lineage — null for v1.0.0
author: dsobczynski                     # stable identifier
required_template_vars: []              # Jinja2 vars consumers must bind
output_pydantic_model: SynthesizedAssessment   # null if free-form text
target_models: [gpt-4o-mini, gpt-4o]    # models this prompt was tested on

# Optional but useful
rubric: [M1, M2, M3, M4, M5]            # if applicable
changelog: |
  - Removed `partial` field from JSON output schema entirely.
  - Reinforced overall_verdict aggregation as deterministic AND.
tested_against_fixtures:
  - tests/fixtures/gold_dataset.jsonl
known_issues:
  - "gpt-4o-mini emits 'aligned' instead of 'Yes' on M5 ~5% of runs"
deprecates: []                          # which previous versions this supersedes
```

### Set manifest schema

```yaml
# Required
name: rtm-v6
component: test_suite_reviewer          # null OK for cross-component sets
prompts:                                # role -> version
  decomposer:  v4.0.0
  summarizer:  v2.0.0
  coverage:    v6.0.0
  synthesizer: v6.0.0
status: production                      # experimental | candidate | production | deprecated
authored: 2026-04-27

# Recommended
description: |
  Drops partial field from synthesizer output; tightens triple-axis rule.
parent_set: rtm-v5
promoted_from_run: <mlflow_run_id>      # provenance: which MLflow run blessed this
performance_baseline:                   # immutable record of what scored well
  fixture: tests/fixtures/test-suite-reviewer-200/inputs.jsonl
  overall_accuracy: 0.91
  rubric_macro_f1: 0.84
  measured_on: 2026-04-27
```

## Reference loader (`_registry.py` sketch)

```python
"""Prompt registry loader.

Resolves a named prompt-set manifest into a PromptConfig with content_sha256
attached per role, plus the manifest's own sha256 for MLflow run-param logging.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
import yaml

PROMPTS_DIR = Path(__file__).parent

@dataclass(frozen=True)
class ResolvedPrompt:
    role: str
    version: str                # e.g. "v6.0.0"
    template_path: Path         # absolute path to template.jinja2
    content_sha256: str         # 16-char short hash of body
    meta: dict                  # the meta.yaml contents

@dataclass(frozen=True)
class ResolvedPromptSet:
    name: str
    component: str | None
    status: str
    manifest_sha256: str
    prompts: dict[str, ResolvedPrompt]   # role -> resolved

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]

def load_set(name: str) -> ResolvedPromptSet:
    """Resolve a set manifest into a frozen, hash-pinned bundle."""
    manifest_path = PROMPTS_DIR / "sets" / f"{name}.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"prompt set {name!r} not found at {manifest_path}")
    manifest = yaml.safe_load(manifest_path.read_text())
    resolved = {}
    for role, version in manifest["prompts"].items():
        version_dir = PROMPTS_DIR / role / version
        template = version_dir / "template.jinja2"
        meta_path = version_dir / "meta.yaml"
        if not template.exists() or not meta_path.exists():
            raise FileNotFoundError(
                f"prompt set {name}: role={role} version={version} missing "
                f"template.jinja2 or meta.yaml at {version_dir}"
            )
        meta = yaml.safe_load(meta_path.read_text())
        actual_sha = _file_sha256(template)
        recorded_sha = meta.get("content_sha256")
        if recorded_sha and recorded_sha != actual_sha:
            raise ValueError(
                f"prompt set {name}: role={role} version={version} content drift — "
                f"meta.yaml records {recorded_sha} but template body is {actual_sha}. "
                "Either revert the body or bump the version."
            )
        resolved[role] = ResolvedPrompt(
            role=role, version=version, template_path=template,
            content_sha256=actual_sha, meta=meta,
        )
    return ResolvedPromptSet(
        name=manifest["name"],
        component=manifest.get("component"),
        status=manifest["status"],
        manifest_sha256=_file_sha256(manifest_path),
        prompts=resolved,
    )

def list_sets(status: str | None = None) -> list[str]:
    """Discovery helper — lists all set names, optionally filtered by status."""
    out = []
    for p in (PROMPTS_DIR / "sets").glob("*.yaml"):
        manifest = yaml.safe_load(p.read_text())
        if status is None or manifest.get("status") == status:
            out.append(manifest["name"])
    return sorted(out)
```

## Pre-commit hook (auto-update content_sha256)

```python
# scripts/update_prompt_meta.py — pre-commit entry point
import hashlib, sys
from pathlib import Path
import yaml

def main(paths: list[Path]) -> int:
    changed = []
    for tpl in paths:
        if tpl.name != "template.jinja2":
            continue
        meta_path = tpl.parent / "meta.yaml"
        if not meta_path.exists():
            print(f"missing meta.yaml at {meta_path}", file=sys.stderr)
            return 2
        body = tpl.read_bytes()
        new_sha = hashlib.sha256(body).hexdigest()[:16]
        meta = yaml.safe_load(meta_path.read_text())
        if meta.get("content_sha256") != new_sha:
            meta["content_sha256"] = new_sha
            meta_path.write_text(yaml.safe_dump(meta, sort_keys=False))
            changed.append(meta_path)
    if changed:
        print(f"updated content_sha256 in {len(changed)} meta.yaml file(s); "
              "stage and re-commit", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main([Path(p) for p in sys.argv[1:]]))
```

`.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: prompt-meta-sync
      name: Auto-update prompt meta.yaml content_sha256
      entry: uv run python scripts/update_prompt_meta.py
      language: system
      files: '^autoqa/prompts/.+/template\.jinja2$'
```

## CI lint test (`tests/unit/test_prompt_registry.py`)

```python
"""Walks the prompt registry, validates every set + version + body."""
import pytest
from pathlib import Path
import yaml
from jinja2 import Environment

from autoqa.prompts._registry import PROMPTS_DIR, load_set, _file_sha256

def _all_set_names() -> list[str]:
    return [p.stem for p in (PROMPTS_DIR / "sets").glob("*.yaml")]

@pytest.mark.parametrize("set_name", _all_set_names())
def test_set_resolves_cleanly(set_name):
    """Every set manifest resolves without missing files or sha drift."""
    s = load_set(set_name)   # raises on drift / missing files
    assert s.name == set_name

@pytest.mark.parametrize("set_name", _all_set_names())
def test_set_components_consistent(set_name):
    """Every prompt in a set targets the same component as the set itself."""
    s = load_set(set_name)
    if s.component is None:
        return
    for role, p in s.prompts.items():
        assert p.meta["component"] == s.component, (
            f"set {set_name} (component={s.component}) references "
            f"{role}@{p.version} but its meta lists component={p.meta['component']}"
        )

def _all_template_paths() -> list[Path]:
    return list(PROMPTS_DIR.rglob("template.jinja2"))

@pytest.mark.parametrize("template_path", _all_template_paths(), ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_template_jinja2_syntax(template_path):
    """Every template body is valid Jinja2."""
    env = Environment()
    env.parse(template_path.read_text(encoding="utf-8"))   # raises on syntax error

@pytest.mark.parametrize("template_path", _all_template_paths(), ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_template_meta_sha_matches(template_path):
    """meta.yaml::content_sha256 matches the actual body — catches drift."""
    meta_path = template_path.parent / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text())
    assert meta.get("content_sha256") == _file_sha256(template_path), (
        f"{template_path}: body changed but meta.yaml::content_sha256 not updated. "
        "Run pre-commit or bump the version."
    )

@pytest.mark.parametrize("template_path", _all_template_paths(), ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_template_renders_with_required_vars(template_path):
    """Template renders without UndefinedError when required_template_vars are bound."""
    meta_path = template_path.parent / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text())
    required = meta.get("required_template_vars") or []
    env = Environment()
    template = env.from_string(template_path.read_text(encoding="utf-8"))
    bindings = {var: f"<{var}>" for var in required}
    template.render(**bindings)   # raises on UndefinedError if a real-but-undocumented var is referenced
```

## MLflow integration

In the evaluation harness:

```python
from autoqa.prompts._registry import load_set
import mlflow

prompt_set = load_set("rtm-v6")

mlflow.log_params({
    "prompt_set_name":         prompt_set.name,
    "prompt_set_manifest_sha": prompt_set.manifest_sha256,
    # Per-role expansion for forensic comparison:
    **{f"prompt_{role}":     p.version       for role, p in prompt_set.prompts.items()},
    **{f"prompt_{role}_sha": p.content_sha256 for role, p in prompt_set.prompts.items()},
})
mlflow.set_tag("prompt_set_status", prompt_set.status)

# Save full manifest snapshot as an artifact (so a future-deleted set is still reproducible)
import json
mlflow.log_dict({
    "name": prompt_set.name,
    "manifest_sha256": prompt_set.manifest_sha256,
    "prompts": {
        role: {"version": p.version, "content_sha256": p.content_sha256, "meta": p.meta}
        for role, p in prompt_set.prompts.items()
    },
}, "prompt_set_snapshot.json")
```

Result in MLflow UI:
- Filter `params.prompt_set_name = "rtm-v6"` → all runs against this stack.
- Sort by `metrics.overall_accuracy` to find the best-performing run.
- Diff two runs → see exactly which `prompt_<role>` version changed.
- Filter `tags.prompt_set_status = "production"` → current prod baseline.

## Migration path (incremental — keeps everything green)

Each phase is independently shippable; phase 1+2 alone deliver 80% of the benefit.

### Phase 1: Sidecar metadata (non-invasive)

- Drop `meta.yaml` next to every existing `*.jinja2` (no rename yet).
- Author each meta with current SHA, status=`published`, role/version inferred from filename.
- Add `tests/unit/test_prompt_meta.py` asserting every `*.jinja2` has a sibling `meta.yaml` with matching SHA.
- **Outcome**: drift detection.

### Phase 2: Set manifests (still non-invasive)

- Author `prompts/sets/*.yaml` files reflecting current `PromptConfig` defaults.
- Add `_registry.py` with `load_set()`.
- Add `PromptConfig.from_set("...")` classmethod that resolves a manifest.
- Update `PromptConfig` in `core/config.py` to use `from_set()` for its default.
- Update factory defaults to call `from_set()` rather than hardcoded filenames.
- **Outcome**: named bundles for MLflow + single source of truth for "the production stack".

### Phase 3: Directory restructure (purely cosmetic — defer if low priority)

- Move `synthesizer-v6.jinja2` → `synthesizer/v6.0.0/template.jinja2`.
- Carry `meta.yaml` along.
- Update set manifests to reference `v6.0.0` instead of `v6.jinja2`.
- One-time mechanical refactor; no behaviour change.
- **Outcome**: directory shape matches the conceptual model.

### Phase 4: Validation tests

- Add the parametrized test_prompt_registry.py from above.
- CI runs on every PR touching `autoqa/prompts/`.
- **Outcome**: syntax / drift / missing-required-var bugs caught at PR time.

### Phase 5: Frozen versions + pre-commit hook

- Add the pre-commit hook so SHA stays synced automatically.
- Add a CI rule: if any committed change modifies a `template.jinja2` body
  AND the parent directory ends in a published version (e.g. `v6.0.0/`),
  the PR fails with "bump the version directory; published prompts are
  immutable".
- **Outcome**: published prompts cannot be silently rewritten.

## Status taxonomy

The `status` field on `meta.yaml` and set manifests:

- **draft** — author is iterating; not safe for evaluation runs. Set
  manifests with `status=draft` should not be promoted via Model Registry.
- **published** — body is frozen (immutability rule applies). Safe to evaluate
  against. Multiple published versions can coexist; only one is in production
  at a time.
- **production** (sets only) — currently wired into `PromptConfig` defaults.
  Exactly one set per component should have this status.
- **candidate** (sets only) — A/B-testing against production; pending
  promotion decision.
- **experimental** (sets only) — exploratory; may be deleted without notice.
- **deprecated** — kept on disk for run reproducibility but not for new use.
  Consumers that still reference deprecated prompts should generate a
  warning.

## Verification

After Phase 1+2 land:

```bash
# 1. Every meta is in sync
uv run pytest tests/unit/test_prompt_registry.py -v

# 2. Loader resolves every set
uv run python -c "from autoqa.prompts._registry import load_set, list_sets; \
  [print(s, '->', load_set(s).name) for s in list_sets()]"

# 3. PromptConfig from_set works
uv run python -c "from autoqa.core.config import PromptConfig; \
  print(PromptConfig.from_set('rtm-v6'))"

# 4. Eval harness logs prompt_set_name / sha to MLflow
uv run python scripts/evaluate_with_mlflow.py --component test_suite_reviewer ...
# then check the run in mlflow UI for params.prompt_set_name + params.prompt_*_sha
```

## Pitfalls

- **Don't try to make `PromptConfig` infer the set name from individual
  templates** — too magical and brittle. The set is the user's explicit choice.
- **Don't store templates inside MLflow itself** — repo-as-source-of-truth is
  much easier to PR-review and diff than registry-as-source-of-truth. Use
  MLflow registered models for the set *alias* (production / candidate), not
  the template body.
- **Don't mix manifests with templates** — keep `prompts/sets/*.yaml` separate
  from `prompts/<role>/<version>/*.yaml`. Naming collisions and `glob` confusion
  otherwise.
- **Don't allow `content_sha256` to be edited by humans** — pre-commit hook
  owns that field. If a PR modifies it without changing the body, lint fails.
- **Don't conflate "draft" with "experimental"** — draft means "author is
  iterating, not safe yet"; experimental means "published but flagged as
  exploratory". Distinct.
- **Don't promote-by-editing-defaults** — promotion goes via set-manifest
  status change, code-update sync, and (optionally) MLflow Model Registry
  alias. Auditable; reversible.
- **Whitespace-only edits still count as a body change** — strict
  immutability. SHA changes ⇒ patch bump. Encourages versioning discipline.

## Out of scope

- **Authoring new prompts** — this skill manages existing templates; prompt
  engineering itself (e.g. how to write a good rubric prompt) is a separate
  concern.
- **Cross-language prompt sharing** — the schema assumes Jinja2; if a project
  also has Liquid, Mustache, or raw f-string prompts, additional adapters
  would be needed.
- **Localization / i18n of prompts** — multi-language prompt registries are
  out of scope; treat each language as a separate role (e.g.
  `synthesizer_en` / `synthesizer_es`) if needed.
- **MLflow tracking server / artifact backend setup** — see
  `evaluate-langgraph-mlflow` for the evaluation-side concerns.
