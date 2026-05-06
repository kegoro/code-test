# Agent Teams: Patterns & Playbook

> Synthesized by a 3-teammate research team (Researcher + Strategist + Critic).
> Companion to `docs/agent-teams-reference.md`.
> Last updated: 2026-04-15

---

## Table of Contents

1. [Configuration Reference](#1-configuration-reference)
2. [Use Case Patterns](#2-use-case-patterns)
3. [Gaps & Recommendations](#3-gaps--recommendations)

---

## 1. Configuration Reference

Complete inventory of every documented configuration surface, organized by category.

### 1.1 Environment Variables

| Key | Value | Where to set |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `"1"` | `.claude/settings.local.json` under `"env"`, OR shell environment |

> **Caution:** "Experimental" means no stability guarantees between minor versions. The env var may be renamed or removed when the feature graduates. Treat this as unstable infrastructure.

### 1.2 Global Config Keys (`~/.claude.json`)

| Key | Values | Default | Notes |
|---|---|---|---|
| `teammateMode` | `"in-process"`, `"split-panes"`, `"auto"` | `"auto"` | `"auto"` uses split-panes if already in a tmux session, in-process otherwise |

**Example:**
```json
{
  "teammateMode": "in-process"
}
```

> **Known gap:** What happens if `split-panes` is set on an unsupported terminal (VS Code, Windows Terminal, Ghostty)? The docs don't say whether it silently falls back to in-process or throws an error.

### 1.3 CLI Flags

| Flag | Effect | Scope |
|---|---|---|
| `--teammate-mode in-process` | Forces in-process mode for this session | Per-session only |
| `--teammate-mode split-panes` | Forces split-pane mode for this session | Per-session only |

> **Known gap:** Precedence between `--teammate-mode` and `~/.claude.json` is undocumented. Assume CLI flag wins, but verify.

### 1.4 Minimum Version

```
Claude Code v2.1.32+
```

Check: `claude --version`

### 1.5 Display Modes

| Mode | How to Activate | Terminal Requirements | Not Supported In |
|---|---|---|---|
| **in-process** (default) | Default, or `"auto"` outside tmux, or `--teammate-mode in-process` | Any terminal | — |
| **split-panes** | `"auto"` inside tmux, or `"split-panes"`, or `--teammate-mode split-panes` | tmux OR iTerm2 with `it2` CLI | VS Code terminal, Windows Terminal, Ghostty |

**Split-panes setup:**
- **tmux:** install via system package manager; run `tmux -CC` in iTerm2 for best results
- **iTerm2:** install [`it2` CLI](https://github.com/mkusaka/it2); enable Python API in iTerm2 → Settings → General → Magic

### 1.6 Navigation Controls (in-process mode)

| Key | Effect |
|---|---|
| `Shift+Down` | Cycle through teammates (wraps after last teammate back to lead) |
| `Enter` | View a teammate's session |
| `Escape` | Interrupt a teammate's current turn |
| `Ctrl+T` | Toggle the shared task list |

> **Tip:** If teammates aren't appearing, press `Shift+Down` — they may already be running in-process.

### 1.7 Hooks

| Hook Name | Fires When | Exit Code 2 Effect |
|---|---|---|
| `TeammateIdle` | A teammate is about to go idle | Send feedback to keep the teammate working |
| `TaskCreated` | A task is being created | Prevent creation and send feedback |
| `TaskCompleted` | A task is being marked complete | Prevent completion and send feedback |

**Hook configuration location:** `.claude/settings.json` or `.claude/settings.local.json` under `"hooks"`.

> **Known gap:** The docs list these hooks with no code examples. What a `TeammateIdle` hook script looks like, and exactly how exit code 2 "sends feedback," is completely undocumented. See [Section 3](#3-gaps--recommendations) for recommended additions.

### 1.8 Storage Locations

| Item | Path | Notes |
|---|---|---|
| Team config | `~/.claude/teams/{team-name}/config.json` | Auto-generated; do NOT hand-edit — overwritten on every state update |
| Task list | `~/.claude/tasks/{team-name}/` | Shared across all teammates |

**What the team config contains** (documented in SDK, not in reference):
- `members` array with each teammate's `name`, `agentId`, `agentType`
- Runtime state: session IDs, tmux pane IDs
- Always reference teammates by `name`, not by `agentId`

> **Known gap:** The config schema is never shown in the reference doc. The `{team-name}` token is never explained — is it user-defined at spawn time or auto-generated? How do you reference a specific team if you have multiple?

### 1.9 Permissions Behavior

| Scenario | Behavior |
|---|---|
| Lead has default permissions | Teammates inherit those permissions at spawn time |
| Lead uses `--dangerously-skip-permissions` | ALL teammates also skip permissions |
| Change teammate permissions after spawn | Possible (mode change per teammate) |
| Set per-teammate permissions at spawn time | NOT possible |

> **Best practice:** Pre-approve common operations in permission settings before spawning teammates to avoid repeated prompts interrupting parallel work.
>
> **Known gap:** The mechanism for changing individual teammate permissions post-spawn is not documented — no example command or UI flow is shown.

### 1.10 Task Management

| Feature | Behavior |
|---|---|
| Lead-assigned tasks | Lead explicitly tells a specific teammate to take a task |
| Self-claim | After finishing a task, a teammate picks up the next unassigned, unblocked task |
| Task dependencies | Tasks can be blocked by other tasks; auto-unblock when dependency completes |
| Task status lag | Known issue: teammates sometimes fail to mark tasks complete, blocking dependents — nudge manually if stuck |
| Recommended load | 5–6 tasks per teammate |

> **Known gap:** How task dependencies are encoded (file format, syntax) is never explained. "Blocked tasks" is mentioned but the encoding mechanism is absent.

### 1.11 Communication Primitives

| Primitive | Behavior | Cost |
|---|---|---|
| `message` | Send to one specific teammate by name | Scales with message size |
| `broadcast` | Send to all teammates simultaneously | Scales **linearly with team size** — use sparingly |
| Auto-delivery | Messages delivered automatically — lead does NOT poll | — |
| Idle notifications | Teammates auto-notify lead when they go idle | — |

> **Known gap:** What happens if a message is sent to a teammate that has already shut down? Is there a queue depth limit? Are messages ordered? Mailbox mechanics are undocumented.
>
> **Known gap:** If the lead is mid-turn when an idle notification arrives, is it queued, dropped, or does it interrupt? Not documented.

### 1.12 Subagent Definitions as Teammates

Reuse a subagent definition (e.g., a file in `.claude/agents/`) as a teammate by name:

```
Spawn a teammate using the security-reviewer agent type to audit the auth module.
```

| Field in subagent definition | Applied to teammate? |
|---|---|
| `tools` allowlist | YES — honored |
| `model` | YES — honored |
| Definition body (system prompt) | YES — appended to teammate's system prompt |
| `skills` frontmatter | NO — loads from project/user settings instead |
| `mcpServers` frontmatter | NO — loads from project/user settings instead |

**`SendMessage` and task tools are always available** to a teammate regardless of `tools` restrictions.

**What every teammate loads:**
- `CLAUDE.md` from their working directory
- MCP servers and skills from project/user settings
- The spawn prompt from the lead

**What teammates do NOT inherit:**
- The lead's conversation history

### 1.13 Known Limitations (Complete List)

| Limitation | Impact |
|---|---|
| No session resumption | `/resume` and `/rewind` don't restore in-process teammates — mid-task crashes are unrecoverable |
| Task status can lag | Blocking dependents; may need manual update or lead nudge |
| Slow shutdown | Teammates finish their current request before shutting down |
| One team per session | Clean up before starting a new team |
| No nested teams | Only the lead can spawn teammates; teammates cannot spawn sub-teams |
| Lead is fixed | No leadership transfer to a teammate |
| Split panes limited | Not supported in VS Code terminal, Windows Terminal, or Ghostty |
| Permissions set at spawn | Can change post-spawn but not at spawn time |

---

## 2. Use Case Patterns

Five real-world scenarios where agent teams clearly outperform a single session or subagents. Ordered from most proven to most creative.

---

### Pattern 1: Parallel Domain-Specific Code Review

**Scenario:** A security-critical PR or entire codebase needs thorough review across multiple domains simultaneously. A single reviewer anchors on one issue type; simultaneous specialists don't.

**Why agent teams beat alternatives:** Serialized review anchors on the first finding. Parallel specialists each apply a different filter to the same code — a compound vulnerability visible only from two angles (e.g., weak auth + unauthenticated endpoint) gets caught by the Coordinator's cross-reference step, which a single pass misses entirely.

**When to use this:** Codebase or PR is large enough that one reviewer would take >30 min. The domains are meaningfully distinct (security, performance, test coverage). **Do NOT use for PRs under ~200 lines** — the coordination overhead exceeds the benefit.

**Recommended team structure (security audit example):**
| Role | Model | Responsibility |
|---|---|---|
| Coordinator | claude-opus-4-6 | Divides codebase, deduplicates findings, synthesizes report |
| Auth Auditor | claude-sonnet-4-6 | Authentication, session management, token handling |
| Injection Auditor | claude-sonnet-4-6 | SQL/command injection, deserialization |
| API Surface Auditor | claude-sonnet-4-6 | Endpoints, input validation, rate limiting |
| Dependency Auditor | claude-haiku-4-5 | Package manifests, known-vulnerable versions |

**Workflow:**
1. Coordinator reads repo structure, divides into domains, spawns specialists with scoped file lists
2. Each specialist receives a spawn prompt like: *"Review only files in `/auth/**`. Report every finding with file:line citations and severity. Return structured JSON, not prose."*
3. Specialists run in parallel, each producing a JSON findings list
4. Specialists send results to Coordinator
5. Coordinator cross-references for compound vulnerabilities, deduplicates by file:line, produces final report

**Pitfalls:**
- Specialists overlap on shared utility files → Coordinator must deduplicate by `file:line`
- Hallucinated CVEs → instruct specialists to only cite findings with direct code evidence
- Token bloat on lead → require structured JSON responses, not prose summaries

---

### Pattern 2: Competing Hypotheses Debugging

**Scenario:** A bug's root cause is genuinely unknown across multiple subsystems. A single agent tends to anchor on the first plausible theory and stop looking.

**Why agent teams beat alternatives:** Sequential investigation suffers from anchoring bias. Teammates explicitly assigned to *disprove* each other's theories resist this bias. The hypothesis that survives adversarial pressure is much more likely to be the actual root cause.

**When to use this:** Root cause is unknown AND could plausibly be in multiple subsystems. **Do NOT use when** a stack trace points directly to a single function — that warrants a single focused session.

**Recommended team structure:**
| Role | Model | Responsibility |
|---|---|---|
| Lead | claude-sonnet-4-6 | Assigns hypotheses, collects consensus, writes findings doc |
| Investigator x3–5 | claude-sonnet-4-6 | Each investigates one theory; actively tries to disprove others |

**Workflow:**
1. Lead identifies 3–5 plausible hypotheses, assigns one to each Investigator
2. Each Investigator receives a spawn prompt like: *"Investigate whether [hypothesis]. Actively message the other investigators with evidence that challenges their theories."*
3. Investigators work independently, messaging each other directly with counter-evidence
4. Lead monitors the debate, identifies emerging consensus
5. Lead writes `findings.md` once consensus emerges

**Pitfalls:**
- **File write conflict:** if teammates are instructed to update a shared `findings.md`, two will overwrite each other. Instead, have each teammate write to their own `findings-[name].md` and let the lead merge
- "Debate" produces noise without convergence → Lead should intervene and ask for a single ranked-confidence list after N rounds
- Teammates without `SendMessage` capability can't debate → relay through lead if needed

---

### Pattern 3: Parallel Full-Stack Feature Implementation

**Scenario:** A new feature spans database schema, backend API, frontend component, and test suite — workstreams that are independent once an interface contract is established.

**Why agent teams beat alternatives:** Sequential subagents serialize work that can be parallel. An agent team agrees on the API contract first, then all workstreams run simultaneously, with a Reviewer catching integration mismatches before human review.

**Critical prerequisite:** Each teammate must own completely non-overlapping files. Two teammates editing the same file will cause overwrites.

**Recommended team structure:**
| Role | Model | Files Owned |
|---|---|---|
| Tech Lead | claude-opus-4-6 | OpenAPI spec, DB schema |
| Backend Engineer | claude-sonnet-4-6 | Migrations, API endpoints |
| Frontend Engineer | claude-sonnet-4-6 | React components, API client |
| QA Engineer | claude-sonnet-4-6 | Test files only |
| Reviewer | claude-sonnet-4-6 | Read-only; validates spec compliance |

**Workflow:**
1. Tech Lead reads existing codebase conventions, drafts the OpenAPI spec and DB schema
2. Tech Lead broadcasts the spec to Backend, Frontend, and QA simultaneously
3. All three implement in parallel; QA writes tests against the spec (not the implementation)
4. All three send completed work to Tech Lead
5. Tech Lead spawns Reviewer: *"Check that backend endpoints exactly match the OpenAPI spec, frontend calls match the spec, and tests cover all spec-defined error codes."*
6. Reviewer returns a diff of mismatches; Tech Lead routes fixes

**Pitfalls:**
- API contract drift: if Backend changes an endpoint signature, Frontend breaks silently → enforce "no spec changes without broadcast" as a rule in the Tech Lead's spawn prompt
- Frontend agent assumes auth token format → include auth conventions explicitly in the spawn prompt
- Reviewer must have the original spec in context (not just implementations) to catch omissions

---

### Pattern 4: Parallel Literature or Data Synthesis

**Scenario:** A large corpus (150 research papers, 50 competitor reports, 30 audit logs) needs structured extraction followed by cross-corpus synthesis. Too large for one context window; too structured to summarize loosely.

**Why agent teams beat alternatives:** A single session cannot hold the corpus. Sequential subagents require human re-aggregation, reintroducing the bottleneck automation was meant to eliminate. Parallel Reader agents return structured data to a Synthesizer — the synthesis is the value, and it requires all corpus data at once.

**Recommended team structure (meta-analysis example):**
| Role | Model | Responsibility |
|---|---|---|
| Coordinator | claude-opus-4-6 | Defines extraction schema, divides corpus, runs synthesis |
| Reader x10 | claude-haiku-4-5 | Each reads ~15 papers, extracts to JSON schema |
| Quality Screener | claude-sonnet-4-6 | Scores methodology independently (prevents confirmation bias) |
| Statistician | claude-sonnet-4-6 | Receives all extracted data, runs aggregation + contradiction analysis |

**Workflow:**
1. Coordinator defines extraction schema: `{id, effect_size, ci, population_n, methodology_score, contradicts[]}`
2. Coordinator sends 15-paper batches to each Reader + Quality Screener runs in parallel on same batches
3. All return structured JSON to Coordinator
4. Coordinator passes full dataset to Statistician
5. Statistician computes pooled effect size, identifies outliers and contradictions
6. Coordinator formats final report

**Pitfalls:**
- Readers interpret ambiguous tables differently → Coordinator should include 1–2 worked extraction examples in the spawn prompt
- Output is AI-extracted data → final report must state this limitation explicitly
- Haiku models miss nuanced methodology flaws → Quality Screener (Sonnet) provides the independent check

---

### Pattern 5: Multi-Profile Content Generation

**Scenario:** The same conceptual content must be adapted for multiple distinct audiences simultaneously (e.g., beginner/intermediate/expert, consumer/enterprise/developer). A single session writing for all profiles produces averaged, mediocre content for none.

**Why agent teams beat alternatives:** Profile-specific writers running in parallel produce genuinely tailored content in the time it takes to produce one profile sequentially. A shared Curriculum Designer ensures conceptual consistency across profiles — something sequential subagents don't provide.

**Recommended team structure (statistics course example):**
| Role | Model | Responsibility |
|---|---|---|
| Curriculum Designer | claude-opus-4-6 | Concept map, learning objectives, assessment rubrics |
| Profile Writer x3 | claude-sonnet-4-6 | One writer per audience profile |
| Factual Reviewer | claude-sonnet-4-6 | Verifies accuracy across all profiles |
| Assessment Designer | claude-haiku-4-5 | Quiz banks and capstone project specs per profile |

**Workflow:**
1. Curriculum Designer defines the concept map and learning objectives per topic per profile
2. Curriculum Designer broadcasts to all Writers and Assessment Designer simultaneously
3. Each Writer produces their full module (explanations + worked examples)
4. Assessment Designer produces quiz banks per profile
5. All send content to Curriculum Designer
6. Factual Reviewer checks accuracy and cross-profile consistency
7. Corrections routed; Curriculum Designer assembles final modules

**Pitfalls:**
- Writers diverge on fundamental definitions → include canonical definitions (e.g., p-value interpretation) in the spawn prompt
- Assessment Designer misaligned with content depth → Assessment Designer should receive completed content, not just the objectives
- Graduate-level writer produces technically correct but pedagogically unusable content → specify "explanatory, not terse" in spawn prompt

---

### When NOT to Use Agent Teams

| Scenario | Use Instead |
|---|---|
| PR under ~200 lines | Single thorough review session |
| Bug with stack trace pointing to one function | Single focused debug session |
| Brainstorming / perspective-gathering | Single session with explicit perspective-switching |
| Sequential tasks with strong dependencies | Subagents (serial) or single session |
| Same-file edits across the team | Refactor the work breakdown so each teammate owns distinct files |
| Short tasks where coordination overhead > task time | Single session or subagents |

---

## 3. Gaps & Recommendations

Critical analysis of what's missing or unclear in the current documentation and patterns. Prioritized for actionability.

---

### 3.1 HIGH Priority — Blocks Correct Usage

**1. Teammate naming is unexplained**

The docs reference teammates by name throughout ("ask the researcher teammate to shut down") but never explain:
- How are names assigned? User-defined at spawn time? Auto-generated?
- Can two teammates have the same name?
- How do you reference a teammate by name in a prompt?

**Recommended addition:** Add a section to the reference doc explaining that the lead assigns names at spawn time, names must be unique within a team, and that you should explicitly name teammates in your spawn instruction if you want predictable names.

---

**2. Plan approval flow is a black box**

The reference says "lead reviews and approves/rejects plans autonomously" — but:
- Does the user ever see the plan before the lead approves it?
- Can the lead silently approve a bad plan without any user checkpoint?
- "Influence the lead's judgment via prompt" suggests the user is out of the loop

**Recommended addition:** Explicitly document when the user is vs. isn't in the approval loop. Add an example showing how to configure the lead to require user confirmation before plan approval.

---

**3. No failure recovery guidance**

The Known Limitations section notes that `/resume` doesn't restore teammates, but gives no mitigation strategy. A 2-hour parallel task that crashes at 90% is currently a complete loss.

**Recommended addition:** A "Failure Recovery" section with:
- Checkpoint pattern: have teammates write intermediate results to files at task completion, not just in their context window
- Re-run pattern: how to spawn replacement teammates and hand them context from completed steps
- Task-size guidance specifically for long-running work (smaller units = smaller blast radius)

---

**4. File conflict in "competing hypotheses" pattern**

The reference's own canonical example ("update the findings doc with whatever consensus emerges") creates an exact write conflict it warns against elsewhere. Two teammates updating the same file simultaneously = silent overwrite.

**Recommended fix:**
- Change the example to have each teammate write to their own `findings-[teammate-name].md`
- Lead merges at synthesis step
- Add this as an explicit rule in the "Avoid file conflicts" best practice section

---

**5. Lead token exhaustion is unaddressed**

The docs mention "token costs scale linearly" for teammates but never address the compounding cost on the lead's synthesis step. On a 5-teammate team, receiving detailed reports from each can exhaust the lead's context window before synthesis completes.

**Recommended addition:** Instruct teammates to return structured JSON or bulleted summaries rather than prose — keep lead context budget available for synthesis. Add this to the "Give teammates enough context" best practice.

---

### 3.2 MEDIUM Priority — Causes Confusion and Wasted Resources

**6. Team size and task count guidance is inconsistent**

"Start with 3–5 teammates" and "5–6 tasks per teammate" are given independently. They imply very different total task counts (15 tasks vs. 30 tasks) with no guidance on when each applies.

**Recommended addition:** A workload-sizing table:
| Workload size | Recommended team | Tasks per teammate |
|---|---|---|
| Small (1–5 files, < 1 hour) | 2–3 teammates | 3–4 tasks each |
| Medium (5–20 files, 1–3 hours) | 3–4 teammates | 5–6 tasks each |
| Large (20+ files, 3+ hours) | 4–5 teammates | 5–6 tasks each, with checkpointing |

---

**7. "Parallel code review" threshold missing**

The reference presents PR review as a canonical use case with no size threshold. Applied to a 50-line PR, the overhead of spawning 3 teammates exceeds the value entirely.

**Recommended addition:** Add an explicit guidance line: "Agent teams for code review are most effective when the PR or scope is large enough that a single thorough reviewer would take more than 20–30 minutes."

---

**8. Hook section is completely inactionable**

The hooks table lists `TeammateIdle`, `TaskCreated`, `TaskCompleted` with no example code. "Exit with code 2 to send feedback" doesn't explain where the feedback goes, what format it should be in, or how to write the hook script.

**Recommended addition:** At minimum, one concrete shell script example:
```bash
#!/bin/bash
# TeammateIdle hook — enforce tests before idle
INPUT=$(cat)
TEAMMATE=$(echo "$INPUT" | jq -r '.teammate_name')
echo "Checking if $TEAMMATE ran tests before going idle..." >&2
# Check task list or message content here
# Exit 2 with a message to keep the teammate working:
echo '{"feedback": "Run the test suite before going idle."}'
exit 2
```

---

**9. `teammateMode` fallback behavior on unsupported terminals is undocumented**

If a user sets `"teammateMode": "split-panes"` in `~/.claude.json` and then opens Claude Code in VS Code's integrated terminal, what happens? Silent fallback? Error? Crash?

**Recommended addition:** Document the fallback behavior explicitly (expected: silent fallback to in-process).

---

**10. Per-teammate permission change mechanism is undocumented**

The reference says you can change individual teammate modes after spawn but never shows how.

**Recommended addition:** Show the natural language command or mechanism: e.g., "To change a teammate's permission mode after spawning: [command or UI flow]."

---

### 3.3 LOW Priority — Quality Improvements

**11. "Research from multiple angles" example uses unhelpful placeholder**

The canonical example uses `[system]` as a placeholder. This tells a practitioner nothing about what the UX or architecture teammate actually does or returns.

**Recommended fix:** Replace with a concrete example: "I'm building a CLI tool for tracking TODO comments across a codebase" — then show what each teammate's spawn prompt actually looks like.

---

**12. "Parallel code review" and "Parallel feature implementation" are structurally identical**

Both patterns are: spawn N teammates → divide work → collect results. They differ only in artifact type.

**Recommended fix:** Consolidate into one "Parallel Workload" pattern with variants, or explicitly call out the structural similarity and explain why they're listed separately.

---

**13. Missing use case domains**

The following high-value patterns are entirely absent from the reference:
- **Incremental migration** — migrate a codebase module-by-module; each teammate owns a module (natural file ownership, no conflicts)
- **Multi-environment testing** — run integration tests across staging, production-mirror, and canary simultaneously
- **Documentation generation** — one teammate per module generates docs; lead synthesizes unified reference

---

**14. Stability disclaimer absent**

The `EXPERIMENTAL` env var, `v2.1.32+` minimum, and keyboard shortcuts are all likely to change. The doc should include a version-awareness note so practitioners know which parts to re-verify on upgrade.

---

**15. "Don't run unattended for too long" tension is unresolved**

The docs sell agent teams on autonomous parallel work but then warn against leaving them unattended. "How long is too long?" is never answered.

**Recommended addition:** Define "monitoring" concretely — e.g., check in every 10–15 minutes on tasks over an hour; use `Shift+Down` to scan each teammate's last action.

---

### 3.4 Summary Table

| # | Issue | Priority | Effort to fix |
|---|---|---|---|
| 1 | Teammate naming unexplained | HIGH | Low — 1 paragraph |
| 2 | Plan approval black box | HIGH | Medium — needs design clarification |
| 3 | No failure recovery guidance | HIGH | Medium — new section |
| 4 | File conflict in canonical example | HIGH | Low — fix one example |
| 5 | Lead token exhaustion unaddressed | HIGH | Low — 1 bullet in best practices |
| 6 | Team size / task count inconsistency | MEDIUM | Low — add sizing table |
| 7 | Code review threshold missing | MEDIUM | Low — 1 sentence |
| 8 | Hooks section inactionable | MEDIUM | Medium — add 1 example script |
| 9 | `split-panes` fallback undocumented | MEDIUM | Low — 1 sentence |
| 10 | Per-teammate permission change undocumented | MEDIUM | Low — 1 example |
| 11 | Placeholder in canonical example | LOW | Low — swap in concrete example |
| 12 | Duplicate structural patterns | LOW | Low — consolidate or note |
| 13 | Missing use case domains | LOW | Medium — add 2–3 patterns |
| 14 | No stability/version disclaimer | LOW | Low — 1 note |
| 15 | "Unattended" guidance too vague | LOW | Low — 1 sentence |
