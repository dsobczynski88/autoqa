---
name: parallelize-async-pytest
description: |
  Refactor an existing pytest test suite that uses `async def` test functions but
  still runs sequentially into one that genuinely executes test cases in parallel,
  cutting wall-clock time on I/O-bound suites (LLM/API/HTTP/DB integration tests).
  Diagnoses why `async def` alone doesn't yield parallelism (each test still awaits
  in isolation), then applies one of two patterns: (A) **asyncio.gather fan-out** —
  collapse a parametrized test into a single async test that gathers per-row
  coroutines, sharing one in-process rate-limited client — recommended for
  LLM/API-bound work; (B) **pytest-xdist** — multi-process worker pool, recommended
  for CPU-bound or hermetic tests. Covers concurrency bounds (semaphore sizing
  vs RPM/TPM ceilings), session-fixture compatibility, ordered result recording
  via index, partial-failure handling, and pytest reporting trade-offs. Use when
  the user reports "my pytest runs are slow despite using async", "tests are
  sequential", "how do I parallelize integration tests", "run pytest faster",
  or references long integration runs (>5 min) where most time is spent on
  outbound network calls.
---

# parallelize-async-pytest

Refactor `pytest` integration tests that already use `async def` but execute one
at a time into suites that fan out work concurrently and reclaim wall-clock time.
Targeted at I/O-bound suites — the autoqa pipeline tests are the canonical
example: 23 parametrized cases × ~15 LLM calls each ran in 12 minutes
sequentially when 5 minutes was achievable with proper concurrency.

## Mission

Diagnose why an `async def` pytest test suite is still sequential, choose the
right parallelism pattern for the workload, refactor the tests + fixtures
accordingly, and verify the speedup empirically.

## When to invoke

- A user says "my pytest tests are slow even though I'm using async / await".
- A user says "tests run one at a time", "tests are sequential", or asks
  about pytest parallelism / concurrency.
- A user asks "how do I run integration tests in parallel" or
  "how do I make pytest faster on LLM tests".
- A user references a long pytest run (>5 min) where wall-clock time
  dominated by outbound network/LLM calls.
- A repo has `pytest-asyncio` configured but no `pytest-xdist` and no
  `asyncio.gather` fan-out anywhere.

If the slowness is CPU-bound (numpy, parsing, regex) — `asyncio.gather` won't
help; jump straight to Approach B (pytest-xdist).

## Diagnosis (do this first)

Confirm the diagnosis before refactoring. Three checks:

1. **Are tests actually sequential?** Run with `pytest -v --durations=0` and
   look at total wall-clock time vs sum of per-test durations. If they're
   approximately equal, tests are sequential.
2. **Where is time being spent?** A pytest test that awaits one slow LLM call
   is correctly async — but if you have N parametrized tests and each awaits
   one slow call, pytest still runs them one after the other. The async/await
   inside a test is intra-test concurrency; pytest provides zero inter-test
   concurrency by default.
3. **Is the client rate-limited?** Inspect the HTTP client. If it has a
   global semaphore / token bucket / RPM ceiling (e.g. autoqa's
   `RateLimitOpenAIClient`), Approach A is safe and preferred. If the client
   is naive, you must add concurrency control during the refactor.

State the diagnosis to the user explicitly before proposing a fix:
> "Your tests use `async def` correctly, but pytest-asyncio runs tests one
> at a time. The wall-clock equals the sum of per-test runtimes — you're
> not getting concurrency. Recommended fix: ..."

## Two approaches — pick one

| | Approach A: `asyncio.gather` fan-out | Approach B: `pytest-xdist` |
|---|---|---|
| Best for | I/O-bound (LLM, HTTP, DB) | CPU-bound or fully hermetic |
| Process model | Single process, single event loop | N worker processes |
| Setup cost | None (stdlib) | New dep (`pytest-xdist`), `-n auto` flag |
| Shared state | Trivial (just module globals / closures) | Hard — each worker is a fresh interpreter |
| Rate-limited client | Shares one instance — easy | Each worker creates its own — must coordinate or accept N×rate |
| Per-row pytest report | Lost — one test, internal fan-out | Preserved — each row is a real test |
| Stdout/log interleave | Clean | Interleaved across workers (use `-s` carefully) |
| Session fixtures | Work normally | Re-run per worker (problematic for `jsonl_recorders`-style global state) |
| Failure isolation | One row fails ≠ test fail unless you choose so | Each row fails independently |

**Default recommendation for LLM-test suites: Approach A.** Process startup
overhead, fixture re-entry, and shared-rate-limiter complications make xdist
the wrong tool when a single in-process semaphore can deliver the same
speedup with no infrastructure changes.

## Approach A — `asyncio.gather` fan-out

### Pattern

Replace `@pytest.mark.parametrize(... ids=[...])` with a **single** async test
that gathers per-row coroutines internally:

```python
import asyncio
import pytest

INPUTS = load_jsonl("gold_dataset.jsonl")  # N rows

# Tunable: how many rows can be in-flight at once. Bound by:
# - upstream RPM/TPM ceilings (RateLimitOpenAIClient handles this internally,
#   so semaphore is a soft cap, not a hard rate gate)
# - memory headroom (each in-flight graph holds full state)
# - reasonable diagnostic readability when failures occur
MAX_CONCURRENT = 8


async def _run_one(real_client, real_model, row, record_input, record_output):
    """Single-row body — exactly what each parametrized test used to do."""
    record_input(row)
    requirement = Requirement(**row["requirement"])
    test_cases = [TestCase(**tc) for tc in row["test_cases"]]
    graph = RTMReviewerRunnable(client=real_client, model=real_model)
    result = await graph.graph.ainvoke(
        {"requirement": requirement, "test_cases": test_cases}
    )
    record_output(serialize_state(result))
    return row["requirement"]["req_id"], result


@pytest.mark.integration
async def test_pipeline_fanout(real_client, real_model, jsonl_recorders):
    """All N rows run concurrently (capped at MAX_CONCURRENT) inside one test."""
    record_input, record_output = jsonl_recorders
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def gated(row):
        async with sem:
            return await _run_one(real_client, real_model, row, record_input, record_output)

    results = await asyncio.gather(
        *(gated(row) for row in INPUTS),
        return_exceptions=True,  # one row's failure does not cancel the others
    )

    # Per-row assertion sweep AFTER all rows complete — accumulate, don't fail
    # on the first row.
    failures = []
    for row, result in zip(INPUTS, results):
        if isinstance(result, Exception):
            failures.append((row["requirement"]["req_id"], repr(result)))
            continue
        req_id, state = result
        try:
            assert isinstance(state.get("synthesized_assessment"), SynthesizedAssessment)
            _assert_partial_invariants(state["synthesized_assessment"])
        except AssertionError as e:
            failures.append((req_id, str(e)))

    if failures:
        msg = "\n".join(f"  {req_id}: {err}" for req_id, err in failures)
        pytest.fail(f"{len(failures)}/{len(INPUTS)} rows failed:\n{msg}")
```

### Key points

- **One test, internal fan-out** — pytest no longer reports each row, but the
  failure-message includes per-row failures with their req_id, so debuggability
  is preserved.
- **`asyncio.Semaphore` caps in-flight work** — sized to the rate-limit
  ceiling (or below). For autoqa's `RateLimitOpenAIClient` (490 RPM, 200K
  TPM), a semaphore of 8 leaves headroom for the per-graph fan-out (~10-20
  LLM calls per row × 8 in-flight rows = 80-160 concurrent calls hitting
  the limiter, which queues them).
- **`return_exceptions=True`** — one row failing does not cancel siblings;
  every row gets a chance to run, and the test surfaces all failures at once.
- **Result-ordering preserved** — `zip(INPUTS, results)` re-aligns outputs to
  inputs by index, so post-run analysis is straightforward.
- **`jsonl_recorders` works unchanged** — the session-scoped fixture's
  recorders are called concurrently, but each `record_input` / `record_output`
  appends an atomic line. The order of lines in `outputs.jsonl` will reflect
  *completion order*, not input order — if input/output line-N alignment
  matters, switch to indexed writes (see "Pitfalls" below).

### Tuning `MAX_CONCURRENT`

Start at 8 and bisect. The right value depends on:

- **Upstream rate limits** — if your client has no internal limiter, set
  MAX_CONCURRENT = floor(RPM / per_row_request_count). E.g. 200 RPM ceiling /
  20 calls per row = 10 max concurrent rows.
- **Memory** — each in-flight LangGraph holds intermediate state. 50+ rows
  in flight on a 16GB box is risky; cap by available RAM.
- **Tail-latency** — high concurrency saturates the upstream and worsens p99
  latency. Sweet spot is usually 4-12 for LLM workloads.

A reasonable default for LLM integration tests: **`MAX_CONCURRENT = 8`**.

## Approach B — `pytest-xdist`

When tests are CPU-bound, hermetic, and you want to keep per-row pytest
reporting:

```bash
uv add --dev pytest-xdist
```

```bash
uv run pytest tests/integration -n auto -m integration -v
# -n auto picks worker count = #CPUs
# -n 4 forces exactly 4 workers
# --dist=loadscope groups parametrized tests onto the same worker
```

### Caveats

- **Session fixtures re-enter per worker** — `jsonl_recorders` writes one
  inputs.jsonl / outputs.jsonl per worker if the path doesn't account for
  worker id. Either:
  - Make the fixture worker-aware: read `os.environ["PYTEST_XDIST_WORKER"]`
    and partition output paths.
  - Or run xdist with `--dist=no` (defeats the purpose) or make the writes
    process-safe via file locks.
- **Each worker creates its own client** — N workers × N internal rate
  limiters = N× upstream pressure. Either centralize the limiter (Redis-backed,
  shared file lock) or set `MAX_CONCURRENT_PER_WORKER = ceiling / N`.
- **Stdout interleaves** — `-s` makes this messy; rely on per-test logs or
  `pytest --log-cli-level=INFO` instead.
- **Faster startup but more memory** — N processes each import the project,
  which for autoqa's LangGraph imports can be 200-400 MB per worker.

Use xdist when: tests are CPU-heavy (e.g., regex-bound parsing, ML
inference), the fixture model is already process-safe, and you specifically
want per-row pytest reporting in a CI dashboard.

## Rate-limiting and concurrency control

Whichever approach is chosen, audit the HTTP client:

```python
# Read the client's source. Look for these markers:
#   - asyncio.Lock / asyncio.Semaphore           → safe for in-process concurrency
#   - rolling-window or token-bucket throttle    → safe; queues over-limit calls
#   - bare httpx.AsyncClient with no limiter     → MUST add semaphore in test
#   - retry-on-RateLimitError with backoff       → safe but watch tail latency
```

For autoqa specifically: `autoqa/components/clients.py::RateLimitOpenAIClient`
has both an `OpenAIRateLimiter` (RPM ceiling with rolling 60s window) and
exponential-backoff retry on `RateLimitError`. **Approach A's semaphore is a
soft cap on top of the client's hard rate limit — both must be set.**

## Result recording in parallel

If your fixture appends to a single jsonl in completion-order, downstream
audits that assume "line N input ↔ line N output" will break. Two fixes:

### Option 1 — write indexed, sort post-hoc

```python
async def _run_one(idx, row, ...):
    ...
    record_output({"_idx": idx, **serialize_state(result)})

# After the run:
records = [json.loads(l) for l in outputs.jsonl ...]
records.sort(key=lambda r: r["_idx"])
```

### Option 2 — collect in memory, write at end

```python
async def test_fanout(...):
    results = await asyncio.gather(*[_run_one(i, row) for i, row in enumerate(INPUTS)])
    # Now write in input order
    for i, (row, result) in enumerate(zip(INPUTS, results)):
        record_input(row)
        record_output(serialize_state(result))
```

Option 2 is cleaner when the dataset fits in memory.

## Reference template (autoqa-flavour)

For a project that follows autoqa's layout (parametrized integration tests
loading `gold_dataset.jsonl`, `jsonl_recorders` session fixture, pre-built
LangGraph runnable):

```python
# tests/integration/test_pipeline_fanout.py
import asyncio
import pytest
from autoqa.components.test_suite_reviewer.pipeline import RTMReviewerRunnable
from autoqa.components.test_suite_reviewer.core import (
    Requirement, TestCase, SynthesizedAssessment,
)
from tests.helpers import load_jsonl, serialize_state

INPUTS = load_jsonl("gold_dataset.jsonl")
MAX_CONCURRENT = 8


@pytest.mark.integration
async def test_pipeline_parametrized_fanout(real_client, real_model, jsonl_recorders):
    record_input, record_output = jsonl_recorders
    graph = RTMReviewerRunnable(client=real_client, model=real_model)  # SHARED
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def run_one(idx, row):
        async with sem:
            requirement = Requirement(**row["requirement"])
            test_cases = [TestCase(**tc) for tc in row["test_cases"]]
            return idx, row, await graph.graph.ainvoke(
                {"requirement": requirement, "test_cases": test_cases}
            )

    completed = await asyncio.gather(
        *(run_one(i, row) for i, row in enumerate(INPUTS)),
        return_exceptions=True,
    )

    # Re-order to input order, write deterministically
    completed_sorted = sorted(
        [c for c in completed if not isinstance(c, Exception)],
        key=lambda c: c[0],
    )
    failures = [c for c in completed if isinstance(c, Exception)]

    for idx, row, result in completed_sorted:
        record_input(row)
        record_output(serialize_state(result))

    # Per-row invariants — accumulate, then summary-fail
    fail_msgs = []
    for idx, row, result in completed_sorted:
        try:
            assert isinstance(result.get("synthesized_assessment"), SynthesizedAssessment)
        except AssertionError as e:
            fail_msgs.append(f"{row['requirement']['req_id']}: {e}")
    if failures or fail_msgs:
        pytest.fail(
            f"exceptions={len(failures)}; assertion-failures={len(fail_msgs)}\n"
            + "\n".join(fail_msgs)
            + ("\nexceptions:\n" + "\n".join(repr(e) for e in failures) if failures else "")
        )
```

Build the runnable ONCE outside the gather (graph compilation is non-trivial),
then dispatch ainvoke calls in parallel.

## Verification — measure the speedup

1. **Baseline**: capture sequential wall-clock with the current parametrized
   form. `time uv run pytest tests/integration/test_pipeline.py -m integration -s`.
2. **After refactor**: same command pointed at the new fan-out test.
3. **Compute speedup**: parallel_time / sequential_time. Expect 3-6× for
   LLM I/O-bound suites at MAX_CONCURRENT=8. If speedup is <2×, the upstream
   is the bottleneck (rate limiter is queuing) — increase the limiter or
   accept the ceiling.
4. **Per-row correctness check**: diff `outputs.jsonl` line-counts and
   record-by-record content between sequential and parallel runs. Same record
   IDs should appear with equivalent payloads (LLM nondeterminism aside).

## Pitfalls

- **Single-graph compilation cost** — building an `RTMReviewerRunnable` per
  row is wasteful. Build once outside the gather, share across all rows.
- **Fixture scoping** — module-scoped fixtures are created N times under
  pytest-xdist (per worker), once under pytest-asyncio gather. Check that
  `real_client` is appropriately scoped (session is best for clients).
- **Stdout floods** — fan-out tests emit all per-row prints concurrently;
  prefer structured logs over print, or write per-row diagnostics to the
  output jsonl rather than stdout.
- **Test-id grain loss** — pytest reports one "test" instead of N. Mitigate
  by emitting a per-row table at end-of-test, or by keeping a parametrized
  smoke test alongside (one row, runs sequentially) for fast CI feedback.
- **Cache miss on first run** — if `MAX_CONCURRENT` exceeds upstream
  capacity, the rate limiter queues calls and tail latency dominates. Bisect
  downward.
- **`asyncio.gather` cancellation semantics** — without `return_exceptions=True`,
  one row's exception cancels the rest. Always set it for test fan-outs.
- **Fan-out + xdist together** — possible but rarely worth it. xdist's
  per-worker semaphores don't coordinate, so the soft cap becomes
  N_workers × MAX_CONCURRENT — easy to overrun upstream limits.

## Out of scope

- Refactoring synchronous tests to async — the skill assumes `async def`
  is already in place.
- Changing the application code itself (graph compilation, client
  configuration). Rate-limiter tuning is downstream of this skill.
- CI config (matrix sharding, runner parallelism) — those operate at a
  layer above pytest.
