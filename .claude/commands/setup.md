Code Cannon: Detect setup state, guide first-time configuration, populate labels, and walk through optional config values

---

## Detect state

Before taking any action, determine which state the project is in. Run these checks in order.

**Check A — Is this the Code Cannon skill library repo itself?**

```bash
test -f sync.py && test -d skills
```

If both exist at the working directory root → **go to State 1**.

**Check B — Is there any Code Cannon submodule presence?**

```bash
test -d CodeCannon
```

```bash
test -f .gitmodules && grep -q CodeCannon .gitmodules
```

If either is true → **go to State 2**.

**Check C — State 1 fallback**

If `.codecannon.yaml` is absent AND neither `CodeCannon/` nor `.gitmodules` exist → **go to State 1**.

Otherwise → **go to State 2**.

---

## State 1 — Just checking it out

Do not configure anything. Do not touch any file.

Tell the user warmly that Code Cannon is designed to live as a submodule inside another project — running `/setup` here in the Code Cannon repo itself isn't the intended path.

Offer two forward paths and ask which they want:

**Path A — "I want to understand how Code Cannon works"**

Explain the three-layer model:
- **Skills** (`skills/*.md`) — portable workflow instructions with `main`-style tokens for project-specific values (see `config.schema.yaml`)
- **Config** (`.codecannon.yaml`) — a project's values that fill those tokens at sync time
- **Sync** (`sync.py`) — reads the config, substitutes values, and writes generated command files for each adapter (Claude Code → `.claude/commands/`, Cursor → `.cursor/rules/`)

Point to README.md for the full skill list and documentation. Do not touch any file.

**Path B — "I want to add Code Cannon to my project"**

Show the exact command sequence:

```bash
cd /path/to/your-project
git submodule add https://github.com/LightbridgeLab/CodeCannon.git CodeCannon
git submodule update --init
cp CodeCannon/templates/codecannon.yaml .codecannon.yaml
# Edit .codecannon.yaml — set branch names, commands, adapters
CodeCannon/sync.py
```

Do not touch any file. The user runs these commands in their project directory.

---

## State 2 — Partial or broken setup

Run checks 1–7 in order. Stop at the first failing check and address it. After describing the fix, tell the user to run `/setup` again once they've resolved it. Do not continue past a failing check.

### Check 1 — CodeCannon/sync.py present

```bash
test -f CodeCannon/sync.py
```

If missing: the submodule was added to `.gitmodules` or `CodeCannon/` exists as an empty directory, but it hasn't been initialized. Show:

```bash
git submodule update --init --recursive
```

Offer to run it. If the user agrees, run it. If they decline, tell them to run it manually before continuing. Stop.

### Check 2 — gh installed

```bash
which gh
```

If not found: "`gh` is required by all Code Cannon skills. Install it with `brew install gh` (macOS) or from https://cli.github.com." Cannot proceed without it. Stop.

### Check 3 — gh authenticated

```bash
gh auth status
```

If exit code is non-zero: "You're not authenticated with GitHub." Show:

```bash
gh auth login
```

Cannot proceed without it. Stop.

### Check 4 — Inside a GitHub repository

```bash
gh repo view --json name
```

If exit code is non-zero: warn that most skills require a GitHub remote. Skills can be read and configured, but `/start`, `/submit-for-review`, `/review`, `/deploy`, and `/status` will fail without one. This is not a hard stop — ask if the user wants to continue configuring anyway.

### Check 5 — .codecannon.yaml present

```bash
test -f .codecannon.yaml
```

If missing: "I'll create `.codecannon.yaml` from the template — you'll want to review the branch names and commands before running sync."

Show:

```bash
cp CodeCannon/templates/codecannon.yaml .codecannon.yaml
```

Ask permission to run it. If the user agrees, run it. If they decline, tell them to run it manually.

After creating the file, proceed immediately to Check 5b.

### Check 5b — Profile selection (only on first setup)

This check runs only when Check 5 just created `.codecannon.yaml` from the template. If `.codecannon.yaml` already existed before this `/setup` invocation, skip to Check 6.

Ask the user:

> "What level of process does this project need?"
>
> **1. Lightweight** — Fast iteration. AI review is advisory, features merge to main, no QA workflow.
>
> **2. Standard** — Integration branch with AI-gated review. QA and milestones available but not required.
>
> **3. Governed** — Full traceability. QA handoff, assigned reviewers, milestones, structured labels.
>
> **4. Custom** — Configure each setting individually.
>
> Pick a number, or describe your workflow and I'll recommend one.

Wait for response. If the user describes their situation instead of picking a number, recommend the best-fit profile and confirm before applying.

**Apply profile values to `.codecannon.yaml`:**

After the user selects a profile, ask the applicable follow-up questions from this list:
- "What's your production branch name?" (default: `main`) — ask for all profiles except Custom
- "What's your integration branch name?" (default: `development`) — ask for Standard and Governed only
- "Do you need a separate test/staging branch?" (default: `staging`) — ask for Governed only; if yes, ask for the branch name

Show every change before writing and ask "Apply these values to `.codecannon.yaml`? (yes/no)". Write only on yes.

| Profile | Values to write | Values left commented out |
|---|---|---|
| **Lightweight** | `BRANCH_PROD`, `REVIEW_GATE: "advisory"` | `BRANCH_DEV`, `BRANCH_TEST`, `DEFAULT_REVIEWERS`, `TICKET_LABELS`, all QA labels |
| **Standard** | `BRANCH_PROD`, `BRANCH_DEV`, `REVIEW_GATE: "ai"` | `BRANCH_TEST`, QA labels |
| **Governed** | `BRANCH_PROD`, `BRANCH_DEV`, `REVIEW_GATE: "ai"`, `QA_READY_LABEL: "ready-for-qa"`, `QA_PASSED_LABEL: "qa-passed"`, `QA_FAILED_LABEL: "qa-failed"`, and `BRANCH_TEST` if applicable | — |
| **Custom** | Nothing — tell the user to review the file manually | — |

After writing, say: "<Profile> profile applied. Check the workflow commands and run `/setup` again to finish configuration." Stop.

### Check 6 — .codecannon.yaml stale values

Read `.codecannon.yaml`. Apply the following checks conservatively — only flag a value if you are confident it points to something that does not exist:

- If `VERSION_READ_CMD` references `package.json` and no `package.json` exists at the project root → flag it
- If `BRANCH_DEV` is set to a non-empty value and that branch does not appear in `git branch -a` → flag it
- If `BRANCH_TEST` is set to a non-empty value and that branch does not appear in `git branch -a` → flag it

If nothing is confidently broken, do not flag anything. When in doubt, do not flag.

If anything is flagged: show the specific key names and what they should likely be changed to. Do not modify the file. Tell the user to update these values and run `/setup` again. Stop.

### Check 7 — Generated skill output present

Check whether sync.py has been run by looking for any of the adapter output directories configured in `.codecannon.yaml`:

```bash
test -d .claude/commands || test -d .cursor/rules || test -d .agents/skills || test -d .gemini/skills
```

If none exist: "sync.py hasn't been run yet — the skill commands don't exist."

Show:

```bash
CodeCannon/sync.py
```

Ask permission to run it. If the user agrees, run it. If they decline, tell them to run it manually before continuing. Stop.

---

## State 3 — Everything configured

All checks pass. Run phases 1–4 in order.

---

### Phase 1 — Health summary

Print one sentence confirming the setup looks healthy. Read `.codecannon.yaml` and infer the workflow profile for display:

- `REVIEW_GATE` is `"advisory"` or `"off"` AND `BRANCH_DEV` is empty → **Lightweight**
- `REVIEW_GATE` is `"ai"` AND `BRANCH_DEV` is set AND `QA_READY_LABEL` is empty → **Standard**
- `REVIEW_GATE` is `"ai"` AND `QA_READY_LABEL` is set → **Governed**
- Anything else → **Custom**

Check whether the configured dev/test branches exist in the remote (skip checks for empty values):

```bash
git branch -a | grep -q "remotes/origin/<BRANCH_DEV value>"
git branch -a | grep -q "remotes/origin/<BRANCH_TEST value>"
```

Display:

```
Setup looks healthy. Profile: <inferred profile>

  BRANCH_PROD:         <value>
  BRANCH_DEV:          <value>  (exists in remote: yes/no/not set)
  BRANCH_TEST:         <value>  (exists in remote: yes/no/not set)
  REVIEW_GATE:         <value>
  CHECK_CMD:           <value>
  MERGE_CMD:           <value>
  Adapters:            <list from config>

  Optional config:
    DEFAULT_MILESTONE              — set / unset
    DEFAULT_REVIEWERS              — set / unset
    TICKET_LABELS                  — set (N labels) / unset
    TICKET_LABEL_CREATION_ALLOWED  — set / unset
    QA_READY_LABEL                 — set / unset
    PLATFORM_COMPLIANCE_NOTES      — set / unset
    CONVENTIONS_NOTES              — set / unset
    SENSITIVE_AREAS_GATE           — "true" (default) / "false"
    SENSITIVE_AREAS_CATEGORIES     — set (custom list) / unset (default 5-category list)
```

A value counts as "set" if it is present, uncommented, and non-empty in `.codecannon.yaml`.

---

### Phase 2 — Permission audit

Check whether the agent's permission configuration covers the shell commands Code Cannon skills use. Read `CodeCannon/permissions.yaml` to get the list of required command prefixes.

**Claude Code:** Read `.claude/settings.local.json` (if it exists) and `.claude/settings.json` (if it exists). Collect all `Bash(...)` entries from the `permissions.allow` arrays in both files. For each command prefix in `permissions.yaml`, check whether an allow rule covers it (e.g. `Bash(git:*)` or `Bash(git *)` covers the `git` prefix).

If all prefixes are covered, display `Agent permissions: all skill commands pre-approved` and continue to Phase 3.

If any prefixes are missing, show:

```
Agent permissions: some skill commands may prompt for approval.

  Missing allow rules:
    - Bash(cd:*)
    - Bash(make:*)
    ...

  To pre-approve these, add them to .claude/settings.local.json (git-ignored)
  or .claude/settings.json (shared with team). See docs/index.md for a full example.

  This is optional — you can approve commands individually when prompted instead.
```

Do not modify any settings file. This is advisory only.

**Other agents (Cursor, Codex, Gemini):** Skip this phase silently — Cursor doesn't prompt, and Codex/Gemini permission systems vary. The docs cover these agents separately.

---

### Phase 3 — Commit signing

Check whether commit signing is already configured at any level (local or global):

```bash
git config --get commit.gpgsign
```

If the output is `true`, display `Commit signing: enabled` in the health summary area and skip to Phase 4.

If not `true`, ask: **"Does this project require signed commits? (yes/no)"**

Wait for response.

- **no / skip** → continue to Phase 4.
- **yes** → proceed with signing setup.

**Verify a signing key exists:**

```bash
git config --get user.signingkey
```

**If a signing key is found**, show the proposed change and confirm:

```
I'll enable commit and tag signing for this repo:

  git config commit.gpgsign true
  git config tag.gpgsign true

  Signing key: <truncated-key>

Proceed? (yes/no)
```

Wait for confirmation. Write only on yes. If no, skip to Phase 4.

Continue to Phase 4.

**If no signing key is found**, detect the signing format:

```bash
git config --get gpg.format
```

- If `ssh` → suggest: `git config user.signingkey ~/.ssh/id_ed25519.pub` (adjust path to the user's key). Ask the user for their SSH public key path.
- If `gpg` or unset → suggest: run `gpg --list-secret-keys --keyid-format=long` to find a key ID. Ask the user for their GPG key ID.

Once the user provides a key value, show the proposed changes and confirm:

```
I'll configure signing for this repo:

  git config user.signingkey <provided-key>
  git config commit.gpgsign true
  git config tag.gpgsign true

Proceed? (yes/no)
```

Wait for confirmation. Write only on yes. If no, skip to Phase 4.

If the user has no signing key and doesn't know how to create one, point them to GitHub's signing key documentation and stop: "Set up a signing key first, then run `/setup` again to enable commit signing."

---

### Phase 4 — Label population

Run:

```bash
gh label list --limit 100 --json name,color,description
```

If zero labels are found, treat this as a greenfield repository and offer a starter label baseline before asking about `TICKET_LABELS`.

Show this recommendation:

```
No labels were found. For new projects, a practical baseline is:
  - bug
  - enhancement
  - chore
  - documentation
  - ready-for-qa
  - qa-passed
  - qa-failed
```

Ask: **"Create any missing labels from this baseline now? (yes/no)"**

Wait for response.

- **yes** → run `python3 CodeCannon/skills/github-agile/scripts/label-create.py bug enhancement chore documentation ready-for-qa qa-passed qa-failed`. The script applies sensible color/description defaults from a baked-in table and warns-and-continues on any name that already exists.
- **no / skip / anything else** → continue without creating labels.

#### Configured-label audit

Whether or not the greenfield baseline ran, audit the labels that configured skills will try to apply at runtime against what actually exists in the repo:

```bash
python3 CodeCannon/skills/github-agile/scripts/label-audit.py
```

The script reads `.codecannon.yaml`, collects the names referenced by `TICKET_LABELS` plus `QA_READY_LABEL` / `QA_PASSED_LABEL` / `QA_FAILED_LABEL` (skipping any that are unset), diffs against `gh label list`, and prints missing names — one per line — on stdout. A one-line diagnostic goes to stderr.

- **No stdout output** → all configured labels exist. Continue silently to the "Display the results" step below.
- **One or more names on stdout** → show them as a combined list and ask once: **"These labels are referenced by your configured skills but don't exist in the repo: \<list\>. Create them now? (yes/no)"**
  - **yes** → run `python3 CodeCannon/skills/github-agile/scripts/label-create.py <name1> <name2> ...` with the missing names from the audit output.
  - **no / skip** → continue, but at the end of Phase 4 print a one-line summary: "Skipped creating: \<list\>. `/submit-for-review` will warn and continue if it needs to apply a missing label; `/qa` and `/start` may degrade similarly."

After this step (or if labels were non-zero initially), run `gh label list --limit 100 --json name,color,description` again.

If `TICKET_LABELS` is unset or fewer than 5 labels exist, add a note: "`/start` works best with a clear issue-label pool (`TICKET_LABELS`), and `/qa` needs explicit QA lifecycle labels (`ready-for-qa`, `qa-passed`, `qa-failed`). Consider a lightweight priority scheme (e.g. `priority:high`, `priority:medium`, `priority:low`) if the team needs triage support. If the team runs planned iterations, set `DEFAULT_MILESTONE` in Phase 5; otherwise leave it unset so `/start` auto-detects."

Display the results as a numbered list:

```
Available labels (N found):
  1. bug — Something isn't working
  2. enhancement — New feature or request
  3. good first issue — Good for newcomers
  ...
```

Ask: **"Write these label names to `.codecannon.yaml` as TICKET_LABELS? (yes / no / list specific numbers)"**

Wait for the user's response.

- **yes** → use all labels
- **numbers** (e.g. `1,3,5`) → use only those labels
- **no / skip / anything else** → skip this phase, continue to Phase 5

Show the exact change before writing:

```
I'll update .codecannon.yaml with:

  TICKET_LABELS: "bug,enhancement,..."

Proceed? (yes/no)
```

Wait for confirmation. Write only on yes.

---

### Phase 5 — Optional config walkthrough (profile-aware)

First, infer the current profile using the same rules as Phase 1.

The walkthrough adapts based on profile. Walk through each applicable unset value in the order shown. Skip any value already set. If the user says "skip", move on without modifying the file and do not ask again.

**Common pattern for simple values** (DEFAULT_MILESTONE, DEFAULT_REVIEWERS, TICKET_LABEL_CREATION_ALLOWED): explain in one sentence, show the example value, ask. If the user provides a value, show the exact YAML change and ask "Write this to `.codecannon.yaml`? (yes/no)". Write only on yes.

**Common pattern for drafted values** (PLATFORM_COMPLIANCE_NOTES, CONVENTIONS_NOTES): ask what technologies/conventions apply, draft 2–4 concise checkable rules, show the draft, iterate until the user approves or skips. On approval, show the exact YAML change, confirm, write only on yes.

| Key | Profiles | Description | Example / Prompt |
|---|---|---|---|
| `DEFAULT_MILESTONE` | Governed, Custom | Default milestone for `/start` issues | `"Sprint 4"` — "Which milestone, if any?" |
| `DEFAULT_REVIEWERS` | Standard, Governed, Custom | PR reviewers for `/submit-for-review` | `"@alice,@bob"` — "Who should review PRs?" |
| `TICKET_LABEL_CREATION_ALLOWED` | Standard, Governed, Custom | Allow `/start` to create new labels on the fly (defaults to `false`) | `"true"` — "Allow label creation? (true/false)" |
| `PLATFORM_COMPLIANCE_NOTES` | All | Platform-specific rules for the review agent | "What backend/infra? (Postgres, Next.js, etc.)" |
| `CONVENTIONS_NOTES` | All | Non-obvious team conventions for the review agent | "What conventions should a reviewer catch?" |

**Lightweight** skips DEFAULT_MILESTONE, DEFAULT_REVIEWERS, and TICKET_LABEL_CREATION_ALLOWED — those are intentionally unset.

---

### Phase 6 — Team sharing

After completing or skipping the config walkthrough, say:

"To share this setup with your team, commit these files. Anyone who clones the project and runs `git submodule update --init` will have all skills ready — no further setup needed."

Show the exact command:

```bash
git add .codecannon.yaml .claude/ CodeCannon AGENTS.md
```

Add a note: `/start` can be used to create well-formed GitHub issues without writing any code — useful for non-developers tracking work. `/status` generates standup summaries from open issues and PRs — both are valuable outside of a development workflow.

---

## Hard rules

- Only modify `.codecannon.yaml` and local git config (Phase 3 signing setup). Do not touch any other file (except running `CodeCannon/sync.py`, which modifies `.claude/commands/` — permitted only with explicit user approval).
- Do not run `sync.py` without explicit user permission.
- Do not create `.codecannon.yaml` without explicit user permission.
- Do not report a configuration problem unless confident the condition is genuinely broken. Prefer false negatives over false positives on all diagnostic checks.
- Never fetch more than 100 labels in a single command. `gh label list --limit 100` is the ceiling.
- Do not skip any human gate in Phase 3, Phase 4, or Phase 5 — each write requires confirmation.
- If the user skips a config value, do not ask again. Move on.
<!-- generated by CodeCannon/sync.py | skill: setup | adapter: claude | hash: a086fe27 | DO NOT EDIT — run CodeCannon/sync.py to regenerate -->
