# Manager Agent: Tools

_Conceptual capabilities this agent will use once orchestration is wired up.
None of this is implemented yet: no LLM calls, no real delegation logic._

- Delegate a task to Intelligence, Performance, Strategist, or Creative Studio
- Read the Agent Activity log
- Check which memory tier (`data/`, `insights/`, `clients/<id>/approved_learnings.json`)
  a piece of information lives in, so it never overstates its confidence
- Flag an item as "awaiting human decision"
