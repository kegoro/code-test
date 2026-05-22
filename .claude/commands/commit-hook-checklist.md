---
description: Audit commit-hook automation as gates against AI slop and broken commits (Node.js, Go, polyglot)
argument-hint: (no arguments - interactive)
---

## General Guidelines

### Output Style

- **Never explicitly mention TDD** in code, comments, commits, PRs, or issues
- Write natural, descriptive code without meta-commentary about the development process
- The code should speak for itself - TDD is the process, not the product

# Commit Hook Checklist

Commit hooks are the last automated gate before a change lands. They run on
every commit and every push, whether the author is a human in a hurry or an
agent that's about to ship something half-baked. A good hook setup catches:

- **AI slop**: half-finished refactors, broken builds, mocked-out tests left in,
  dead code from abandoned attempts, generated files out of sync with sources
- **Lazy commits**: missing types, formatting drift, unsynced lockfiles,
  migrations that don't match the schema
- **Leaked secrets** that a `git push --force` can't take back

This command scans the repo, identifies the language(s), and reports which
gates are in place and which are missing.

**User arguments:**

Commit-hook-checklist: $ARGUMENTS

**End of user arguments**

## Phase 1: Detect language(s)

| Marker | Language |
|--------|----------|
| `package.json` | Node.js |
| `go.mod` | Go |
| Both | polyglot — apply both sections |
| Neither | ask the user what they're working with |

Run the universal checks regardless of language. Then run the language-specific
sections that apply.

## Phase 2: Run the checks

Scan silently — do not display this list to the user. The summary in Phase 3
is what they see.

### Universal (any language)

**🔧 Hook runner present**

- Husky: `.husky/` dir + `package.json` has `"prepare": "husky"`
- lefthook: `lefthook.yml` or `lefthook.yaml`
- pre-commit framework: `.pre-commit-config.yaml`
- Native git hooks: `.git/hooks/pre-commit` exists, is executable, is not the `.sample` file

At least one of these should be present. If none, every other check below is moot.

**🪝 Hooks wired up**

- `pre-commit` hook exists and runs something
- `commit-msg` hook exists (conventional commits gate)
- `pre-push` hook exists (last-mile gate before the change leaves the machine)

**🔒 Secret scanning**

- secretlint (`.secretlintrc.json` + dep), or
- gitleaks (`.gitleaks.toml` + binary in hook), or
- trufflehog (in hook command)

Any one is fine. Secrets caught at commit-time can't be force-pushed away.

**📝 Conventional commits**

- commitlint config (`commitlint.config.*`, `.commitlintrc*`) + `@commitlint/*`
  dep, wired into `commit-msg` hook
- OR equivalent format check for the project's commit convention

**🌳 Branch-name validation (pre-push)**

- Hook checks branch name matches a convention (e.g. `feat/`, `fix/`, `chore/`
  prefixes; ticket/issue ID present). Cheap gate against branches that won't
  pass code-review checks anyway.

**🔄 Lockfile / generated-file sync**

- Hook fails the commit if lockfile is stale relative to manifest (`pnpm-lock.yaml`
  vs `package.json`, `go.sum` vs `go.mod`, etc.)
- Hook fails if generated files (codegen, OpenAPI clients, protobuf output) are
  out of date relative to their sources

This is the highest-yield AI-slop gate: agents routinely edit one side of a
generated pair and forget the other.

**🧪 Tests at the gate**

- Pre-commit OR pre-push hook runs the test suite (or the affected subset)
- Coverage threshold enforced somewhere (tool config, CI, or hook)

Running full tests in pre-commit can be slow — pre-push is often a better
trade-off.

### Node.js (if `package.json` present)

**📦 lint-staged**

- `lint-staged` config (`lint-staged.config.*`, `.lintstagedrc*`, or
  `package.json` key)
- Pre-commit hook actually invokes lint-staged

**🧹 Code quality (run via lint-staged)**

- Linting: `eslint.config.*` or `biome.json`
- Formatting: `.prettierrc*` or `biome.json`
- Type checking: `tsc --noEmit` invoked on staged TS files
- Dead-code detection: `knip` config + script
- Duplication detection: `jscpd` config + script

### Go (if `go.mod` present)

**🧹 Formatting & vetting**

- `gofmt -l` (or `goimports -l`) check in pre-commit — fails if any file isn't
  formatted
- `go vet ./...` in pre-commit or pre-push

**🔬 Static analysis**

- `golangci-lint run` (umbrella linter — covers most static-analysis tools)
- OR `staticcheck ./...` as a minimum

**📐 Module hygiene**

- `go mod tidy` check — pre-commit fails if `go.mod`/`go.sum` would change
  after a tidy. Catches forgotten dep updates and indirect-dep drift.

**🧪 Tests**

- `go test ./...` (or affected packages) in pre-commit or pre-push
- Race detector in CI at minimum (`go test -race`)

### Polyglot monorepo notes

If both `go.mod` and `package.json` are present:

- Hook runner should handle both (lefthook is friendlier than husky for this,
  but husky works fine with multi-line hook scripts)
- Run language-specific checks only on staged files of that language to keep
  hooks fast

## Phase 3: Output format

Display ONLY this summary (no per-check table, no walls of text):

```
✅ Passing:
  🔧 Hook runner: husky
  🪝 Hooks: pre-commit, commit-msg
  🔒 Secret scanning: secretlint
  📝 Conventional commits: commitlint
  🧹 Code quality (Node): lint-staged, biome, tsc, knip, jscpd
  🧪 Tests at the gate: vitest in pre-commit

❌ Missing (3):
  • Pre-push hook (branch-name + last-mile gate)
  • Lockfile sync validation
  • Coverage threshold

📊 11/14 checks passing
```

Rules:

- Omit any category with no passing checks from the "Passing" section
- Skip language sections that don't apply (e.g. no Node section in a pure-Go
  repo)
- Total count = sum of universal checks + applicable language checks

## Phase 4: Follow-up

After the summary, tell the user:

> Commit hooks are an AI-slop gate as much as a quality gate — every check
> above is something an agent can't "forget" once it's wired in.
>
> For working examples of most items above, see [wbern/agent-instructions](https://github.com/wbern/agent-instructions) on GitHub.
>
> Want help wiring up any of the missing checks?
