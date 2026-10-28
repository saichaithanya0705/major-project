# Main branch integration - 2026-10-28

## What I did

Combined the eight stacked GitHub PRs with local `main`, including its five
unpublished commits and eight uncommitted launcher/runtime files. The existing
local changes were checkpointed in `e4b8b72` before merging the complete PR stack
from `68e59c8`.

| PR | Change | Original head |
| --- | --- | --- |
| [1](https://github.com/saichaithanya0705/major-project/pull/1) | Reproducibility, tests, dead vendor cleanup | `8824305` |
| [2](https://github.com/saichaithanya0705/major-project/pull/2) | Pluggable coding CLI backends | `279187c` |
| [3](https://github.com/saichaithanya0705/major-project/pull/3) | Local brain and provider escalation | `237f3c9` |
| [4](https://github.com/saichaithanya0705/major-project/pull/4) | Skills and document builders | `18f5686` |
| [5](https://github.com/saichaithanya0705/major-project/pull/5) | Browser confirmations and Gemini-free operation | `d8b14c2` |
| [6](https://github.com/saichaithanya0705/major-project/pull/6) | Explicit memory and offline voice | `29aee51` |
| [7](https://github.com/saichaithanya0705/major-project/pull/7) | Task scorecard | `6534a1a` |
| [8](https://github.com/saichaithanya0705/major-project/pull/8) | ChatGPT plan sign-in integration | `68e59c8` |

## Why this approach

A history-preserving merge keeps both development lines and all original PR
commits reachable from `main`, making inclusion verifiable with Git ancestry.
The existing `models/runtime`, `models/routing`, and `models/shared` layout stays
canonical, and memory hooks and document-routing examples fit that layout.

## Why not the alternative

Replacing either branch with the other would discard unique work. Reintroducing
the old root-level direct-answer runtime would duplicate the local chat agent
and leave the new local-model behavior disconnected from the active chat path.

## What was the issue / root cause

Both lines diverged from `f48895b`: local work reorganized the model modules and
centralized chat in `DirectChatAgent`, while the PRs edited the older module
paths. Git reported three conflicts in the direct-answer runtime, model bridge,
and routing prompts. A new skill-import test also assumed native symlink
creation privileges that this Windows account does not have.

## Why this works best

`DirectChatAgent` now uses the shared provider brain for normal and sourced
answers while retaining Tavily search, source rendering, conversation history,
and explicit escalation. Three integration cases cover these combined paths.
Skill-import tests independently check dangerous-capability approval, rejection
before copying, and real symlinks where the OS allows creating them. Only the
native test skips for Windows error 1314; production validation is unchanged.
The retired vendor directory is ignored so existing local CLI sessions remain
on disk without being reintroduced into source control; the database, battery
report, and migration marker removed from tracking are also retained locally
as ignored files.

Validation on the combined tree:

- Full Python suite: **635 passed, 1 skipped** (232.30 seconds), including the
  rendered UI test enabled through a temporary Playwright installation.
- Rendered UI harness: **7 scenarios passed**, covering keyboard controls,
  stopping work, restored history, platform shortcuts, storage failures, and
  compact window sizes.
- All tracked JavaScript files passed `node --check`; both PowerShell entry
  points passed the PowerShell parser.
- `pip check` found no broken installed requirements; Git whitespace checks
  passed and all merge conflicts were resolved.
- The sole skip is native symlink creation, unavailable to this Windows account
  (error 1314); the rejection-before-copying and dangerous-approval tests passed.

## Other valid patterns

Rebase or squash integration could also combine the code, but would rewrite or
hide the original PR commit identities. Keeping the source branches temporarily
provides recovery references; `main` is the consolidated development branch.
Live provider accounts, speech models, and packaged Windows app execution need
their own runtime validation; deterministic tests do not establish those results.
