# 2026-08-31 Installable Dual-Host V1.1

## What changed

- Added one canonical `onshape-engineering` skill shared by Codex and Claude
  Code.
- Added Engineering, CAD, Drawing, and Visual QA specialist definitions.
- Added Codex and Claude plugin manifests plus repository marketplace files.
- Added Apache-2.0 licensing and aligned package/plugin version `0.2.0`.
- Added a deterministic `doctor --json` command.
- Added the approved `simple-bracket` example and four-view Drawing plan.
- Added Windows installation, runtime launcher, ownership markers, and
  uninstallation.

## Why

The repository needed to become an installable product rather than a
course-specific simulation. Codex or Claude Code now supplies the reasoning,
while the local package supplies repeatable artifacts and execution contracts;
no separate LLM provider API key is needed.

## Development process

Work was isolated on `feature/installable-v1-1`. Mechanical manifest and skill
work was delegated to a Luna Max worker. The main agent reviewed each result;
independent reviews found and corrected fixed-pipeline routing, ambiguous
Markdown output, weak YAML/reference tests, and a repository-unscoped Doctor
import check. Luna capacity was exhausted during the final Doctor quality pass,
so the main agent continued implementation and verification.

## Verification evidence

- Manifest tests observed RED before files existed and GREEN afterward.
- Skill tests observed RED for missing files and later for task-routing defects.
- Doctor tests observed RED before the module existed and for the incorrectly
  scoped package import.
- Example tests observed RED before the command existed.
- Installer tests observed RED before PowerShell scripts existed.
- The installer was exercised against temporary Codex and Claude directories;
  the installed launcher successfully invoked the offline Doctor.
- Uninstallation preserved an unrelated Claude agent file.

## Expected result

A fresh Windows checkout can run `scripts/install.ps1 -HostTarget all`, reload
Codex or Claude Code, and use the same local CAD skill. The bundled example
produces seven auditable JSON artifacts without a network request.

## Current boundary

V1.1 does not modify Onshape. The next product slice is a read-only OAuth
transport followed by a single idempotent, read-back-verified sketch write.
