# Native GitHub panel

Local user-plugin version of tcballard/omarchy PR #2, with an internal thread reader, PR review/diff/check tabs, CI job/log views, replies, and explicit notification marking through the existing `gh` login. Installed at `~/.config/omarchy/plugins/tcballard.github/`. Super+Alt+I opens the panel.

## Install and update

Requires Omarchy with the Quickshell plugin API, Python 3, and GitHub CLI authenticated with `gh auth login --hostname github.com`. Your token must have access to the repositories and actions you use; inbox notifications additionally need notification access.

Install from this repository on a new machine:

```bash
omarchy plugin add https://github.com/tcballard/omarchy-github-panel.git --enable
omarchy-shell shell summon tcballard.github
```

The repository is public. For a git-managed installation, update with `omarchy plugin update tcballard.github`. Installation does not create or replace keyboard shortcuts; this machine’s existing Super+Alt+I binding is retained.

Remove the plugin with:

```bash
omarchy plugin remove tcballard.github
```

Remove any shortcut you added separately. Removal leaves your GitHub CLI login and the dashboard cache at `$XDG_STATE_HOME/omarchy/github/dashboard.json` (normally `~/.local/state/omarchy/github/dashboard.json`) intact. Delete that cache separately if you no longer want its stored repository and notification metadata.

The panel launches bundled Python helpers, which invoke `gh` to access GitHub's API using your existing authentication. Dashboard refreshes run periodically while loaded; reader requests, searches, and confirmed management actions run on demand. The dashboard cache is written locally; reply drafts stay in memory until the shell restarts. Installation does not replace user configuration or create keyboard bindings. GitHub changes use your account permissions and require explicit UI actions and the documented confirmations.

The manifest keeps the original `tcballard.github` ID so existing configurations continue to work. Derived from the GitHub panel in [tcballard/omarchy PR #2](https://github.com/tcballard/omarchy/pull/2); the original Omarchy MIT license is included.

Build a portable archive and SHA-256 checksum with `python3 scripts/package.py`. Archives contain only runtime files, the manifest, README and license; they exclude tests, caches and account data. Extract the plugin folder into `~/.config/omarchy/plugins/` on a machine without an existing installation of this ID, then run `omarchy plugin enable tcballard.github`.

## Keyboard

In the dashboard:

- Up/Down (K/J): choose a section when the section rail is focused. 1–6 jumps straight to a section’s items.
- Tab/Shift+Tab: switch between the section rail and item list; the border marks the active area.
- Up/Down (K/J): select a section or item in the active area.
- Enter/Right (L): enter the item list from the section rail, or read the selected item. Left/Backspace (H) returns to the section rail; at the top level it closes the panel.
- Home/End and PageUp/PageDown: navigate the item list.
- /, F or Search: open GitHub search. Enter submits; Down enters results; P loads another page. Search results use the same reader and action menu.
- N or New issue: create an issue in any repository you can access; the selected item’s repository is prefilled.
- R: refresh. Escape: close the panel.

In the reader:

- [ / ], Ctrl+Tab/Ctrl+Shift+Tab, or 1–9: switch detail tabs.
- Up/Down (K/J): select workflow/job entries when present; otherwise scroll. Enter/Right opens the selected entry. PageUp/PageDown and Home/End scroll the thread, diff, or log.
- Tab/Shift+Tab: move among visible, enabled controls inside the reader. Focus has an accent border; buttons inside long content scroll into view.
- Enter/Space: activate the focused button.
- A or Actions: open the item’s action menu. Up/Down selects; Enter/Right opens; Left/Backspace returns. Text fields retain their normal editing keys; Tab moves between fields and controls. Escape returns from a form.
- C: compose a reply. R: refresh. Left/Backspace/Escape: previous view.

In a reply:

- Letters, arrows, shortcuts for editing, and Enter edit the text; Enter inserts a newline.
- Tab/Shift+Tab move between the editor and controls.
- Escape keeps the draft and returns to reading. Another Escape returns to the list.
- Posting requires explicitly activating Post reply. Drafts are retained per item while this plugin instance remains loaded; they do not survive a shell restart.

## Verification

Run `tests/run` for the portable backend checks and archive build. Run `tests/keyboard` separately on a machine with Qt Quick Test installed for the keyboard and confirmation tests.

`tests/keyboard` runs real Qt key/focus tests against Reader.qml. It substitutes only the Quickshell process wrapper and theme singletons because those plugins are linked into the Quickshell executable. All controls and event handling are real Qt Quick; no subprocesses or GitHub actions run.

`python3 -m unittest discover -s tests -v` runs the helper tests. `python3 tests/live_reader.py` optionally reads real GitHub data through your existing login, without mutating anything.

The native reader deliberately renders remote text as selectable plain text. Some large review/file/log responses are capped with an explicit message. CI notifications without a run ID show recent repository runs and explain that limitation. PRs have Approve, Request changes, and Merge dialogs. Each shows the repository, number, source and target branch, commit, and current readiness. Reviews accept an optional approval note or required change-request note. Merging offers only repository-enabled methods. The backend rechecks head SHA, target branch, state, and account permissions before submitting; merge requests also carry GitHub's SHA precondition. Direct merges respect GitHub rules. The Actions menu additionally supports enabling/disabling auto-merge and joining/leaving a merge queue, with separate explicit confirmation. It never bypasses queue ordering, uses admin merge overrides, or deletes the source branch.

PR writes are tested with a fake transport; the Qt confirmation tests only emit captured requests. No live approvals or merges are performed by tests.

## Native lifecycle actions

- PRs: approve, request changes, merge, request user/team reviewers, mark drafts ready, update the branch, close/reopen, manage labels/assignees, enable/disable auto-merge, and join/leave the merge queue when supported. Details show requested reviewers, auto-merge method, queue position and state. Auto-merge is a persistent GitHub setting and can apply to subsequent commits under GitHub’s rules; the confirmation explains this.
- Issues: create, edit title/description, replace labels/assignees, and close as completed or reopen. Lists accept one name per line, including label names with spaces; empty lists remove all entries. New issues open in the reader after creation.
- CI: rerun all jobs, rerun failed jobs, rerun the current job and its dependents, or cancel an active workflow. These are offered from run details and completed job logs according to run state.

Every lifecycle action has a review/confirmation step. Confirmation defaults focus to Back. Submitting locks the dialog against duplicate activation; failures require closing and refreshing before retrying. Write requests use the existing GitHub login and surface GitHub permission/rules errors. The backend re-reads issue contents/metadata, PR head/base/state, or workflow attempt/status and rejects changed snapshots. APIs with head preconditions receive the confirmed SHA. Other REST edits have a preflight check but no atomic compare-and-swap, so a concurrent edit in the final request window remains possible.

Backend tests use mocked transports for every write path, and Qt tests exercise menu navigation, text editing, review/confirmation, snapshot binding, and duplicate-submit prevention. Live smoke checks only read GitHub data. Queue actions are verified against the live schema and mocked mutations; they require a repository with a configured merge queue to use.

## Search

Search covers issues and pull requests visible to your GitHub account, beyond the dashboard’s attention signals. Filter by repository, issue/PR type, and open/closed/merged state. Queries accept GitHub qualifiers, for example `label:bug`, `author:alice`, `review-requested:@me`, or `repo:owner/name`. Account qualifiers using `@me` resolve through the current login. Filters combine with the entire query, including OR expressions.

Results are sorted by latest update, loaded 50 at a time, and capped at GitHub’s 1,000-result search limit. Use Load more or P to fetch another page. Incomplete results, rate limits and permission errors appear in the search view. Submitting a newer query discards older in-flight responses. Search runs only when submitted, and its results are not written to disk.

## Inline code review

In a PR’s Changes tab, Up/Down selects changed files. Enter/Right opens Comment on line; choose a numbered New (right) or Old (left) diff line, write the comment, then review and confirm. Comments are submitted immediately as individual inline review comments, rather than collected into a pending batch review. Binary or unavailable patches cannot receive a line comment. Displayed lines include L/R numbers matching the selector.

The Threads tab groups inline conversations and marks them resolved, unresolved and/or outdated. Select a thread with Up/Down, then Enter/Right to resolve or reopen it. The confirmation checks current GitHub permissions, the PR head/base, thread membership and whether the loaded comments or resolution changed. Each read shows up to 100 threads and 100 comments per thread; oversized threads cannot be resolved from a partial conversation. GitHub does not offer an atomic comment-version precondition for thread resolution, so another reply in the final request window remains possible.

Inline comments bind the confirmed commit and a line from a freshly fetched patch. These controls reuse the explicit confirmation and duplicate-submit protection used by other actions. Tests use mocked write responses; live verification only reads GitHub data.
