# Optional Freerouting v2.5.0 Adapter (Experimental)

Freerouting is a separately installed external routing program, not a mandatory bundled Skill dependency. The adapter may prepare or validate bounded DSN→SES exchange under explicit tool/version/rule acceptance; it does not guarantee that a router's SES was imported, transformed into real PCB copper, saved and independently validated. The alternative native/script route-planning path is likewise **only a proposal** until the accepted Konnect backend writes actual copper.

Use the adapter only after verifying the selected board's accurate source and factory rules, protected geometry, differential/high-current/high-speed constraints, layer mapping, via allowances and the actual external executable/build. Validate route and mask-rule fidelity on a separate candidate. An unavailable router leaves the design unmodified and requires an explicit alternate accepted execution plan; it cannot silently downgrade to unverified manual or `pcbnew` writes.

For supported command details inspect `scripts/freerouting_adapter.py --help` and [routing contract](constraint-routing.md). Native import/save/reload/DRC, G4 and engineer approval remain independent steps. Failure/partial route/unsupported topology must be declared, never counted as completed routing.

## R10 strict candidate input guards

The v2.5.0 adapter additionally supports `--expected-dsn-sha256`, `--exclude-netclasses`, `--rules-file` and `--expected-rules-sha256`. With `--apply`, reviewed DSN SHA and nonempty protected NetClass exclusions are required. The adapter blocks a silently autodiscovered adjacent `<board>.rules` unless explicitly selected, and blocks rules hash drift. Exclusions use the official `-inc` **NetClass** mechanism, not raw net names; declared DSN class-name presence alone cannot prove protected net membership. Actual KiCad NetClass assignments must be independently verified. Review [Freerouting-primary routing contract](freerouting-primary-routing.md) before invoking this path; the old preview and manual fallback do not confer G4 acceptance.
