<!-- Guidance for AGY/Codex/OpenCode. Generated from .harness/spec; not a substitute for CI -->
## Skill / Prompt modification policy
- Inspect existing repo instructions, skills, tools, MCP, and history before adding new skills or modifying reusable prompts.
- Prefer reuse or a deterministic script over another overlapping skill.
- Define the task goal, expected inputs and outputs, constraints, permissions, feedback tests, and non-trigger examples before writing.
- Apply the same Explore > Plan > Baseline > Implement > Verify > Compare > Promote process required by `seh author`.
- Evaluate trigger and outcome separately in a fresh host session; do not claim success from a different host's test run.
- Never change shared policies or tool permissions without explicit approval. If evidence is missing, report BLOCKED_NO_EVAL.
- The final safety authority is the repository's `seh author` CI required check, not this Markdown file.
