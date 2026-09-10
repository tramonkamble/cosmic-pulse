# Security

Cosmic Pulse is a **local** dashboard. It is not a multi-user service.

## Bind address

- Default: `127.0.0.1:8765` (this machine only).
- `--lan` / `PULSE_LAN=1` listens on all interfaces **with no authentication**.
  Use that only on a trusted home LAN (second monitor or phone). Do **not**
  port-forward 8765 to the internet.

## What Pulse will not do

- It does not run `sudo` for you. Root/fix steps are copy-paste commands.
- One-click Fix actions are limited to user-owned files (e.g. Steam launch options).
- It does not phone home. No accounts, no telemetry.

## Reporting a vulnerability

Open a private report via GitHub Security Advisories on
[tramonkamble/cosmic-pulse](https://github.com/tramonkamble/cosmic-pulse),
or an issue if the finding is already public (e.g. “LAN bind has no auth” —
that is documented, not a surprise).
