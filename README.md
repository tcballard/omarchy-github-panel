<h1 align="center">GitHub for Omarchy</h1>

<p align="center">
  <a href="https://github.com/tcballard/omarchy-badges"><img src="https://raw.githubusercontent.com/tcballard/omarchy-badges/75975e5b5bf75e7ede3764bcd2950046f7abfe2c/badges/v1/omarchy-plugin.svg" alt="Built for Omarchy: Plugin" height="24"></a>
</p>

**Keep up with your repositories from your desktop.**

A native GitHub panel for notifications, issues, pull requests and CI. Read a thread, inspect a diff, check a failing job or write a reply using your existing GitHub CLI login.

## Everyday use

Browse the dashboard or search for an issue or pull request. Open its reader for discussion, changes, review threads and checks. Actions such as posting, reviewing or merging have explicit review and confirmation steps. [Keyboard controls →](GUIDE.md#keyboard)

## Install

Omarchy with the Quickshell plugin API, Python 3 and GitHub CLI authenticated with `gh auth login --hostname github.com`. Your login needs access to the repositories and notifications you use.

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

## A few useful details

Installation does not add a shortcut. Open the panel with `omarchy-shell shell summon tcballard.github`, or add your own binding.

Dashboard metadata is cached locally; reply drafts last until the shell restarts. Removal keeps the cache and your gh login. [Data and removal](GUIDE.md#install-and-update) · [Validation](VALIDATION.md)

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
