# Project Log

Sanitized development milestones are recorded under `docs/project-log/`. Runtime execution history is stored under ignored `runs/<run_id>/events.jsonl` files.

| Date | Milestone | Result |
|---|---|---|
| 2026-08-31 | Generic V1 foundation | Contracts, closed-loop routing, deny-by-default Gateway, immutable artifacts, logging, and safe CLI demo implemented and tested. |
| 2026-08-31 | Installable dual-host V1.1 | Shared Codex/Claude skill, specialist agents, offline doctor, simple-bracket result, Windows installer, and Apache-2.0 distribution implemented. |
| 2026-09-05 | V1.11.0 read-only live connection work | Added pinned onshape-mcp OAuth setup/login scripts, explicit live diagnostics and bounded document-read CLI paths. Windows setup and authentication documentation checked against source. Real-account acceptance and publication are not established by this entry; the bracket example remains offline and simulated. |
| 2026-09-05 | Real-account smoke verification | Existing local OAuth validated with READY_LIVE; bounded document discovery returned one item; selected-document readback confirmed matching ID. No Onshape mutations were sent. |
| 2026-09-05 | Real MCP installer verification | Temporary Codex/Claude installation with the actual pinned npm package succeeded. Fixed version parsing to accept the real `onshape-mcp 0.5.2` output. |
| 2026-09-05 | Release acceptance | 286 tests passed; Ruff and skill/plugin validators passed. A clean Git archive installed into a fresh virtual environment and temporary host directories; its installed launcher passed READY_LIVE from outside the repository. Offline simple-bracket remained simulated and routed repair. Live calls now pass through CadGateway and persist hashed run reports. |
| 2026-09-05 | v1.11.1 review fixes | Added regression-first fixes for partial-host uninstall, absolute XDG storage paths, repeated scalar geometry values, MCP isError and HTTP status handling, and unresolved nested dimensions. Existing user project memory/archive preserved. Real read-only doctor returned READY_LIVE; a deliberately nonexistent document returned NOT_FOUND with readback_verified=false. |
