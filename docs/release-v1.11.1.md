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
