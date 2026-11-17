# R10 G1–G4 Device Cache and Engineering Role Validation

## Software validation scope

Offline unit and synthetic end-to-end tests cover exact part/source-card identity, immutable bundles, cached original text reuse, stage-specific coverage, tamper rejection and preparation of G1/G2/G3/G4 evidence packets. The Konnect single-writer migration adds dynamic tool/schema acceptance logic and protected freeze handoff. Workspace and context-budget additions are tested separately.

## Boundaries

These software tests do not authenticate manufacturer PDF originals, certify live commercial Konnect on the user's workstation, prove impedance/return current/EMC/thermal performance, grant engineer approval or replace real KiCad native compatibility and factory CAM checks. A report labeled successful at one stage is not authorization for other projects or versions.

## Deployment checks

Before stable publication, verify native ERC/DRC, schematic netlist and pin/pad mapping, layout/routing/zone-fill saved state, manufacturing file consistency and recovery against a real independent candidate project; retain exact tool versions and input/output hashes. Public packages must not contain customer files or confidential sources. Do not publish an unverified candidate as a stable, manufacturing-approved release.
