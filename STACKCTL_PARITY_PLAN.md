# Stackctl Parity Plan via Lifecycle Hooks

This project will add stackctl-parity capabilities through a lifecycle hook plugin framework.

## Goals

- Keep compose-farm core generic and portable.
- Make lab-specific behavior pluggable.
- Preserve backward compatibility when no plugins are enabled.

## Core Direction

1. Add lifecycle hook events in compose-farm operations.
2. Add plugin discovery via Python entry points (`compose_farm.plugins`).
3. Support per-hook failure policy:
   - `blocking`: fail the lifecycle operation.
   - `warn`: log and continue.
4. Pass rich migration metadata to hooks.

## First Milestone (Implemented)

- Plugin type system (`HookEvent`, `HookContext`, `HookPolicy`, `HookRegistration`, `HookResult`).
- `HookManager` with entry point discovery and dispatch.
- Migration lifecycle hook dispatch points in core operations.
- Config fields for plugin enablement and plugin-specific config.

## Planned Hook-Driven Plugins

1. Compose Sync Plugin
- Trigger on pre-up/pre-apply.
- Sync compose stack files to target hosts.
- Support dry-run and excludes.

2. Secret Render Plugin
- Trigger on pre-up.
- Render/decrypt secrets into runtime paths with strict permissions.

3. Lab Data Migration Plugin
- Trigger on migration checkpoints.
- Perform host-local persistent data copy and verification.
- Keep this optional and lab-specific.

## Non-Goals

- Hardcoding NixOS-only behavior into compose-farm core.
- Building a full scheduler or HA control plane.
