# Output-limit repair — 15 September 2026

Scope: marketplace issue omacom/omarchy-plugin-marketplace#6584, based on
81fbe393d7ca707c60dc4cb5ec05a054f1ef614e. Evidence applies to the accompanying
0.3.1 source changes, not the earlier validated commit.

- `python3 -B -m unittest discover -s tests -v`: PASS, 69 tests, including
  14 new subprocess regression tests. Real local Python children exercise exact
  byte limits, one-byte overflow on each stream, unbounded fast output,
  silent/continuous-output deadlines, closed pipes with a living child,
  concurrent request input/output, early stdin close, missing executable,
  direct-child reaping, descriptor closure, and descendants holding pipes open.
  Both client entry points are checked with a temporary fake gh executable.
  Existing application tests continue to mock GitHub writes.
- `python3 -B scripts/package.py`: PASS. Archive includes bounded_process.py;
  importing both clients from the extracted archive succeeds.
- Omarchy plugin test skill `validate_plugin.py --json --security .`: PASS
  structural validation, no errors/warnings or security findings. Existing QML
  Process/StdioCollector capability notices remain review-required; this is
  advisory validation, not marketplace security approval.
- `git diff --check`: PASS.

No live Omarchy desktop or authenticated GitHub write was used. Native host
validation and marketplace review of the corrected commit remain outstanding.
QML is unchanged; the keyboard suite was not rerun for this transport repair.


# Workspace on-device verification — 22 September 2026

Tom updated his XPS to main at `8793d4b` (the 0.4.0 workspace and conflict
resolution changes), confirmed the plugin opens and repository browsing works,
and subsequently confirmed all remaining local testing passed.

The screenshot at `docs/images/github-xps-familiar.png` was supplied by Tom
and is reproduced unchanged. It shows the plugin floating on the Familiar
theme with the repository browser open. This records owner-reported testing;
it does not turn the earlier mocked tests into live GitHub mutation evidence
or claim a new marketplace review. See WORKSPACE.md for the completed checklist.
