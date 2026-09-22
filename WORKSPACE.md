# Native GitHub workspace

Accepted scope (22 September 2026): make routine repository, star, issue, PR,
review, conflict resolution, notification, CI and release work possible inside the existing plugin.
Repository administration, billing, Projects and security administration are
outside this change. Keep plugin ID `tcballard.github`, panel/service kinds,
Python 3 and the user's GitHub CLI authentication. No browser embedding or
credential copying.

## Architecture

- Keep the attention dashboard as a bounded summary; label it as such and add
  complete, paginated collection views. Repository homes link all native views.
- Extend the existing reader target protocol with typed collection, repository,
  code, review, workflow and release views. URL navigation resolves to these
  targets. Pagination is explicit and bounded per request.
- GitHub state stays on GitHub. Private local state (drafts, saved views, pins,
  review drafts, reading positions and detail cache) lives beneath XDG_STATE_HOME
  with account isolation and 0600 files. Never replay writes automatically.
- Every remote write uses the existing confirmation dialog, current server
  state and available SHA preconditions. Cached views have no remote actions.
- Remote Markdown is rendered through an escaping, restricted renderer. Links
  are classified; remote images require explicit loading. No remote HTML,
  scripts, local-file URLs or token-bearing image requests.
- Downloads use authenticated `gh api` in a bounded child process to a new file
  in the configured download directory; archives are not extracted.

## Delivery checklist

- [x] Repositories, stars, recent/pinned, repository search and homes
- [x] Paginated inbox, issues, incoming/authored/review PRs and saved views
- [x] README, code tree, branches, commits, releases and native URL navigation
- [x] Markdown/images, persistent drafts, positions and cached read-only details
- [x] Issue templates/forms, milestones, timeline, comments and reactions
- [x] PR creation/editing, draft conversion, reviewer removal, branch cleanup
- [x] Thread replies, pending batch reviews, multiline comments, viewed files
- [x] Complete diff/review/thread pages and suggested-change handling
- [x] Isolated PR conflict workspace, saved file resolutions and guarded merge publication
- [x] Check-to-log links, workflow history/dispatch, artifacts and log search
- [x] Release drafts/editing/publication and asset download/upload
- [x] Notification filtering, bulk page actions, done/unsubscribe
- [x] Discussion creation, nested replies and answer management

## Evidence

Portable verification on 22 September 2026:

- 111 Python tests passed, including mutation preflights, account isolation,
  pagination, templates, review submission and GraphQL syntax regression checks.
- 41 Qt Quick checks passed with PySide6 6.11.2 using real controls and stubbed
  Quickshell process/theme wrappers; no remote operations are executed.
- 15 static GraphQL operations validated against the official Octokit GitHub
  introspection schema. Runtime-selected mutations were checked against the
  GitHub reference documentation.
- Real Git fixtures cover content, add/add, modify/delete, binary and executable
  files, structural conflict rejection, marker validation, local revisions,
  two-parent commits, and actual push lease rejection against a local bare remote.
- A read-only public GitHub fetch and merge-tree smoke passed against this PR
  at b1d1cb9 and main at 6d84d58. No GitHub branch was changed by that check.
- Plugin archive builds, git whitespace checks pass, and the Omarchy plugin
  validator reports no errors, warnings or security findings.

## Target desktop smoke gate

Completed on Tom’s XPS: Tom confirmed all remaining local testing passed on
22 September 2026 after updating to main at `8793d4b`. The supplied Familiar
screenshot shows the running repository browser. This is owner-reported desktop
evidence; the automated checks above were run separately.

Completed checklist:

- Open/close with the plugin binding, keyboard navigation, Escape/back, focus
  restoration, current theme, secondary monitor and normal scaling.
- Open a repository and README, follow an issue reference, browse another code
  file/branch, then use Back and verify each reading position.
- Page through issues, stars and PR threads; filter inbox and restore a saved
  view. Restart the shell and verify drafts/pins persist for the same account.
- In a disposable repository, create an issue from a form and a PR, post a
  comment/reaction, stage and submit a multiline review, reply to a thread,
  mark a file viewed and apply a current suggestion.
- In a disposable conflicting PR, prepare the workspace, combine a text file,
  save a whole-file/deletion choice, inspect the merge preview and publish.
  Verify the source commit has both parents and the PR remains open. Test a fork
  with permission to push and a protected branch that rejects publication.
- Dispatch a test workflow, follow a check to its job/log, find a log term and
  download a small artifact. Create/edit a draft release, upload/download an
  asset, then publish only when deliberately ready.
- Verify a stale PR head blocks a saved review, a denied permission surfaces
  an error, and switching gh accounts cannot expose the previous account's
  drafts or cached details. Verify offline copies have no remote actions.

No authenticated GitHub mutations or live Omarchy desktop checks were run in
the build environment. Tom’s subsequent on-device confirmation closes the local
smoke gate. No release or tag has been published as part of this documentation update.
