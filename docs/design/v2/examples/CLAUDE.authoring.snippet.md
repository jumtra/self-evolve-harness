<!-- Copy-ready guidance for the existing CLAUDE.md; not a CI-enforced guard. -->
## Skill / Prompt change protocol

- Before creating or editing any Skill, reusable prompt, Agent, Rule, Hook, or CLAUDE.md instruction, first inspect existing code, instructions, Git history, and available CLI/MCP tools in read-only mode. Prefer reusing existing capabilities over adding a new Skill.
- Decide whether the requirement belongs in a short CLAUDE.md convention, a path-scoped Rule, an on-demand Skill, a deterministic Tool, a Subagent, or the workflow runtime. Do not duplicate long instructions across layers.
- Define goal, input/context, boundaries, expected output, and an executable feedback check before authoring. For shared or high-risk behavioral changes, propose a plan and obtain approval before editing.
- For meaningful behavior changes, create positive/negative/edge/regression cases first; test in fresh sessions and compare candidate against baseline. For Skills, check both triggering and outcome, including a run with the Skill disabled when feasible.
- Use the project's tests, schema validator, typecheck, lint, screenshots, or other domain-specific feedback. Repair only failed cases within the configured attempt budget. Never claim tests passed without actual evidence.
- Never broaden tool permissions or edit protected policies without explicit approval. If evaluation cannot run, report BLOCKED_NO_EVAL instead of claiming success.
- When `seh author` is installed, run the authoring gate and provide its run ID. Until CI is configured, these instructions are guidelines rather than guaranteed enforcement.
