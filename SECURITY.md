# Security Policy

## Supported Versions

EFTForge is a continuously deployed web app plus a rolling-release desktop app, there
is no maintained set of older versions. Security fixes are only made against the
latest code on `main`.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting:

1. Go to the [Security tab](https://github.com/SouthHorizons76/EFTForge/security)
2. Click **"Report a vulnerability"**
3. Describe the issue, how to reproduce it, and its potential impact

This opens a private advisory visible only to the maintainers until a fix is ready,
so the issue isn't exposed to the public before it's patched.

## Scope

Things we consider in scope: the backend API (`backend/`), the frontend web app
(`frontend/`), and the desktop app (`desktop/`). Third-party dependencies should
generally be reported upstream, though we're happy to hear about a vulnerable
dependency here too so we can prioritize the update.
