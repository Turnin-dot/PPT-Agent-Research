# Project conventions

- `agent_harness` is the reusable backend runtime. Keep it independent from web frameworks.
- `apps/api` may depend on `agent_harness`; `agent_harness` must never depend on `apps/api`.
- Model-driven control stays in the Harness loop. Do not encode the whole PPT lifecycle as a DAG.
- Put PPT-specific assets, slide plans and export state in `packages/ppt_domain`, not in `core`.
- Treat `agent_old` as read-only migration history. Do not import code from it.
- Keep generated files, sessions and user workspaces outside source packages.
