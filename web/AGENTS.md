# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## SmartPump design decisions

- Use `docs/design/smartpump-dashboard-selected.png` as the visual source of truth.
- Keep pump start/stop, signed flow, rotation direction, and valve channels together in the operational view.
- Render recipe loops as compact hierarchical groups. Expand only the active loop and never duplicate every iteration in the main timeline. Size the inner-step grid from the actual number of children; use horizontal overflow only for long loops or narrow screens instead of an arbitrary fixed column count.
- Put operational help in the header; do not use a floating help button.
- Red is reserved for stopping or destructive actions, violet for loop hierarchy, teal/blue for active state, and green for confirmed healthy state.
- Manual controls must visibly explain why they are disabled while a recipe is active.
- Recipe editing must expose working forms for steps and loops, including nested additions. Editing the library never mutates the immutable snapshot of an active run.
- A selected recipe must expose a clear start action. Starting requires a confirmation that shows revision, cycles, duration, and pump mode; if the controlled pump is stopped, ask whether it should start. Never replace an active run implicitly.
