# GitHub workspace

Use **Repositories** (7) or **Stars** (8) to browse GitHub. Open a repository for
its README, files, branches, commits, issues, PRs, Actions and releases. Pin a
repository through Actions; Pinned and Recent are available from Repositories.
Use **Open link** for an owner/repository or GitHub issue, PR, discussion,
commit, release, code or Actions link. Inside a repository, `#123` also works.

The original dashboard remains a recent attention snapshot. **Browse all /
filter** opens complete paginated lists. Issues have assigned, created,
involving and incoming views; PRs have authored, requested-review, involving
and incoming views. Choose an owner such as `tcballard` or `asdecided`, then
save the view through Actions. Saved views are under 9.

Repository issue and PR lists use ordinary API pagination. Cross-repository
qualified searches retain GitHub's 1,000-result limit; narrow by repository,
owner or date when needed. Empty filtered pages can still have a next page.
Star searches scan your own list in resumable chunks of up to 500 repositories;
Continue star search includes older stars and accumulates matches. The view
explicitly says when the search is complete.

## Reading and writing

Common Markdown headings, emphasis, links, lists and fenced code are rendered
natively. Raw HTML remains escaped. Image links offer an explicit Load image
button; no remote image is requested just by opening a thread. Relative
repository images use raw GitHub URLs. Private image attachments may require
browser authentication and cannot always be previewed here. External references
have a separate explicit open button. GitHub links open in the native reader.

Reply drafts and reading positions are saved per account. Use Find in a page,
diff or log to select successive matches. Change tabs with brackets or Ctrl+Tab.
Actions opens the available forms; repository, label, assignee, reviewer,
milestone and branch fields offer paginated Browse choices pickers while
retaining direct text entry.

Issue templates are available from the repository overview. Markdown templates
and YAML issue forms support input, textarea, dropdown and checkbox controls,
including required fields. YAML issue forms and workflow input forms require
the Arch package **python-yaml**; missing support produces a specific dependency
message. The plugin never installs packages itself. Regular issue/PR browsing
does not require it.

Comment actions edit/delete top-level issue/PR comments and add reactions.
Issue actions include milestones and closing as not planned. Related contains
the issue timeline, labels, people and milestones. Discussion comments open
their own paginated replies; discussion actions support creation, nested replies,
answers and closing/reopening, subject to GitHub permissions and category rules.

## Pull requests and reviews

Create a PR from the repository Actions menu using an existing pushed source
branch. PR actions edit title/body/target, convert to draft, remove requested
reviewers and delete a merged source branch. Existing approval, merge,
auto-merge, queue, ready-for-review and branch-update actions remain available.

Related → All changed files gives paginated diffs. Review file → Add to pending
review saves a commit-bound comment locally, optionally spanning multiple lines
on the same diff side. Related → Pending review shows the batch and submits it
as Comment, Approve or Request changes. Maximum 50 comments per batch. A changed
PR commit blocks submission; discard that draft and review the new commit.
Single inline comments in the original Changes tab still post immediately.

Related → All review threads opens complete, paginated inline conversations.
Reply in this thread stays in the inline thread. All reviews and All inline
comments are separately paginated. Viewed-file actions update GitHub and show
the local viewed marker for this exact commit.

A current right-side thread containing a single standard fenced suggestion can
offer Apply suggestion. It commits the replacement to the source branch using
the confirmed head as its parent, preserves executable mode, and advances the
branch without force. Concurrent branch advances reject the update. Outdated,
left-side, binary and offset-range suggestion formats are not applied.

## Resolve PR merge conflicts

Open a PR → Related → Resolve merge conflicts → Actions → Prepare conflict
workspace. Git downloads the objects into a private workspace and calculates
what merging the target branch into the PR source branch would do. Your own
checkout is never opened or changed. Requires Git 2.38+ and your existing
GitHub CLI login; there is no separate credential setup.

Open each conflicted file to compare the ancestor, PR source, target and merged
result. **Save resolution** offers these choices:

- **edit**: edit the proposed merged text, remove conflict markers and select
  regular or executable file permissions. This is the default for text files.
- **source**: keep the entire PR-source version of the file.
- **target**: keep the entire target-branch version of the file.

Whole-file choices replace the file, including any nonconflicting changes in
that same file. An absent side means delete the file. Binary files support
whole-file choices; the text editor supports UTF-8 files up to 60,000 characters.
Empty edited files are valid. Save each resolution explicitly; closing an unsaved
form discards its edits. Saved resolutions survive restarting the panel.

Once every file is resolved, inspect **Merge preview**, including changes Git
merged automatically, and choose **Commit resolved merge**. The separate
confirmation identifies both repositories, branches and commits. Publication
adds a merge commit to the PR source branch, preserving both parents; it leaves
the PR open and can start CI. It supports source branches in forks when your
GitHub account has permission to push. Branch rules, including signed-commit or
linear-history requirements, can reject this merge commit.

Both branches are checked again before publication. A changed branch requires
**Start again**, which discards saved resolutions. The source update also uses
an exact Git ref lease, so a concurrent source push is rejected without rewriting
history. A target branch can still advance after the final check; refresh the
PR and resolve any newly introduced conflicts. Failed or uncertain publication
is never retried automatically: refresh the PR first.

Text/content, add/add, modify/delete, binary and regular-file mode conflicts are
supported. Structural rename conflicts, directory/file conflicts, symlink and
submodule conflicts require a local Git checkout; the plugin blocks publication
of those sessions. Git still performs ordinary rename detection for cleanly
mergeable changes. It computes merge bases from full ancestry rather than
assuming a single ancestor.

Each workspace has a monitored 256 MiB budget and each Git operation sequence a
three-minute deadline. The budget is sampled while commands run, so a transfer
may briefly exceed it before being stopped. More than 100 conflicted files are
not handled in-panel. Full merge diffs above 1 MiB show the change summary with
an explicit preview warning. Use **Discard workspace** to delete local Git
objects and resolutions; successful publication also cleans them up. No files
are checked out, hooks run or submodules initialized. Your GitHub noreply address
is used for the merge commit, which is not signed.

## Actions and releases

A PR's Checks and Related tabs link to Actions runs for that exact commit.
Open a run for jobs, completed logs, all-job pagination and artifacts. Existing
rerun-all, rerun-failed, rerun-job and cancellation actions are retained. The
repository Actions view filters workflow, branch and status. Workflows opens
manual dispatch forms using declared inputs at the selected ref.

Create a release draft from its repository; edit the notes and prerelease flag,
upload assets, then publish through a separate confirmation. Release assets and
workflow artifacts download to `~/Downloads` with private file permissions,
unique names and no automatic archive extraction. Transfers are bounded to
256 MiB and three minutes. Oversized or timed-out transfers fail explicitly.
Uploads take an absolute local file path and do not replace existing assets.

Inbox filters include repository, unread/all and reason. Mark this page read
affects only the displayed snapshot, with a preflight for every notification.
Individual entries also offer Done and Unsubscribe. A partial batch failure
reports how many notifications were updated; it is never automatically retried.

## State, permissions and verification

Private state is stored under `$XDG_STATE_HOME/omarchy/github/accounts/` in
account-specific directories (normally `~/.local/state/omarchy/github/accounts/`).
It contains drafts, review drafts, saved views, pins, recents, reading positions,
viewed markers, resumable star searches, explicit conflict workspaces and the last 25 detail views within an
8 MiB cache budget. Credentials stay with `gh`. Removing the plugin leaves this
state and downloaded assets intact; delete the account-state directory yourself
if you want to remove saved private content.

Offline detail copies are available only for a previously verified account,
with timestamps and remote action controls removed. Authentication/permission
failures never fall back to private cached content. Draft writes are debounced
for 700 ms and flushed when closing normally; a sudden shell/process crash may
lose the last unflushed keystrokes. No remote write is queued or retried offline.

Remote writes retain confirmation and preflight checks. REST APIs without an
atomic version precondition still have a small race between checking and
writing, including comment/release edits and branch deletion. GitHub applies
normal permissions, protection and ruleset checks. There are no administrator
overrides. The active account is checked before executing an action.

Install development dependencies with `python3 -m pip install PyYAML==6.0.3 graphql-core==3.2.12 PySide6==6.11.2`.
Run `tests/run` for backend tests and archive checks. `tests/keyboard` uses the
host Qt Quick Test runner or PySide6's equivalent. PySide6 is a development-only
dependency. These tests fake the GitHub transport and shell wrappers; they do
not exercise live account writes or establish on-device Omarchy compatibility.

Repository/organisation settings, billing, Projects, security administration,
a general local Git editor are outside this workspace
expansion. Large binary/code files and unavailable patches retain explicit
preview limits. The target desktop smoke checklist is in `WORKSPACE.md`.
