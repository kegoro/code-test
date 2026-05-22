---
description: Initial setup of a repo for the worktree-friendly [repo]/main layout, with optional main.2/main.3 parallel copies for trunk-based work
argument-hint: <repo-url-or-existing-clone-path> [target-parent-dir]
---

## General Guidelines

### Output Style

- **Never explicitly mention TDD** in code, comments, commits, PRs, or issues
- Write natural, descriptive code without meta-commentary about the development process
- The code should speak for itself - TDD is the process, not the product

# Worktree Layout Setup

Bootstrap the directory structure that `/worktree-add` and `/worktree-cleanup`
expect. The layout this command produces:

```
<parent>/<repo-name>/main             # primary worktree on the default branch
<parent>/<repo-name>/<type>/<slug>    # feature worktrees added by /worktree-add
<parent>/<repo-name>/main.2           # optional: additional local copy of main
<parent>/<repo-name>/main.3           # (for parallel trunk-based work)
```

**User arguments:**

Worktree-setup: $ARGUMENTS

**End of user arguments**

## Phase 0: Gas Town incompatibility check (HARD ABORT)

This command is **intentionally incompatible** with Gas Town. Gas Town manages
its own rig/crew topology, and this layout would shadow it. Abort if any of
the following is true:

| Detection | Condition |
|-----------|-----------|
| Gas Town home present | `~/gt/` exists |
| Currently inside a Gas Town tree | Working directory resolves under `~/gt/` |
| Target parent resolves under `~/gt/` | Resolved target path starts with `~/gt/` |
| `gt` binary present AND target inside a tracked rig | `command -v gt` succeeds and `gt status --json` lists target as a rig path |

If any check fails, print:

> Gas Town detected — this setup would conflict with `gt`'s rig topology.
> Use `gt rig add <repo-url>` instead. Exiting without changes.

…and exit. Do not proceed under any flag.

## Phase 1: Parse arguments and detect input mode

Possible input shapes:

| Input | Mode |
|-------|------|
| Git URL (`https://...` or `git@...`) | **fresh-clone** |
| Path to a regular clone with `.git/` (not already inside a worktree layout) | **convert** |
| Path inside an existing `<repo>/main` (one level deep) | **add-main-copy** (just adds another `main.N`) |
| No argument | Ask the user interactively |

For fresh-clone and convert modes, derive `<repo-name>` from the URL or
existing clone's `origin` remote (strip trailing `.git`). Default
`<target-parent-dir>` to the current working directory.

Show the user the resolved plan before doing anything destructive:

```
Mode:        <fresh-clone | convert | add-main-copy>
Repo name:   <repo-name>
Target:      <parent>/<repo-name>/main
Source:      <url or existing path>
```

Ask for confirmation. Abort on "no".

## Phase 2: Execute

### Fresh-clone mode

```bash
mkdir -p "<parent>/<repo-name>"
git clone "<repo-url>" "<parent>/<repo-name>/main"
cd "<parent>/<repo-name>/main"
```

### Convert mode

Refuse to convert if the source clone:

- has uncommitted changes (`git status --porcelain` non-empty)
- has existing worktrees registered (`git worktree list` shows more than one)
- is already inside another worktree layout (parent dir already named like a repo with sibling worktrees)

Otherwise:

```bash
mkdir -p "<parent>/<repo-name>"
mv "<existing-clone>" "<parent>/<repo-name>/main"
cd "<parent>/<repo-name>/main"
```

### Add-main-copy mode

Used when the user wants `main.2`, `main.3`, etc. — local copies of the
default branch for trunk-based parallel work:

```bash
# From inside <repo>/main:
N=$(ls ../ | grep -E '^main(\.[0-9]+)?$' | wc -l)   # count existing main copies
git worktree add "../main.$((N+1))" main
```

The new worktree shares the same branch as `main`. This is intentional —
trunk-based flow lets two sessions iterate on the same branch with separate
working states. Use with care; coordinate which copy is "the one" that
pushes.

## Phase 3: Sanity check

```bash
git worktree list
```

The primary worktree should be `<repo-name>/main`. Any `main.N` copies
should appear with the same branch name as `main`.

## Phase 4: Tell the user what's next

```
✓ Layout ready at <parent>/<repo-name>/

Add a feature worktree:   /worktree-add <branch-name-or-issue-url>
Clean up merged worktrees: /worktree-cleanup
Add another main copy:    /worktree-setup (from inside <repo>/main)
```
