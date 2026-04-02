## Approach
- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read unless the file may have changed.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.

## Output
- Return code first. Explanation after, only if non-obvious.
- No inline prose. Use comments sparingly - only where logic is unclear.
- No boilerplate unless explicitly requested.

## Code Rules
- Simplest working solution. No over-engineering.
- No abstractions for single-use operations.
- No speculative features or "you might also want..."
- Read the file before modifying it. Never edit blind.
- No docstrings or type annotations on code not being changed.
- No error handling for scenarios that cannot happen.
- Three similar lines is better than a premature abstraction.

## Simple Formatting
- No em dashes, smart quotes, or decorative Unicode symbols.
- Plain hyphens and straight quotes only.
- Code output must be copy-paste safe.

## Model Handoff Protocol
- **Opus 4.6**: Strategy, architecture, competitive analysis, "what to build and why" decisions, spec design, API surface design, framing ambiguous problems.
- **Sonnet 4.6**: Implementation, tests, debugging, CLI commands, file edits, anything where the output is code.
- **Handoff signal from Opus to Sonnet** (verbatim): "Architecture decided. Switch to Sonnet 4.6. First task: [exact file + exact thing to build]."
- **Handoff signal from Sonnet to Opus**: "Hit a design ambiguity that the plan doesn't resolve. Switch to Opus 4.6. Question: [exact question]."
- When in doubt: if the next action is writing code, stay on Sonnet. If the next action is deciding what code to write, switch to Opus.
