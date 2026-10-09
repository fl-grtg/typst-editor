# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's **Private Vulnerability Reporting** (repository → *Security* → *Report a vulnerability*).
Include what you found, how to reproduce it, the version/commit, and the impact you expect.

What you can expect:

- An acknowledgement within **7 days**.
- A first assessment (confirmed / needs info / not a vulnerability) within **14 days**.
- A fix or mitigation plan as soon as practical; please allow reasonable time before public disclosure.
- Credit in the release notes if you want it.

## Supported versions

Until 1.0, only the latest release (and `main`) receives security fixes.

## Scope

In scope: the backend (`backend/`), the single-file frontend (`index.html`, built from `web/`),
the Docker image and compose files, and the backup script.

Out of scope: vulnerabilities in third-party dependencies that are not exploitable through this project
(report them upstream), social engineering, and issues that require a misconfigured reverse proxy
(see the *Reverse proxy* section of the README for the supported setup).

## Hardening notes for operators

- Never expose the app directly; terminate TLS in a reverse proxy and set `TRUST_PROXY=true` only behind one.
- Keep `REGISTRATION=invite-only` (default) unless you run a closed network.
- Back up `DATA_DIR` regularly (`scripts/backup.py`) and test restoring it.
