# Security policy

## Supported versions

Security fixes are made against the latest tagged release and the `main`
branch. Older releases may require upgrading before a fix can be applied.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed secret.
Use the repository's
[private security advisory form](https://github.com/skygazer42/Beacon/security/advisories/new)
and include:

- the affected version or commit;
- a minimal reproduction and expected impact;
- any logs or screenshots with credentials, tokens, faces, and video content
  removed;
- whether the issue is already public.

The project does not currently promise a response SLA. Please allow time for
triage and coordinated disclosure before publishing technical details.

## Deployment responsibility

Beacon processes camera streams, biometric data, and credentials. Operators
must replace every placeholder secret, restrict MediaServer and Analyzer to a
trusted network, enable TLS at the public ingress, and apply the controls in
[`docs/deploy/security-hardening.md`](docs/deploy/security-hardening.md).

