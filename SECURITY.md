# Security policy

## Reporting

Please report security issues privately through GitHub's security-advisory
interface rather than opening a public issue.

## Deployment boundary

The included dashboard is a localhost research interface. It has no
authentication, authorization, rate limiting, or hardened production server.
Do not expose it directly to the public internet.

The data commands make outbound requests to configured sources and write
append-only snapshots locally. Review source terms and file rights before
importing or sharing any dataset. Licensed tracking and market files, local
SQLite warehouses, raw responses, and generated franchise saves must remain
outside version control.
