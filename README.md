# drift-fixer

A CLI tool that automatically detects and corrects Terraform/OpenTofu configuration
drift. It runs a plan, reads the before/after diff from the plan JSON, edits the
relevant `.tf` files in-place using the `hclwrite` AST library, and validates the
result with a second plan.

Written in Go. No external CLI tools required — HCL is edited directly via the
[hashicorp/hcl](https://github.com/hashicorp/hcl) library.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Building](#building)
- [Usage](#usage)
- [Environment Variables](#environment-variables)
- [Comment Hook](#comment-hook)
- [Supported Features](#supported-features)
- [Known Limitations](#known-limitations)
- [Testing](#testing)
- [Project Structure](#project-structure)

---

## How It Works

1. **Plan** — runs `tofu plan -out <tmp>` then `tofu show -json <tmp>` in the
   target directory. Reads `resource_changes[*].change.{before,after}` from the
   JSON output and diffs every attribute. Only attributes where `before != after`
   are collected into a `ResourceDrift`.

2. **Find** — parses every `.tf` file in the project directory using the
   `hclsyntax` AST to locate which file contains each drifted resource block.

3. **Edit** — opens the file with `hclwrite`, walks the block tree, and applies
   each drifted attribute:
   - Scalar attributes are set with `SetAttributeValue` / `SetAttributeRaw`.
   - List attributes with more than one item are formatted one-item-per-line.
   - Block-typed values (nested blocks) are recursively synced.
   - Resources deleted from infra are removed from config entirely.
   - The output is run through `hclwrite.Format` (equivalent to `tofu fmt`).

4. **Validate** — runs a second plan. If no drift remains, exits 0. If drift
   persists, exits 1 with a summary.

---

## Building

**Requirements**

- Go 1.22+ (`go version`)
- OpenTofu or Terraform CLI on `$PATH` (default: `tofu`)
- `GOTOOLCHAIN=local` is required because `go.mod` pins 1.22 while some
  transitive dependencies were built with a newer toolchain declaration.

```bash
# Clone
git clone <repo-url>
cd drift-fixer

# Build binary to project root
cd go
GOTOOLCHAIN=local go build -o ../drift-fixer-go ./cmd/drift-fixer/

# Verify
cd ..
./drift-fixer-go -h
```

The resulting binary `drift-fixer-go` is self-contained with no runtime
dependencies.

---

## Usage

```
./drift-fixer-go [flags]

Flags:
  -path string
        Path to the Terraform/OpenTofu project directory (default ".")
  -tf-bin string
        Terraform/OpenTofu binary to use (default "tofu", or $DRIFT_FIXER_TF_BIN)
  -verbose
        Print every attribute and block change as it is applied
  -dry-run
        Detect and report drift without writing any files
```

### Examples

```bash
# Fix drift in the current directory using tofu
./drift-fixer-go

# Fix a specific project directory
./drift-fixer-go -path ./infra/github

# Use terraform instead of tofu
./drift-fixer-go -tf-bin terraform

# Preview what would change without editing files
./drift-fixer-go -dry-run -verbose

# Verbose mode shows every attribute as it is applied
./drift-fixer-go -verbose
```

### Typical output

```
Starting drift analysis in: /home/user/infra/github
Using CLI binary: tofu
🔍 Running plan to detect drift...
📊 Found 2 resource(s) with drift:
  - github_repository_ruleset.main
  - github_repository.app

📝 Applying fixes...

  Syncing github_repository_ruleset.main in rulesets.tf
  ✅ Fixed github_repository_ruleset.main in rulesets.tf

  Syncing github_repository.app in repos.tf
  ✅ Fixed github_repository.app in repos.tf

✅ Validating...
✅ Drift fixing completed successfully! No remaining drift.
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DRIFT_FIXER_TF_BIN` | `tofu` | Terraform/OpenTofu binary to invoke |
| `DRIFT_FIXER_COMMENT_SCRIPT` | *(unset)* | Path to a script that generates inline HCL comments (see [Comment Hook](#comment-hook)) |

---

## Comment Hook

When `DRIFT_FIXER_COMMENT_SCRIPT` is set, drift-fixer calls that script for
every value it writes — both scalar attributes and individual list items. The
script can print a comment body to stdout; drift-fixer will attach it as an
inline `# comment` on that line.

Existing comments in the file are **always preserved** and take priority over
hook-generated comments. The hook only fires for values that have no existing
comment.

### Variables passed to the script

| Variable | Example |
|---|---|
| `DRIFT_RESOURCE_TYPE` | `github_repository_ruleset` |
| `DRIFT_RESOURCE_NAME` | `ruleset_main` |
| `DRIFT_ATTR_PATH` | `conditions.ref_name.include` |
| `DRIFT_ATTR_VALUE` | `"~DEFAULT_BRANCH"` *(rendered, so strings are quoted)* |

### Script contract

- Print a single line to **stdout** — the comment text, without `#`.
- Print **nothing** (or exit non-zero) to add no comment.
- Stderr is ignored (errors are logged in verbose mode only).

### Example script

```bash
#!/usr/bin/env bash
# Annotate GitHub branch patterns with a human-readable description

case "$DRIFT_ATTR_VALUE" in
  '"~DEFAULT_BRANCH"') echo "the default branch" ;;
  '"~ALL"')            echo "all branches" ;;
  '"refs/heads/releases/**/*"') echo "release branches" ;;
esac
```

With this script active, a synced `include` list might look like:

```hcl
include = [
  "~DEFAULT_BRANCH", # the default branch
  "refs/heads/releases/**/*", # release branches
  "refs/heads/meep",
]
```

---

## Supported Features

### Attribute types

| Type | Supported | Notes |
|---|---|---|
| String | ✅ | Any content including slashes, regex, special chars |
| Boolean | ✅ | |
| Integer | ✅ | Large integers (e.g. GitHub App IDs) rendered as integers, never scientific notation |
| Float | ✅ | |
| String list | ✅ | Multi-line for >1 item, single-line for 1 item |
| Number list | ✅ | Same formatting rules |
| Nested block | ✅ | Recursively synced to arbitrary depth |
| Repeated blocks | ✅ | e.g. multiple `bypass_actors {}` |
| Null value | ✅ | Silently skipped |

### Block operations

| Operation | Behaviour |
|---|---|
| Add missing block | If a block type is entirely absent from config, all instances from infra are added |
| Sync existing block | Attributes inside existing blocks are updated in-place |
| Remove excess blocks | If infra has fewer instances than config, the extra config blocks are removed |
| Preserve user-reduced count | If config has *fewer* blocks than infra, count is left alone (user is intentionally deleting them via Terraform) |
| Remove empty block type | If infra returns `[]` and config has blocks of that type, all are removed |
| Skip empty scalar list | If infra returns `[]` and no blocks of that type exist, it is ignored (not written as `= []`) |
| Delete resource | If a resource is deleted from infra (`actions: ["delete"]`), the entire `resource {}` block is removed from config |

### List formatting

```hcl
# Single item — stays on one line
topics = ["terraform"]

# Multiple items — one per line, `tofu fmt`-compliant indentation
topics = [
  "terraform",
  "go",
  "github",
]
```

### Comment preservation

Comments in list attributes survive drift syncs:

- **Before-line comments** (`# comment` on its own line before a value)
- **Inline comments** (`# comment` at the end of the same line as a value)
- **`//` style** comments
- Comments are keyed by **rendered value content**, not position — they follow
  their value even if the list is reordered or items are inserted before them.
- Comments for **removed items** are dropped.

```hcl
include = [
  # default branch — always included
  "~DEFAULT_BRANCH", # added automatically by provider
  "refs/heads/releases/**/*", # release train
]
```

### Resources tested against (GitHub provider)

| Resource | Notes |
|---|---|
| `github_repository` | `description`, `visibility`, `topics`, all boolean flags, `security_and_analysis` nested blocks, `squash_merge_commit_title/message`, `merge_commit_title/message` |
| `github_repository_ruleset` | `enforcement`, `target`, `conditions.ref_name.{include,exclude}`, `bypass_actors`, all `rules.*` sub-blocks listed below |
| `rules.pull_request` | `allowed_merge_methods`, `required_approving_review_count`, all boolean flags |
| `rules.required_status_checks` | `required_check` repeated blocks (add, remove, sync) |
| `rules.required_deployments` | `required_deployment_environments` list |
| `rules.branch_name_pattern` | `operator`, `pattern`, `name`, `negate` |
| `rules.tag_name_pattern` | same schema as `branch_name_pattern` |
| `rules.commit_message_pattern` | same schema |
| `rules.commit_author_email_pattern` | same schema |
| `rules.committer_email_pattern` | same schema |
| `rules.required_code_scanning` | `required_code_scanning_tool` repeated blocks |
| `rules.file_path_restriction` | `restricted_file_paths` list |
| `rules.file_extension_restriction` | `restricted_file_extensions` list |
| `rules.max_file_size` | `max_file_size` integer |
| `rules.max_file_path_length` | `max_file_path_length` integer |
| `rules.merge_queue` | all integer and string fields |

The tool is provider-agnostic — it works on any Terraform/OpenTofu resource. The
GitHub provider has been the primary test target.

---

## Known Limitations

- **Sensitive attributes** — attributes marked sensitive in the plan JSON are
  skipped (the provider redacts their values, so drift-fixer cannot know the
  correct value).
- **`after_unknown` attributes** — attributes whose post-change value is not
  known at plan time are skipped.
- **User-managed deletions** — if you have *intentionally* fewer blocks in your
  config than exist in infra (because you want Terraform to delete the extras on
  the next apply), drift-fixer will not add them back. It detects this by
  comparing config block count vs infra block count.
- **Multiple resources with the same type+name** — only the first match in a
  file is edited. This is a theoretical edge case since Terraform requires unique
  addresses.
- **`for_each` / `count` meta-arguments** — resources managed with `count` or
  `for_each` are located by address label. The tool edits the block body directly;
  it does not currently modify the `count` or `for_each` expression itself.
- **Comment hook is synchronous** — the script is exec'd once per value written.
  For large syncs with many list items, a slow script will slow the overall run.

---

## Testing

All tests are in `go/internal/editor/` and use only the standard library
(`testing` package). No real cloud credentials or live API calls are made.

```bash
# Run all tests (67 tests across 2 files)
cd go
GOTOOLCHAIN=local go test ./internal/editor/ -v

# Run a specific test
GOTOOLCHAIN=local go test ./internal/editor/ -v -run TestBypassActorModeChange

# Run all packages
GOTOOLCHAIN=local go test ./...
```

### Test files

| File | Count | Coverage |
|---|---|---|
| `editor_test.go` | 18 tests | Core edit operations, multi-line lists, comment preservation, hook |
| `editor_extended_test.go` | 49 tests | GitHub provider shapes, list mutations, deep nesting, every comment edge case, hook path verification |

### Integration test (`test.sh`)

Requires a real GitHub token and the `examples/` directory pointing at a live
repository:

```bash
# Set up credentials
echo 'export GITHUB_TOKEN=ghp_...' > .env

# Run full end-to-end: build → checkout clean main.tf → plan → fix → validate
./test.sh

# Dry run
./test.sh --dry-run
```

The script:
1. Builds the binary from source.
2. Resets `examples/main.tf` to HEAD with `git checkout`.
3. Runs `drift-fixer-go -path examples/ -verbose`.
4. Exits 0 only if the second plan confirms no remaining drift.

---

## Project Structure

```
drift-fixer/
├── drift-fixer-go          # compiled binary (gitignored)
├── test.sh                 # integration test script
├── examples/
│   └── main.tf             # test fixture (github provider resources)
└── go/
    ├── go.mod
    ├── go.sum
    ├── cmd/
    │   └── drift-fixer/
    │       └── main.go     # CLI entry point: flags, orchestration, validate
    └── internal/
        ├── planner/
        │   └── planner.go  # runs plan+show-json, diffs before/after, returns ResourceDrift list
        ├── finder/
        │   └── finder.go   # parses .tf AST to locate which file contains each resource
        └── editor/
            ├── editor.go       # hclwrite-based editor: ApplyDrift, RemoveResource, syncBody
            ├── hook.go         # CommentHook type + DRIFT_FIXER_COMMENT_SCRIPT loader
            ├── editor_test.go          # core unit tests (18)
            └── editor_extended_test.go # extended GitHub provider tests (49)
```

### Package responsibilities

**`planner`**
- Runs `<tf-bin> plan -out <tmp>` followed by `<tf-bin> show -json <tmp>`.
- Iterates `resource_changes` in the JSON output.
- For `delete` actions: returns `ResourceDrift{Delete: true}`.
- For `update`/`replace` actions: walks `change.before` vs `change.after`,
  collects every key where the values differ, skips sensitive keys and
  `after_unknown` markers.

**`finder`**
- Walks the project directory for `*.tf` files.
- Parses each file with `hclsyntax.ParseConfig` (full AST, no regex).
- Returns a map of `resourceAddress → filePath`.

**`editor`**
- `ApplyDrift` — main entry point; opens file, finds resource block, calls
  `syncBody`, writes formatted output.
- `RemoveResource` — removes the entire `resource {}` block.
- `syncBody` — recursive; handles empty lists, block vs scalar distinction,
  block count policy, path accumulation for hooks.
- `setAttributeVal` — scalar/list writer; extracts and re-injects comments;
  calls hook for values with no existing comment.
- `extractItemComments` — token-stream parser that maps rendered value string →
  `{before, inline}` comment tokens. Keyed by value content so comments survive
  list reordering.
- `multilineListTokens` — builds `hclwrite.Tokens` for a multi-line list,
  re-inserting preserved comments and hook-generated comments in the right spots.

**`hook`**
- `CommentHook` — function type `(rType, rName, path, value) → comment`.
- `LoadCommentHook` — reads `DRIFT_FIXER_COMMENT_SCRIPT`; returns a hook that
  exec's the script with context via env vars, or `nil` if unset.
