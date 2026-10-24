# Changelog

## 0.1.0a3 — 2026-10-24

- Check existing output and invalid parent paths before loading saved inputs or starting computation across local entry points; preserve previous reports and give a fresh-path retry.
- Retain a complete typed local planned/history record before rendering. After a late I/O failure or interruption, keep it and print a command using the same Python to redraw without training, selection or testing. Preserve the Q table, conditions, known IDs and original execution context. Initial recovery-write failure does not promise a complete copy; temporary web ZIP exports opt out of this local recovery.
- Recover release lookup through the official GraphQL release identity when the REST list omits a draft. Bound post-create/upload retries, validate repository/tag/source, and preserve drafts rather than recreating or replacing assets.
- Ship matching source, natural recovery guidance and checksums. Keep all earlier releases and numerical/history identities unchanged.

## 0.1.0a2 — 2026-10-24

- Explain unsuccessful schedule choices with bounded per-candidate run details: original selection IDs, full-precision RMSE, incomplete/unknown/over-limit outcomes and retained errors. Keep all original files and selection behavior unchanged.
- Check connection saturation against the documented rejection contract: a best-effort 503 or a connection reset, followed by recovery. Separately verify the exact 503 response, cleanup on disconnect and unchanged worker cap; no server behavior or limits change.
- Share computation admission across all six web experiment routes before reading/decoding the body; reject busy requests with retry guidance while retaining normal GET access.
- Bound the default source launcher and CLI server to eight active connection handlers with read timeouts and overload rejection. Preserve numerical source/record identities, localhost/origin validation and existing request/workload limits.
- Document task-based acceptance and local growth limits, and add a small-reproduction issue form without private data. These bounds are not multi-user throughput or real-world effectiveness evidence.

## 0.1.0a1 — 2026-10-24

- First versioned alpha distribution from the independent SparsiLoop repository: curated offline ZIP, wheel, source distribution, public source/CI receipt and SHA-256 checksums.
- Integrate browser recipes, fixed-policy reuse, planned selection/testing and chronological policy history. Preserve failed candidates, original choices, reserved test conditions and used IDs.
- Include local plant adapters, frozen scalar Q-policy workflows, environment records, report redraw and practical first-use/recovery instructions.
- Health checks now report the installed package version. Numerical engine and historical record identities remain unchanged; their `engine_version` is a numerical-format revision, not the package release identifier.
- This alpha does not establish independent adoption, stability certification, hardware effects or general algorithm superiority. PyPI and cloud deployment are not part of this release.
