# v1.11.1 — Connection and installation fixes

Six fixes identified in the v1.11.0 code review:

- Partial Codex/Claude uninstall preserves the remaining host's shared state
  and runtime.
- OAuth configuration and presence checks honor absolute XDG path overrides.
- Repeated numeric coordinates no longer look like cyclic geometry responses.
- MCP `isError` results cannot be reported as successful reads.
- Pinned upstream HTTP 401/403/404/429 failures retain their stable error codes
  without exposing response bodies.
- UNKNOWN and NEEDS_CONFIRMATION dimensions are blocked, including nested
  parameters; unapproved assumptions remain blocked.

This is a patch to the read-only live connection. It does not enable live CAD,
assembly, mate, or drawing writes. Existing OAuth configuration is reused.

Acceptance includes a clean-archive install into a fresh Python environment.
After partial Codex uninstall with `-RemoveRuntime`, the remaining Claude
launcher still passed live Onshape doctor. A nonexistent-document request
returned `NOT_FOUND`, with no verified readback. No live model writes occurred.

Final verification: 311 tests passed (25 more than v1.11.0), Ruff passed,
and skill/plugin validators passed. Regressions were reproduced before fixes.
