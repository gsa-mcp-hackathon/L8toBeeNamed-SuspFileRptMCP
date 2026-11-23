# Security Policy

As a U.S. Government agency, the General Services Administration (GSA) takes seriously our responsibility to protect the public's information, including financial and personal information, from unwarranted disclosure.

Software developed by the U.S. General Services Administration (GSA) is subject to the GSA Vulnerability Disclosure Policy.

Please consult our policy for:

How to submit a report if you believe you have discovered a vulnerability.
GSA's coordinated disclosure policy.
Information on how you may conduct security research on GSA developed software and systems.
Important legal and policy guidelines.

## Supported Versions

Use this section to tell people about which versions of your project are
currently being supported with security updates.

| Version (Branch) | Supported          |
| ------- | ------------------ |
| main   | :white_check_mark: |
| other  | :x:

## Security Researchers

Security researchers shall:

- Make every effort to avoid privacy violations, degradation of user experience, disruption to production systems, and destruction or manipulation of data.
- Only use exploits to the extent necessary to confirm a vulnerability. Do not use an exploit to compromise or exfiltrate data, establish command line access and/or persistence, or use the exploit to "pivot" to other systems. Once you've established that a vulnerability exists, or encountered any of the sensitive data outlined above, you must stop your test and notify us immediately.
- Keep confidential any information about discovered vulnerabilities for up to 90 calendar days after you have notified GSA. For details, please review Coordinated Disclosure.

## Hackathon note

MCP servers built from this template expose their `/mcp` endpoint **without authentication** by default (matching the public-data pilot posture). This is acceptable for a hackathon over public data. Before any non-hackathon use, front the endpoint with authentication and review your agency's ATO requirements. Never commit secrets — keep API keys in environment variables / `.env` (git-ignored), not in source.

The starter HTTP helper uses a fixed API origin, rejects absolute or escaping paths,
disables redirects and environment proxies, and sanitizes upstream failures. Do not
replace its relative path with a tool-supplied URL. If a tool must fetch arbitrary
URLs, require exact destination allowlists, connection-time validation of every
resolved IPv4/IPv6 address, validation at every redirect hop, credential stripping
across origins, and network-level egress controls. A DNS lookup followed by a normal
hostname request is vulnerable to DNS rebinding.

Treat all tool arguments, retrieved content, and agent-to-agent messages as
untrusted. Do not include upstream response bodies, headers, full URLs, query
strings, stack traces, credentials, names, SSNs, dates of birth, addresses, or other
sensitive values in MCP errors or logs. Use structured logs with explicitly
allowlisted fields and define retention and access controls before processing PII.

## Transaction data handling

The `.DAT` transaction files processed by this application contain NFC
personnel processing return records and must be treated as sensitive government
data:

- `.DAT` files and the `sample-data/` directory are listed in `.gitignore` and
  must never be committed, archived, printed, or shared without explicit
  approval from the data owner.
- Automated tests generate synthetic fixed-width records in memory or in
  `tmp_path`. They never read operator-supplied `.DAT` files.
- The application strips `SINQ_MESSAGE`, raw 200-character lines, `gwebess_raw`,
  and `powrdocs_raw` before any HTML rendering, MCP tool output, or CSV export.
- The CSV download is capped at 10,000 rows and all string cells are protected
  against Excel formula injection (`=`, `+`, `-`, `@` prefixes are escaped).
- The dashboard and MCP tool are strictly read-only. No write, update, delete,
  or resubmit paths exist in the codebase.
- The reference file (`reference-data/sinq_error_reference.txt`) contains
  approved error descriptions only — no personnel data — and is safe to commit.
