<h1 align="center">GitHub for Omarchy</h1>

<p align="center">
  <a href="https://github.com/tcballard/omarchy-badges"><img src="https://raw.githubusercontent.com/tcballard/omarchy-badges/75975e5b5bf75e7ede3764bcd2950046f7abfe2c/badges/v1/omarchy-plugin.svg" alt="Built for Omarchy: Plugin" height="24"></a>
</p>

**Keep up with your repositories from your desktop.**

A native GitHub panel for notifications, issues, pull requests and CI. Read a thread, inspect a diff, check a failing job or write a reply using your existing GitHub CLI login.

## Everyday use

The 0.4.0 workspace also brings repository and star browsing, saved views, durable drafts, release management and native PR conflict resolution. [Workspace guide →](WORKSPACE_GUIDE.md)

Browse the dashboard or search for an issue or pull request. Open its reader for discussion, changes, review threads and checks. Actions such as posting, reviewing or merging have explicit review and confirmation steps. [Keyboard controls →](GUIDE.md#keyboard)

## Install

[Available in the Omarchy Plugin Marketplace](https://plugins.omarchy.org/plugin.html?id=tcballard.github).

Omarchy with the Quickshell plugin API, Python 3, Git 2.38+ for conflict resolution, and GitHub CLI authenticated with `gh auth login --hostname github.com`. Your login needs access to the repositories and notifications you use.

```bash
omarchy plugin add https://github.com/tcballard/omarchy-github-panel.git --enable
```

## Update and remove

Update:

```bash
omarchy plugin update tcballard.github
```

Remove:

```bash
omarchy plugin remove tcballard.github
```

## Marketplace status

The marketplace-listed snapshot is **0.3.1**, commit [`6d84d58`](https://github.com/tcballard/omarchy-github-panel/commit/6d84d58a87f64e8bc8a00a406bd22d99aa30dca9), published on 22 September 2026. Its automated verification applies only to that exact commit and is not a security audit.

The newer **0.4.0 workspace** is not covered by that verification. Normal install and update commands follow the current upstream branch, not the verified snapshot.

## A few useful details

Installation does not add a shortcut. Open the panel with `omarchy-shell shell summon tcballard.github`, or add your own binding.

Dashboard metadata is cached locally; workspace preferences and reply drafts are saved per verified account. Removal keeps local data and your gh login. [Data and removal](GUIDE.md#install-and-update) · [Validation](VALIDATION.md)

Derived from the Omarchy GitHub panel; the original MIT licence is retained.

[Usage and development guide](GUIDE.md) · [Report a bug](https://github.com/tcballard/omarchy-github-panel/issues)

[MIT licensed](LICENSE).

<!-- Preserve links to sections now in the guide. -->
<a id="031--bounded-github-cli-output"></a>
<a id="inline-code-review"></a>
<a id="install-and-update"></a>
<a id="keyboard"></a>
<a id="native-lifecycle-actions"></a>
<a id="search"></a>
<a id="verification"></a>

[Looking for the previous detailed sections? Open the full guide →](GUIDE.md)
