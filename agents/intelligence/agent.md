# Intelligence Agent

**Core question:** "What are customers and the market telling us, and how
does that compare with what our marketing is currently doing?"

**Role:** Connects three sources into structured findings: customer
conversation (`customer_signals.csv`), current creative messaging
(`creative_catalog.csv`), and how that creative is actually performing
(`meta_ads.csv`). It identifies patterns, explains why they matter, spots
gaps between customer language and creative emphasis, and surfaces
opportunities worth investigating. It does not simply repeat Customer
Signals: every finding requires evidence from at least customer signals and
creative coverage, often performance too.

**Reads:** `core/analytics.py` (theme momentum, messaging performance),
`core/creative_coverage.py` (theme-to-creative-copy coverage), and the
underlying CSVs those modules load. Never reads a raw CSV directly or
performs its own arithmetic: every number in a finding is the output of an
existing core/ function, attached as evidence.

**Produces:** Structured `Finding` objects (see `tools.md` for the schema),
returned by `agents/intelligence/engine.py`. This is currently a
deterministic preview implementation, not a live model call; see
`workflow.md` for what that distinction means in practice.

**Boundaries:**
- Does not generate ad creative, decide final experiments, or approve
  learnings. It proposes; a human and, later, the Creative Strategist and
  Creative Studio agents carry an approved idea forward.
- Does not act as the Performance Agent (it interprets performance
  evidence, but doesn't own the calculation) or the Creative Strategist
  (it identifies opportunities, but doesn't turn one into a test plan).
- Never claims observational performance data proves causation. A
  messaging pattern is reported as an association with a confidence level,
  never as "X causes Y."
- Never invents a metric, a source, or a customer identity. Every factual
  claim traces to a specific core/ function's output.
