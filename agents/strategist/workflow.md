# Creative Strategist Agent: Workflow

1. Triggered by a marketer clicking "Develop experiment" on a Marketing
   Intelligence finding, or by choosing one directly from Creative Lab's
   own list of experiment-worthy findings.
2. Resolve the Finding by id (`generate_findings`), and confirm it is an
   experiment-worthy type.
3. Pick the primary product and its funnel stage
   (`_select_funnel_stage`: prefers TOF, since a message-hook change is a
   top-of-funnel lever, falling back to MOF then BOF).
4. Choose a control creative for that product and funnel stage
   (`select_control_creative`), and record why it was chosen.
5. Define the one variable being tested (the primary message hook), what
   stays constant (product, funnel stage, CTA, format, proof claim), a
   falsifiable hypothesis, a proposed creative direction, and recommended
   success metrics.
6. Return the `ExperimentProposal` to Creative Lab for human review
   (approve / edit / reject). The Strategist never approves its own
   proposal and never hands off to a Creative Studio Agent directly.
