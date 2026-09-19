# Intelligence Agent: Workflow

1. Triggered today by loading the Marketing Intelligence page (later, also
   by Manager, or a scheduled scan).
2. Build a shared evidence base for every customer-signal theme: signal
   momentum, associated products, and creative coverage
   (`agents/intelligence/engine.py`'s `_theme_evidence_base`), so every
   detector below reasons from the same numbers.
3. Run each detector against that shared base and the joined performance
   data: emerging opportunity, messaging gap, saturated theme, performance
   pattern. Each either returns a finding that clears its evidence bar or
   returns nothing; none is forced to fire.
4. Rank candidates by confidence, then by how much evidence backs them, and
   keep the page's Intelligence Brief diverse (skip a candidate whose type
   and product are already represented) rather than repetitive.
5. Return structured `Finding` objects for the page to render. The page
   renders exactly what's here: no hidden reasoning, no chain-of-thought.

Never writes to `insights/<client>/findings.json` or
`approved_learnings.json` yet: findings are computed fresh each time, not
persisted. When persistence is added, only a human review step promotes a
finding into approved memory, same as every other agent in this project.
