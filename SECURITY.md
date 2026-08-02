# Security Policy

GIFManager is a small open-source project maintained on a best-effort basis.
This policy describes which versions receive security updates and how to
report a vulnerability.

## Supported Versions

Only the **latest release** on the [Releases](https://github.com/LwoSnow/GIFManager/releases)
page receives security updates.

| Version | Supported |
| --- | --- |
| Latest (e.g. 1.0.x) | ✅ Security fixes are backported and released promptly |
| Older releases | ❌ Please upgrade to the latest version |

## Reporting a Vulnerability

Please **do not open a public issue** for security problems.

1. Go to the repository's **Security** tab → **Report a vulnerability**
   (GitHub Security Advisory, private by default), or
2. Email us at `[your-email@example.com]` with the subject
   `[GIFManager Security] <short summary>`.

Include as much of the following as possible:

- The affected version(s) and platform (Windows 10 / 11)
- Steps to reproduce the issue
- A description of the impact (what an attacker could do)
- Any proof-of-concept or log files (`logs\*.log`)

You will receive an acknowledgement within **3 business days**.

## Disclosure Policy

- Reported vulnerabilities are handled privately until a fixed version is released.
- We will coordinate a disclosure date with you and credit you in the release
  notes if you wish (unless you prefer to stay anonymous).
- **There is no bug bounty program** — this project is maintained voluntarily.

## Scope

In scope:

- The source code in this repository (`app/`, `main.py`, build & installer configs)
- Security of user data handled by the app (sticker files and the `data/` database)
- Security-relevant build/release processes (GitHub Actions, PyInstaller, installer)

Out of scope:

- Vulnerabilities in third-party dependencies themselves (e.g. PySide6 / Qt) —
  please report those to the respective upstream projects
- Issues caused by running unofficial or tampered binaries — always download
  from the official Releases page or CI artifacts

## Security Best Practices (for users)

- Only download GIFManager from the official Releases page or Actions artifacts.
- Keep a backup of your `data/` folder — it contains all your stickers and settings.
- Run the latest version to receive security fixes.
