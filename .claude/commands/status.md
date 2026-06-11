Code Cannon: Summarize in-progress and recently completed work from GitHub and git

---

## Step 1 — Parse arguments

First, check whether `$ARGUMENTS` contains `--milestone`, `--sprint`, or `--team`.

**Milestone mode:** If `--milestone` or `--sprint` is present, extract everything after the flag as the milestone name (trim leading/trailing whitespace; preserve internal spaces). Ignore any other arguments. Enter milestone mode (Steps M1–M3 below) and skip Steps 2–6.

Examples:
- `--milestone Sprint 4` → milestone name = `Sprint 4`
- `--sprint Sprint 4` → milestone name = `Sprint 4`
- `--milestone Q2 Release` → milestone name = `Q2 Release`
- `--milestone 12` → milestone name = `12`

**Team mode:** If `--team` is present, enter team mode (Steps T1–T3 below) and skip Steps 2–6. `--team` is mutually exclusive with `--milestone`/`--sprint` and username arguments. If both are present, report the conflict and stop.

**Personal mode** (no `--milestone` / `--sprint` / `--team` flag): determine:

- **subject**: default `@me`. If the argument starts with `@` or is a plain word that is not a number, treat it as a GitHub username. Strip the leading `@` for `gh` commands that do not accept it (e.g. `gh pr list --author alice`); keep it for display.
- **lookback**: default `7`. If the argument is a number (digits only), use it as the lookback window in days.

No argument → subject = `@me`, lookback = `7`.

---

## Step 2 — Fetch GitHub data (run all in parallel)

Run these commands concurrently:

**Open PRs authored by subject:**
```bash
gh pr list --author <subject> --state open \
  --json number,title,url,labels,milestone,baseRefName,body,reviewDecision,statusCheckRollup,updatedAt,mergeable,isDraft
```

**Recently merged PRs (last `<lookback>` days):**
```bash
gh pr list --author <subject> --state merged --limit 20 \
  --json number,title,url,mergedAt,labels,baseRefName
```
Filter the results to keep only entries where `mergedAt` is within the last `<lookback>` days.

**Open issues assigned to subject:**
```bash
gh issue list --assignee <subject> --state open \
  --json number,title,url,labels,milestone,updatedAt
```

**PRs requesting your review** (only when subject is `@me`):
```bash
gh pr list --search "review-requested:@me" --state open \
  --json number,title,url,author,updatedAt
```
Skip this query when viewing another user's status.

If any `gh` command exits with a non-zero status (including auth errors), report the error message and stop. Do not retry.

---

## Step 3 — Fetch local git context

Check if the current directory is inside a git repository:
```bash
git rev-parse --is-inside-work-tree 2>/dev/null
```

If yes, run:
```bash
git log --oneline --since="<lookback> days ago"
```

If not inside a git repo, skip this step and note it was skipped in the output.

---

## Step 4 — Classify items

Using the data from Steps 2 and 3, classify each item:

- **In progress** — open PRs. For each, attempt to identify a linked issue number from the PR body (look for `#N`, `closes #N`, `fixes #N`, `issue #N`). If found, cross-reference with open issues.
- **Done** — merged PRs within the lookback window.
- **Up next** — open issues that are NOT associated with any open PR (i.e. no open PR body references their issue number).
- **Needs your review** — PRs from the review-requested query (only when subject is `@me`).

An open issue that IS linked from an open PR body appears under "In progress" alongside that PR, not under "Up next".

### 4a — Derive health badges

For each open PR, derive the following badges:

**Draft status:**
- If `isDraft` is `true` → `[draft]`

**CI check status** (from `statusCheckRollup`):
- All checks have `status: COMPLETED` and `conclusion: SUCCESS` → `✅ checks passing`
- Any check has `conclusion: FAILURE` → `❌ checks failing`
- Checks are still running or have other states → `⏳ checks pending`
- No checks configured → omit badge

**Review decision** (from `reviewDecision`):
- `APPROVED` → `✅ approved`
- `CHANGES_REQUESTED` → `🔄 changes requested`
- `REVIEW_REQUIRED` or empty → `⏳ awaiting review`

**Merge conflict** (from `mergeable`):
- `CONFLICTING` → `⚠️ conflicts`
- `MERGEABLE` or `UNKNOWN` → omit badge

### 4b — Flag stale items

For each open PR and open issue, check `updatedAt`. If the item has not been updated within `14` days (default: 14; disabled when set to 0), flag it as stale. Record the last-updated date and the number of days since the last update.

A stale item gets an inline `⚠️ stale (<N>d)` badge appended after any other badges.

---

## Step 5 — Output the summary

Print a formatted summary. Use this structure:

```
## Status for <subject> — last <lookback> days

<N> in progress · <N> done · <N> up next[ · <N> need your review]

### In progress
- #<number> <title> [<labels>] [<milestone>] [draft]
  PR: <url>  ·  <check badge>  ·  <review badge>[ · <conflict badge>][ · <stale badge>]
  Linked issue: #<number> (if found)

### Done
- #<number> <title> [<labels>] — merged <date>
  PR: <url>

### Needs your review
- #<number> <title> (by @<author>)
  PR: <url>

### Up next
- #<number> <title> [<labels>] [<milestone>][ · <stale badge>]
  Issue: <url>

### ⚠️ Stale
- #<number> <title> — last updated <date> (<N> days ago)

---
Local commits (current branch):
<git log output, or "skipped — not in a git repo">
```

Rules:
- **Summary counts line**: show immediately after the heading. Omit zero-count segments (e.g., if nothing is done, skip that segment). "need your review" only appears when subject is `@me` and the count is > 0.
- **Health badges**: show on the second line of each "In progress" item, after the PR URL, separated by ` · `. Omit individual badges that don't apply (e.g., no conflict badge if mergeable).
- **Draft badge**: show `[draft]` inline in the first line of draft PRs, before any other badges.
- **Stale section**: a dedicated section at the bottom (before "Local commits") listing all stale items from any section, with their last-updated date and age. This gives a consolidated view. Individual items also get the inline `⚠️ stale (<N>d)` badge in their own sections.
- **"Needs your review" section**: only shown when subject is `@me` and there are PRs requesting review. Placed between "Done" and "Up next".
- Omit any section that has no items — do not show an empty heading.
- Show labels only if present; show milestone only if present.
- Dates use `YYYY-MM-DD` format.
- If all GitHub sections are empty, print: `Nothing found for <subject> in the last <lookback> days.`

Do not post, comment, write files, or take any action. Output only.

---

## Step 6 — What's next

After the status summary, append a single actionable suggestion based on local git state and the GitHub data already fetched.

### 6a — Gather additional local state

Run these commands (skip if not in a git repo):

```bash
git branch --show-current
```

```bash
git status --porcelain
```

```bash
git describe --tags --abbrev=0 2>/dev/null
```

```bash
git rev-list <latest-tag>..HEAD --count 2>/dev/null
```

From the GitHub data fetched in Step 2, also check for the current branch's PR approval status:

```bash
gh pr view --json number,title,url,reviewDecision,statusCheckRollup \
  --jq '{number,title,url,reviewDecision,checks: [.statusCheckRollup[]? | .status]}'
```

If `gh pr view` exits non-zero (no PR for current branch), note that there is no open PR.

### 6b — Determine suggestion

Evaluate the following conditions **in order**. Use the **first** match:

| Priority | Condition | Output |
|----------|-----------|--------|
| 1 | On a `feature/*` branch with uncommitted changes (`git status --porcelain` is non-empty) | `What's next: You have uncommitted changes on \`<branch>\`. When ready, run \`/submit-for-review\`.` |
| 2 | On a `feature/*` branch with an open PR that has `reviewDecision: APPROVED` and all status checks are `COMPLETED` | `What's next: PR #<number> is approved and checks pass. Consider running \`/deploy\`.` |
| 3 | On a `feature/*` branch with an open PR (any other review/check state) | `What's next: PR #<number> (<title>) is open and awaiting review.` |
| 3.5 | Subject is `@me` and there are PRs requesting your review (from Step 2 query) | Append to the current suggestion (or show standalone if no higher priority matched): `You also have <N> PR(s) awaiting your review.` |
| 4 | On a `feature/*` branch with no open PR and clean working tree | `What's next: No open PR for \`<branch>\`. Run \`/submit-for-review\` to open one.` |
| 5 | On the integration branch (`dev`, `develop`, or `main` when no integration branch exists) with unreleased commits (rev-list count > 0 since last tag) | `What's next: <N> commit(s) on \`<branch>\` since \`<tag>\`. Run \`/deploy\` when ready to release.` |
| 6 | No open PRs, no open issues assigned to subject | `What's next: Nothing in progress. Run \`/start\` to begin new work.` |
| 7 | Open issues exist in "Up next" | `What's next: Next up is #<number> (<title>). Run \`/start <number>\` to pick it up.` |

If none of the above match, omit the "What's next" section entirely.

### 6c — Format

Print the suggestion after a horizontal rule, below the local commits section:

```
---
🧭 <suggestion text>
```

This section is omitted in milestone mode.

---

## Milestone mode (Steps M1–M3)

Only entered when `--milestone` or `--sprint` is detected in Step 1.

### Step M1 — Fetch milestone issues

```bash
gh issue list --milestone "<name>" --state all --limit 200 \
  --json number,title,state,labels,assignees,url
```

If this command fails for any reason (milestone not found, auth error, etc.), report the error and stop.

### Step M2 — Classify issues

Fetch all open PRs to detect which issues are in progress (with health fields):

```bash
gh pr list --state open \
  --json number,title,body,baseRefName,reviewDecision,statusCheckRollup,mergeable,isDraft
```

Group issues into three buckets:

- **Done** — `state: closed`
- **In progress** — `state: open` AND the issue number appears in any open PR body (look for `#<number>`, `closes #<number>`, `fixes #<number>`, `issue #<number>`)
- **Not started** — `state: open` AND no open PR body references the issue number

For in-progress issues, derive health badges from the linked PR using the same rules as Step 4a (check status, review decision, draft, conflict).

### Step M3 — Output the summary

```
## Sprint: <name>

<Y> of <total> issues closed · <Z> in progress · <W> not started

### In progress (<Z>)
- #<number> <title> [@<assignee>] [<milestone>][ [draft]]
  <url>  ·  <check badge>  ·  <review badge>[ · <conflict badge>]

### Not started (<W>)
- #<number> <title> [@<assignee>]

### Done (<Y>)
- #<number> <title>
```

Rules:
- Show "In progress" first, then "Not started", then "Done"
- Show assignee only if present; omit if unassigned
- Show URLs only for in-progress items; omit URLs for closed issues
- Show health badges on in-progress items (same derivation as Step 4a)
- If a section has no items, omit it entirely

Do not post, comment, write files, or take any action. Output only.

---

## Team mode (Steps T1–T3)

Only entered when `--team` is detected in Step 1.

### Step T1 — Fetch all open work (run both in parallel)

```bash
gh pr list --state open --limit 100 \
  --json number,title,url,author,labels,milestone,baseRefName,body,reviewDecision,statusCheckRollup,updatedAt,mergeable,isDraft
```

```bash
gh issue list --state open --limit 200 \
  --json number,title,url,assignees,labels,milestone,updatedAt
```

If either command fails, report the error and stop.

### Step T2 — Group and classify

Group items by person:
- PRs are grouped by `author.login`
- Issues are grouped by assignee (first assignee if multiple). Issues with no assignee go into an "Unassigned" group.

Within each person's group, classify items the same way as personal mode (Step 4):
- **In progress** — open PRs (and linked issues)
- **Up next** — open issues not linked from any open PR

Derive health badges (Step 4a) and flag stale items (Step 4b) for all items.

### Step T3 — Output the team summary

```
## Team status

<N> open PRs · <N> open issues · <N> people

### @<person> (<N> in progress, <N> up next)
- #<number> <title> — PR <check badge> · <review badge>[ · <conflict badge>][ · <stale badge>][ [draft]]
  <url>
- #<number> <title> [up next][ · <stale badge>]

### @<person> (<N> in progress, <N> up next)
...

### Unassigned (<N>)
- #<number> <title>
  <url>

### ⚠️ Stale
- #<number> <title> (@<person>) — last updated <date> (<N> days ago)
```

Rules:
- Sort people alphabetically by username
- Within each person, show in-progress items first, then up-next items
- Show health badges on PR items (same format as personal mode)
- Show `[draft]` on draft PRs
- Tag up-next items with `[up next]` for visual distinction
- "Unassigned" section appears at the bottom, only if there are unassigned issues
- "Stale" section consolidates all stale items across all people
- Omit any section or group with no items
- No "What's next" section in team mode

Do not post, comment, write files, or take any action. Output only.

---

## Hard rules

- Never write to GitHub (no comments, labels, issue updates, or PR changes).
- If `gh` is unauthenticated or any fetch fails, report the error and stop immediately.
- Do not retry failed commands.
- Strip the leading `@` from the subject when passing to `gh` flags that do not accept it.
<!-- generated by CodeCannon/sync.py | skill: status | adapter: claude | hash: ab4b0450 | DO NOT EDIT — run CodeCannon/sync.py to regenerate -->
