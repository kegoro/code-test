# Agent Teams Reference Guide

> Source: https://code.claude.com/docs/en/agent-teams
> Minimum version required: Claude Code v2.1.32+

---

## Quick Setup

Add to `.claude/settings.local.json` (already done for this project):

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

---

## What Are Agent Teams?

Multiple Claude Code instances working together. One session is the **team lead** — it coordinates, assigns tasks, and synthesizes results. **Teammates** work independently in their own context windows and can message each other directly.

**Key difference from subagents:** teammates communicate with each other directly. Subagents only report back to the main agent.

---

## Subagents vs Agent Teams

| | Subagents | Agent Teams |
|---|---|---|
| **Context** | Own window; results return to caller | Own window; fully independent |
| **Communication** | Report results to main agent only | Teammates message each other directly |
| **Coordination** | Main agent manages all work | Shared task list with self-coordination |
| **Best for** | Focused tasks where only the result matters | Complex work requiring discussion and collaboration |
| **Token cost** | Lower | Higher (each teammate is a separate Claude instance) |

**Rule of thumb:** Use subagents for quick, focused workers. Use agent teams when teammates need to share findings, challenge each other, and coordinate on their own.

---

## Best Use Cases

- **Parallel research/review** — multiple teammates investigate different aspects simultaneously
- **New modules/features** — each teammate owns a separate piece with no file overlap
- **Debugging with competing hypotheses** — teammates test different theories in parallel
- **Cross-layer work** — frontend, backend, and tests each owned by a different teammate

**Avoid agent teams for:** sequential tasks, same-file edits, work with heavy dependencies. Use a single session or subagents instead.

---

## Starting a Team

Just describe the task and structure in natural language:

```
Create an agent team to review PR #142. Spawn three reviewers:
- One focused on security implications
- One checking performance impact
- One validating test coverage
Have them each review and report findings.
```

Claude creates a shared task list, spawns teammates, coordinates work, and cleans up when finished.

---

## Architecture

| Component | Role |
|---|---|
| **Team lead** | Main Claude Code session — creates the team, spawns teammates, coordinates |
| **Teammates** | Separate Claude Code instances working on assigned tasks |
| **Task list** | Shared work items that teammates claim and complete |
| **Mailbox** | Messaging system between agents |

**Storage:**
- Team config: `~/.claude/teams/{team-name}/config.json`
- Task list: `~/.claude/tasks/{team-name}/`

> Do NOT hand-edit the team config — it gets overwritten on every state update.

---

## Display Modes

| Mode | How it works | Requirements |
|---|---|---|
| **in-process** (default) | All teammates run in your terminal; Shift+Down to cycle | Any terminal |
| **split-panes** | Each teammate gets its own pane | tmux or iTerm2 |

Set globally in `~/.claude.json`:
```json
{
  "teammateMode": "in-process"
}
```

Or per session:
```bash
claude --teammate-mode in-process
```

**Navigation (in-process mode):**
- `Shift+Down` — cycle through teammates
- `Enter` — view teammate's session
- `Escape` — interrupt current turn
- `Ctrl+T` — toggle task list

---

## Key Controls

### Specify teammates and model
```
Create a team with 4 teammates to refactor these modules in parallel.
Use Sonnet for each teammate.
```

### Require plan approval before implementation
```
Spawn an architect teammate to refactor the authentication module.
Require plan approval before they make any changes.
```
Lead reviews and approves/rejects plans autonomously. Influence the lead's judgment via prompt: "only approve plans that include test coverage."

### Assign tasks
- **Lead assigns explicitly:** tell the lead which task goes to which teammate
- **Self-claim:** teammates pick up the next unassigned unblocked task after finishing

### Shut down a teammate
```
Ask the researcher teammate to shut down
```

### Clean up the team
```
Clean up the team
```
Always use the lead to clean up. Shut down all teammates first, then clean up.

---

## Context and Communication

Teammates load:
- `CLAUDE.md` files from the working directory
- MCP servers and skills from project/user settings
- The spawn prompt from the lead

They do NOT inherit the lead's conversation history.

**Communication mechanisms:**
- `message` — send to one specific teammate by name
- `broadcast` — send to all teammates (use sparingly; cost scales with team size)
- Messages are delivered automatically — lead doesn't poll
- Idle teammates auto-notify the lead

---

## Using Subagent Definitions as Teammates

Define a role once (e.g., `security-reviewer`) and reuse it as either a subagent or a teammate:

```
Spawn a teammate using the security-reviewer agent type to audit the auth module.
```

The teammate honors the definition's `tools` allowlist and `model`. The definition's body is appended to the teammate's system prompt. `SendMessage` and task tools are always available regardless of `tools` restrictions.

> `skills` and `mcpServers` frontmatter fields are NOT applied to teammates — they load from project/user settings instead.

---

## Permissions

- Teammates start with the lead's permission settings
- If lead uses `--dangerously-skip-permissions`, all teammates do too
- Can change individual teammate modes after spawn, but not at spawn time
- Pre-approve common operations before spawning to reduce interruptions

---

## Hooks for Quality Gates

| Hook | Trigger | Exit code 2 effect |
|---|---|---|
| `TeammateIdle` | Teammate about to go idle | Send feedback, keep teammate working |
| `TaskCreated` | Task being created | Prevent creation, send feedback |
| `TaskCompleted` | Task being marked complete | Prevent completion, send feedback |

---

## Best Practices

### Team size
- **Start with 3–5 teammates** — balances parallelism with coordination overhead
- **5–6 tasks per teammate** keeps everyone productive
- Token costs scale linearly — each teammate has its own full context window
- More teammates ≠ faster work beyond a certain point

### Task sizing
- **Too small** — coordination overhead exceeds the benefit
- **Too large** — risk of wasted effort without check-ins
- **Just right** — self-contained units with a clear deliverable (a function, a test file, a review)

### Give teammates enough context
The lead's conversation history is NOT inherited. Include task-specific details in the spawn prompt:
```
Spawn a security reviewer teammate with this prompt: "Review src/auth/ for
security vulnerabilities. Focus on token handling, session management, and
input validation. The app uses JWT tokens in httpOnly cookies. Report issues
with severity ratings."
```

### Avoid file conflicts
Two teammates editing the same file = overwrites. Each teammate should own a different set of files.

### Monitor and steer
Don't let a team run unattended for too long. Check progress, redirect approaches that aren't working, synthesize findings as they come in.

### Wait for teammates before proceeding
If the lead starts implementing tasks itself:
```
Wait for your teammates to complete their tasks before proceeding
```

### Competing hypotheses pattern
For debugging unknown root causes, make teammates adversarial:
```
Spawn 5 teammates to investigate different hypotheses. Have them talk to each
other to try to disprove each other's theories. Update the findings doc with
whatever consensus emerges.
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Teammates not appearing | Press Shift+Down to check if they're running in-process; verify tmux is in PATH |
| Too many permission prompts | Pre-approve common operations in permission settings before spawning |
| Teammates stopping on errors | Give them additional instructions directly, or spawn a replacement |
| Lead shuts down too early | Tell the lead to keep going / wait for teammates |
| Orphaned tmux sessions | `tmux ls` then `tmux kill-session -t <name>` |
| Task status lagging | Check if work is done, update status manually or tell the lead to nudge the teammate |

---

## Known Limitations

- **No session resumption** — `/resume` and `/rewind` don't restore in-process teammates
- **Task status can lag** — teammates sometimes fail to mark tasks complete, blocking dependents
- **Slow shutdown** — teammates finish their current request before shutting down
- **One team per session** — clean up before starting a new team
- **No nested teams** — teammates cannot spawn their own teams; only the lead can
- **Lead is fixed** — can't transfer leadership to a teammate
- **Split panes not supported** in VS Code terminal, Windows Terminal, or Ghostty (use in-process instead)

---

## Prompting Patterns That Work Well

### Parallel code review
```
Create an agent team to review PR #142. Spawn three reviewers:
- One focused on security implications
- One checking performance impact
- One validating test coverage
```

### Competing hypotheses debug
```
Users report [bug]. Spawn 5 teammates to investigate different hypotheses.
Have them debate and try to disprove each other's theories.
Update findings.md with whatever consensus emerges.
```

### Research from multiple angles
```
I'm designing [system]. Create an agent team to explore this from different angles:
one on UX, one on technical architecture, one playing devil's advocate.
```

### Parallel feature implementation
```
Create a team with 4 teammates to implement these modules in parallel.
Each teammate owns a separate file set — no shared files.
Use Sonnet for each teammate.
```
