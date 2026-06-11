Code Cannon: Walk the open sub-issues of a story ticket within one session

---

## What `/story` does

`/story <parent#>` walks the open sub-issues of a parent ("story") ticket in their GitHub-defined order, threading `/start` and `/submit-for-review` for each one into a single interactive session. It removes a few routine per-ticket prompts (`/start`'s plan-confirm gate and verified-locally prompt) — the operator already approved the whole story plan at story start.

What `/story` deliberately does **not** do: it does not auto-decide on `/submit-for-review`'s `needs-attention` warnings or `must-address` blockers. Those remain human-judgment moments. When the review stops, the driver pauses and waits — when the operator finishes, the driver resumes with the next sub-issue.

`/story` is intentionally a thin coordinator. See #167 for the design discussion and #177 for the deferred path that would automate judgment moments based on observed usage.

---

## Step 1 — Argument check

Required: a single integer (the parent issue number). If missing or non-numeric, abort:

> "/story requires a parent issue number. Usage: /story <parent#>"

---

## Step 2 — Fetch and echo the story plan

Find owner/repo if not already known:

```
gh repo view --json owner,name
```

Verify the parent and fetch its sub-issues:

```
gh issue view <parent#> --json number,title,state
gh api repos/<owner>/<repo>/issues/<parent#>/sub_issues --jq '.[] | {number, title, state}'
```

Stop immediately if any of these hold:

- Parent issue is closed → "Issue #<parent#> is closed. /story requires an open parent."
- Sub-issue list is empty → "Issue #<parent#> has no sub-issues. /story requires a parent with linked sub-issues."
- All sub-issues are closed → "All sub-issues of #<parent#> are closed. Story is complete."

Otherwise, echo the plan (filter to `state == "open"` for the work list; show closed ones for context):

> Story #<parent#>: <title>
>
> Open sub-issues (worked in this order):
> 1. #<Na> <title>
> 2. #<Nb> <title>
> ...
>
> Closed sub-issues (already complete): <"none" or list>
>
> Routine per-ticket prompts (plan-confirm at `/start` and verified-locally at end of `/start`) are auto-passed under the driver. Review-stage prompts (`needs-attention` warnings, `must-address` blockers) still stop and ask — they are the human-judgment moments.
>
> Type `go` to start, or share concerns first.

Wait for the operator. Proceed only on unconditional `go`. Treat any other response as discussion — address concerns and re-ask. If the operator abandons, stop with nothing to clean up.

---

## Step 3 — Ticket loop

For each open sub-issue, in the order returned by the API:

### 3a — Pre-flight escalation check

Read the sub-issue body (already fetched, or re-fetch via `gh issue view <sub#>` if needed). Stop and ask **before** invoking `/start` if any of these triggers fire:

- The acceptance criteria contain phrases like "TBD", "decide later", "?", or otherwise indicate unresolved scope.
- The body mentions a sensitive surface: authentication, authorization, payments, billing, secrets, credentials, production configuration, destructive operations (`DROP TABLE`, `rm -rf`, `git push --force`, mass deletes, schema drops).
- The body or any project-level guidance (e.g. `CLAUDE.md`) names a domain the operator has flagged for explicit review.

If any trigger fires:

> "Sub-issue #<sub#> triggered escalation: <reason>.
>
> - `proceed` — invoke `/start` for this sub-issue anyway (operator confirms they want it under the driver).
> - `defer` — skip this sub-issue for now and move on to the next.
> - `stop` — exit the driver with a partial summary."

Wait for the operator. Honor the choice exactly.

### 3b — Invoke `/start <sub#>` under the driver

Print this preamble line immediately before invoking the skill (this is the signal `/start` recognizes):

```
[story-driver: parent=<parent#> ticket=<index> of <open-count>]
```

Then invoke `/start <sub#>`. `/start` recognizes the preamble (see Case B in `/start`) and auto-passes its plan-confirm gate and verified-locally prompt. All other `/start` behavior is unchanged — including writing the code.

### 3c — `/submit-for-review` runs from `/start`'s auto-proceed

`/start` under the driver auto-fires `/submit-for-review` itself (because its verified-locally prompt is auto-approved). The driver does not invoke `/submit-for-review` separately — it observes the outcome and routes accordingly. The tier routing applies as today:

- `clean` or `informational` → auto-merge. The driver continues to the next sub-issue.
- `needs-attention` → `/submit-for-review` itself stops and asks the operator (address now / follow up later / accept as-is). The driver waits for the operator to respond through `/submit-for-review`. When `/submit-for-review` completes (either by merging or by routing back to coding), the driver resumes — either with the next sub-issue (on merge) or by re-running `/submit-for-review` after the operator fixes things.
- `must-address` → `/submit-for-review` itself stops; the operator fixes the blocker; the driver resumes on the next `/submit-for-review` invocation.

### 3d — Per-ticket safety

Track an attempt counter per sub-issue (start at 1; increment on each `/start → /submit-for-review` pass for the same sub-issue):

- **Attempt cap of 2**: if a sub-issue would require a third pass, stop and ask:
  > "Sub-issue #<sub#> has hit the attempt cap (2). Continue manually or stop the story?"
- **No-progress guard**: before each attempt past the first, capture `git diff origin/dev` on the feature branch. After the attempt, if the new diff is byte-identical to the previous attempt's diff, the iteration made no code change. Stop and ask:
  > "Sub-issue #<sub#> made no code progress on this attempt. Stop the story or take over manually?"

Both guards exist to prevent unbounded retry loops; neither tries to be clever.

---

## Step 4 — Track follow-up tickets created during the story

During each `/submit-for-review` run, follow-up tickets may be created (the `needs-attention` "follow up later" branch and the Step 9 selective branch both do this). Keep a running list of those follow-up issue numbers and their titles for the story summary in Step 5. The list is purely informational — sub-issue closure status is still the source of truth for "what got done."

---

## Step 5 — Story session end

When the loop exits (all open sub-issues processed, or operator chose `stop`), post a session summary as a comment on the parent issue. Skip the comment silently if nothing actually merged in this session.

Create a temp directory if not already created:

```
mkdir -p /tmp/CodeCannon && mktemp -d /tmp/CodeCannon/XXXXXX
```

Use the file-writing tool to create `<tmpdir>/story_summary.md`:

```markdown
## /story session summary

Worked by the /story driver in one interactive session.

**Merged:**
- #<sub#> <title> → PR #<pr#>
- ...

**Deferred or not addressed:**
- #<sub#> <title> (reason: <escalation / cap / no-progress / operator-stop>)
- ... (or "none")

**Follow-up tickets created during the story:**
- #<f#> <title>
- ... (or "none")
```

Post via the comment-posting script:

```
python3 CodeCannon/skills/github-agile/scripts/post-issue-comment.py <parent#> <tmpdir>/story_summary.md
```

Then close out to the operator:

> Story #<parent#> session done. Merged: N. Deferred: M. Open sub-issues remaining: K.
> If K > 0, run `/story <parent#>` again to resume from the next open sub-issue.

---

## Hard rules

- `/story` runs entirely inside the current interactive session. No `claude -p`, no headless subprocesses, no daemons.
- `/story` does not write or edit code itself — it sequences `/start` and `/submit-for-review`. The code is written inside `/start` as it normally would be.
- `/story` does not auto-decide on `/submit-for-review`'s `needs-attention` or `must-address` tiers. Those remain human-judgment moments.
- Sub-issue state is the source of truth. The Step 5 session summary is informational — deleting or editing it must not affect resumption. A fresh `/story <parent#>` invocation always re-derives state from open sub-issues.
- Attempt cap and no-progress guards stop the story rather than retry past the limit.
- If the driver itself is interrupted (operator switches tasks, session ends), no state needs to be saved. The next `/story <parent#>` resumes by picking up the next open sub-issue.
<!-- generated by CodeCannon/sync.py | skill: story | adapter: claude | hash: 67207d66 | DO NOT EDIT — run CodeCannon/sync.py to regenerate -->
