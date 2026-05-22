---
description: Bootstrap a new Gas Town installation, optionally with the wbern/gastown-me-and-my-crew preset for manual-mode operation
argument-hint: (no arguments - interactive)
---

## General Guidelines

### Output Style

- **Never explicitly mention TDD** in code, comments, commits, PRs, or issues
- Write natural, descriptive code without meta-commentary about the development process
- The code should speak for itself - TDD is the process, not the product

# Gas Town Setup

Bootstrap a new [Gas Town](https://github.com/steveyegge/gastown) installation —
the multi-agent workspace from Steve Yegge ([overview post](https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04)).

This command leans on the **upstream Gas Town docs** rather than duplicating
install steps that will drift. Your job is to walk the user through the
decision points and hand off to the canonical instructions at the right time.

## Phase 0: Prerequisite check

Verify the environment before suggesting anything:

| Check | Pass condition |
|-------|----------------|
| `gt` binary present | `command -v gt` succeeds |
| `tmux` present | `command -v tmux` succeeds |
| `~/gt/` absent or empty | First-time install only — don't clobber an existing town |

If `~/gt/` already exists and contains a `settings/` or `mayor/` dir, **stop**.
Show the user `gt status` and let them decide whether to repair, extend, or
nuke before reinstalling. Do not proceed past this point automatically.

If `gt` is missing, point the user at the install instructions in
[gastown/README](https://github.com/steveyegge/gastown#installation) and exit.

## Phase 1: Ask the user which flavor they want

Use `AskUserQuestion`:

**Question: "Which Gas Town flavor do you want to bootstrap?"** (header: "Flavor")

Options:

1. **Default (autonomous)** — "Out-of-the-box Gas Town with full autonomous patrols. Higher token burn, more emergent behavior."
2. **Manual mode (me-and-my-crew preset)** — "Apply the [wbern/gastown-me-and-my-crew](https://github.com/wbern/gastown-me-and-my-crew) preset: disables autonomous patrols, keeps crew workers only. Lower token burn, you drive the work."
3. **Skip preset for now** — "Just install default Gas Town. I can apply a preset later by visiting the preset repo."

Note for the user: the manual-mode preset is one config among many. It is the
maintainer's personal setup, shared **for friends who want the same defaults** —
not a required component of Gas Town. The preset can always be applied or
removed later.

## Phase 2: Default install

Regardless of preset choice, the underlying install is the same. Hand the user
off to the upstream quickstart:

> Follow the installation steps in
> [gastown/README](https://github.com/steveyegge/gastown#installation).
> Come back here once `gt up` succeeds and `gt status` shows the daemon
> running.

Don't re-paste the steps — they evolve, and the upstream docs are the source
of truth.

## Phase 3: Apply the me-and-my-crew preset (if chosen)

If the user picked option 2 in Phase 1, after the default install is up:

```bash
# 1. Clone the preset repo somewhere outside ~/gt/
git clone https://github.com/wbern/gastown-me-and-my-crew.git ~/gastown-presets/me-and-my-crew
cd ~/gastown-presets/me-and-my-crew

# 2. Follow the preset's own README for what to copy/merge into ~/gt/
#    (settings overrides, daemon tunings, disabled patrols, etc.)
cat README.md
```

Defer to the preset repo's instructions — it documents which files merge into
`~/gt/settings/` and `~/gt/mayor/`, and how to verify the tuning took effect.
Do not transcribe those steps here.

## Phase 4: CLAUDE.md interoperability note

Gas Town composes `CLAUDE.md` files at three levels and Claude Code reads all
of them. Worth understanding before the user starts customizing:

| Level | Path | Scope |
|-------|------|-------|
| Global | `~/.claude/CLAUDE.md` (or `~/.claude-accounts/<handle>/CLAUDE.md`) | Every project, every agent |
| Gas Town root | `~/gt/CLAUDE.md` | Every rig and crew member in this town |
| Rig | `~/gt/<rig>/CLAUDE.md` | Just that rig (committed to the rig's git history) |

Rig `CLAUDE.md` files should be **committed**, not gitignored — they're
shared instructions for anyone (human or agent) working in the repo.

Out of scope for this command, but worth knowing: instructions cascade, more
specific levels take precedence, and the rig-level file travels with the
project when others clone it.

## Phase 5: Verify

```bash
gt status                  # Daemon + services up?
gt prime                   # If you're in a crew session, fetch identity
gt mayor at                # Drop into the mayor's session to confirm it's alive
```

If anything looks off — daemon not running, services missing, mayor not
responding — the troubleshooting section in the upstream docs is more
current than anything I could write here.

## Phase 6: Tell the user what's next

```
✓ Gas Town installed at ~/gt/

Add your first rig:        gt rig add <repo-url>
Check status:              gt status
Open the mayor:            gt mayor at
Apply a different preset:  https://github.com/wbern/gastown-me-and-my-crew
                           (or write your own settings overrides)
```

---

**User arguments:**

Gastown-setup: $ARGUMENTS

**End of user arguments**
