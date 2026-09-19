# Creative Strategist Agent: Tools

- `agents.intelligence.engine.generate_findings` / `experiment_worthy_findings`:
  read the current Findings for a client, scoped to types worth developing
  into an experiment (Emerging Opportunity, Messaging Gap).
- `core.data.load_creative_catalog`, `core.data.load_performance_with_creatives`:
  the only sources for a control creative's identity, copy, and performance.
- `core.analytics.aggregate_performance`: performance rollups used to break
  ties when more than one candidate control creative is otherwise equal.
- `agents.strategist.engine.select_control_creative`: the deterministic
  control-selection rule, scoped to one product and funnel stage at a time.
- `agents.strategist.engine.generate_proposal`: assembles a Finding plus a
  selected control into a structured `ExperimentProposal`.

No LLM call exists yet (see engine.py's module docstring): every proposal
today comes from these deterministic rules over already-computed evidence.
