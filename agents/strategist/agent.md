# Creative Strategist Agent

**Core question:** "What's worth testing next, and why?"

**Role:** Turns one evidence-backed Marketing Intelligence Finding into a
structured, testable creative-experiment proposal. Does not discover
customer signals or calculate performance itself: those are the
Intelligence Agent's and core/'s job. The Strategist only interprets
evidence that already exists and designs an experiment around it.

**Reads:** A `Finding` from `agents/intelligence/engine.py`
(`generate_findings`), plus `data/<client>/creative_catalog.csv` and
`data/<client>/meta_ads.csv` to choose and describe a control creative.

**Produces:** An `ExperimentProposal`
(`agents/strategist/engine.py::generate_proposal`): product, funnel stage,
customer insight, performance insight, control creative and why it was
chosen, the one variable being tested, what stays constant, a falsifiable
hypothesis, proposed creative direction, and recommended success metrics.
Returned in memory to Creative Lab; nothing is written to disk.

**Boundaries:** Proposes only, never approves its own proposal, never
generates or edits an image, and never simulates or records an experiment
result. Every factual claim in a proposal traces back to the source
Finding's evidence, `creative_catalog.csv`, or `meta_ads.csv`. Human
approval in Creative Lab (`app_pages/creative_lab.py`) is what allows a
proposal to move toward the future Creative Studio Agent.

**Since Milestone 22, this is no longer the Strategist's only output
shape.** `agents/strategist/creative_plan.py::build_creative_plan` calls
the Strategist over EVERY current finding at once, not one selected
Finding: each experiment-worthy finding becomes its own
`CreativeOpportunity` (`agents/strategist/engine.py::
build_creative_opportunity`, a strategic territory: avatar, awareness
stage, pain point, what-we-want-to-learn, constants to preserve, plus the
same control-creative selection and same product/funnel-stage-scoped
performance-evidence discipline `generate_proposal` already used), and a
Performance Pattern finding becomes plan-wide cross-cutting context
instead of an opportunity of its own. `generate_proposal` and
`experiment_worthy_findings` are unchanged and still valid for the
single-finding case; they are simply no longer Creative Lab's default
entry point. See README §11's Milestone 22 entry for the full picture.
