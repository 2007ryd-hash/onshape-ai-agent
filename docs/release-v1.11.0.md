# v1.11.0 — Live Onshape connection

Windows users can install the local Codex/Claude Code workflow, configure their
own Onshape OAuth application, authorize once, and perform verified read-only
requests through a deterministic Gateway. No LLM provider API key is required.

Included: pinned onshape-mcp 0.5.2, guided configuration/login, live doctor,
bounded document discovery, selected-document readback, immutable run evidence,
and installation rollback. The offline simple-bracket workflow remains available.

Validated against an existing real local OAuth grant: live authentication,
document discovery, and selected-document ID readback. A newly registered
third-party OAuth application was not created during this acceptance run.

This release does not create or modify live CAD, assemblies, mates, or drawings.
Users supply their own OAuth app credentials and consent; configuration and
tokens remain local and are not shipped in this repository.

Acceptance: 286 tests, Ruff, skill/plugin validators, and a clean-archive
installation with a fresh Python environment passed. The installed launcher
passed live doctor from outside the repository; the offline example retained
its explicit simulated repair result.

See [authentication](https://github.com/2007ryd-hash/onshape-ai-agent/blob/v1.11.0/docs/authentication.md)
and the repository README for setup.
