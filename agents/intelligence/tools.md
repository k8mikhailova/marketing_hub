# Intelligence Agent: Tools

As of this milestone, these are real, callable functions (`agents/intelligence/
engine.py`), not conceptual placeholders. What's still a placeholder is the
*reasoning*: a live model call would replace the fixed detector rules below
with judgment, while returning the same structured output.

**Reads (via core/, never a raw CSV directly):**
- `core.analytics.theme_movement`: per-theme signal counts for a period,
  and change vs. the immediately preceding period of equal length.
- `core.analytics.theme_associated_products`: which products customers
  most associate with a theme.
- `core.creative_coverage.creative_coverage`: for a theme and its
  associated products, how many relevant creatives lead with it, mention
  it, or neither.
- `core.analytics.aggregate_performance` (via `agents/intelligence/engine.py`'s
  own funnel-stage-respecting grouping): spend, CTR, CPA, ROAS by message
  style, within one product and funnel stage at a time, never mixed across
  stages.

**Produces:**
- `Finding`: `finding_id`, `type`, `title`, `summary`, `why_it_matters`,
  `confidence` (`low` / `medium` / `high`), `evidence` (a list of
  `Evidence`), `products`, `themes`, `recommended_next_step`,
  `generated_by` (`"preview"` today; a live agent would set `"agent"`).
- `Evidence`: `label`, `detail`, `source` (which dataset and core/
  function), and an optional supporting `table`.

**Not yet implemented:**
- A live model call. `generate_findings()` is deterministic: fixed
  thresholds decide what qualifies as emerging, a gap, saturated, or a
  performance pattern. A future version could replace the detector rules
  with a model call while keeping the exact same `Finding` schema, so nothing
  downstream (the page, evidence rendering) would need to change.
- Writing findings to `insights/<client>/findings.json`. Findings are
  computed on demand for the page today; persisting them (and later,
  promoting one to `approved_learnings.json`) is a future milestone.
