package editor

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// applyDriftToString is a test helper that writes input HCL to a temp file,
// calls ApplyDrift, and returns the resulting file content.
func applyDriftToString(t *testing.T, inputHCL string, rType, rName string, drifted map[string]interface{}) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "main.tf")
	if err := os.WriteFile(path, []byte(inputHCL), 0644); err != nil {
		t.Fatalf("write temp file: %v", err)
	}
	_, err := ApplyDrift(path, rType, rName, drifted, false)
	if err != nil {
		t.Fatalf("ApplyDrift: %v", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read result: %v", err)
	}
	return string(out)
}

func removeResourceFromString(t *testing.T, inputHCL string, rType, rName string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "main.tf")
	if err := os.WriteFile(path, []byte(inputHCL), 0644); err != nil {
		t.Fatalf("write temp file: %v", err)
	}
	removed, err := RemoveResource(path, rType, rName)
	if err != nil {
		t.Fatalf("RemoveResource: %v", err)
	}
	if !removed {
		t.Fatal("RemoveResource returned false — block not found")
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read result: %v", err)
	}
	return string(out)
}

// assertContains fails if substr is not found in s.
func assertContains(t *testing.T, s, substr string) {
	t.Helper()
	if !strings.Contains(s, substr) {
		t.Errorf("expected output to contain:\n  %q\ngot:\n%s", substr, s)
	}
}

// assertNotContains fails if substr IS found in s.
func assertNotContains(t *testing.T, s, substr string) {
	t.Helper()
	if strings.Contains(s, substr) {
		t.Errorf("expected output NOT to contain:\n  %q\ngot:\n%s", substr, s)
	}
}

// ---------------------------------------------------------------------------
// Scalar attribute tests
// ---------------------------------------------------------------------------

func TestUpdateExistingScalar(t *testing.T) {
	input := `
resource "github_repository" "repo" {
  description = "old"
}
`
	out := applyDriftToString(t, input, "github_repository", "repo",
		map[string]interface{}{"description": "new value"})

	assertContains(t, out, `description = "new value"`)
	assertNotContains(t, out, `"old"`)
}

func TestAddMissingScalar(t *testing.T) {
	input := `
resource "github_repository" "repo" {
  name = "my-repo"
}
`
	out := applyDriftToString(t, input, "github_repository", "repo",
		map[string]interface{}{"description": "added"})

	assertContains(t, out, `description = "added"`)
}

func TestLargeIntegerNoScientificNotation(t *testing.T) {
	// Regression: actor_id was written as 1.236702e+06
	input := `
resource "github_repository_ruleset" "rs" {
  bypass_actors {
    actor_id    = 0
    bypass_mode = "always"
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"bypass_actors": []interface{}{
				map[string]interface{}{
					"actor_id":    float64(1236702),
					"bypass_mode": "always",
				},
			},
		})

	assertContains(t, out, "actor_id    = 1236702")
	assertNotContains(t, out, "1.236702e")
}

func TestBooleanValues(t *testing.T) {
	input := `
resource "github_repository" "repo" {
  has_issues = true
}
`
	out := applyDriftToString(t, input, "github_repository", "repo",
		map[string]interface{}{"has_issues": false})

	assertContains(t, out, "has_issues = false")
}

// ---------------------------------------------------------------------------
// Nested block tests
// ---------------------------------------------------------------------------

func TestAddMissingNestedBlock(t *testing.T) {
	// Regression: required_status_checks was not being created inside rules {}
	input := `
resource "github_repository_ruleset" "rs" {
  rules {
    deletion = true
    pull_request {
      required_approving_review_count = 1
    }
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"rules": map[string]interface{}{
				"deletion": true,
				"required_status_checks": map[string]interface{}{
					"do_not_enforce_on_create": false,
					"required_check": map[string]interface{}{
						"context":        "ci/test",
						"integration_id": float64(0),
					},
				},
			},
		})

	assertContains(t, out, "required_status_checks {")
	assertContains(t, out, `context        = "ci/test"`)
}

func TestUpdateScalarInsideExistingBlock(t *testing.T) {
	input := `
resource "github_repository_ruleset" "rs" {
  rules {
    deletion = false
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"rules": map[string]interface{}{
				"deletion": true,
			},
		})

	assertContains(t, out, "deletion = true")
}

// ---------------------------------------------------------------------------
// Repeated block tests
// ---------------------------------------------------------------------------

func TestAddTwoRepeatedBlocks(t *testing.T) {
	// Block type absent from config — both instances should be added.
	input := `
resource "github_repository_ruleset" "rs" {
  name = "main"
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"bypass_actors": []interface{}{
				map[string]interface{}{"actor_id": float64(100), "bypass_mode": "always"},
				map[string]interface{}{"actor_id": float64(200), "bypass_mode": "always"},
			},
		})

	if strings.Count(out, "bypass_actors {") != 2 {
		t.Errorf("expected 2 bypass_actors blocks, got:\n%s", out)
	}
	assertContains(t, out, "= 100")
	assertContains(t, out, "= 200")
}

func TestRemoveExcessRepeatedBlock(t *testing.T) {
	// Regression: config has 2 bypass_actors, infra now has 1 — excess should
	// be removed and the remaining one synced.
	input := `
resource "github_repository_ruleset" "rs" {
  bypass_actors {
    actor_id    = 100
    bypass_mode = "always"
  }
  bypass_actors {
    actor_id    = 200
    bypass_mode = "always"
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"bypass_actors": []interface{}{
				map[string]interface{}{"actor_id": float64(100), "bypass_mode": "exempt"},
			},
		})

	if strings.Count(out, "bypass_actors {") != 1 {
		t.Errorf("expected 1 bypass_actors block, got:\n%s", out)
	}
	assertContains(t, out, `bypass_mode = "exempt"`)
}

func TestEmptyListRemovesExistingBlocks(t *testing.T) {
	// Regression: when infra has no bypass_actors (plan returns []),
	// existing config blocks should be removed.
	input := `
resource "github_repository_ruleset" "rs" {
  bypass_actors {
    actor_id    = 100
    bypass_mode = "always"
  }
  bypass_actors {
    actor_id    = 200
    bypass_mode = "always"
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"bypass_actors": []interface{}{},
		})

	assertNotContains(t, out, "bypass_actors")
}

func TestEmptyListNoBlocksIsNoop(t *testing.T) {
	// Empty list from plan when no config blocks exist = no-op (not a scalar attr).
	input := `
resource "github_repository_ruleset" "rs" {
  name = "main"
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"branch_name_pattern": []interface{}{},
		})

	assertNotContains(t, out, "branch_name_pattern")
}

func TestUserIntentionallyFewerBlocksThanInfra(t *testing.T) {
	// Config has 1 bypass_actor, infra has 2 — user intentionally has fewer
	// (wants to delete one). Tool should only update index[0], not add index[1].
	input := `
resource "github_repository_ruleset" "rs" {
  bypass_actors {
    actor_id    = 100
    bypass_mode = "always"
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"bypass_actors": []interface{}{
				map[string]interface{}{"actor_id": float64(100), "bypass_mode": "exempt"},
				map[string]interface{}{"actor_id": float64(200), "bypass_mode": "always"},
			},
		})

	if strings.Count(out, "bypass_actors {") != 1 {
		t.Errorf("expected config to still have 1 bypass_actors block, got:\n%s", out)
	}
	assertNotContains(t, out, "actor_id = 200")
}

// ---------------------------------------------------------------------------
// RemoveResource tests
// ---------------------------------------------------------------------------

func TestRemoveResource(t *testing.T) {
	input := `
resource "github_repository" "keep" {
  name = "keep"
}

resource "github_repository" "delete_me" {
  name = "delete_me"
}
`
	out := removeResourceFromString(t, input, "github_repository", "delete_me")

	assertNotContains(t, out, `"delete_me"`)
	assertContains(t, out, `"keep"`)
}

func TestRemoveResourceNotFound(t *testing.T) {
	input := `
resource "github_repository" "repo" {
  name = "repo"
}
`
	dir := t.TempDir()
	path := filepath.Join(dir, "main.tf")
	if err := os.WriteFile(path, []byte(input), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}
	removed, err := RemoveResource(path, "github_repository", "nonexistent")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if removed {
		t.Error("expected removed=false for nonexistent resource")
	}
}

// ---------------------------------------------------------------------------
// Multi-line list formatting tests
// ---------------------------------------------------------------------------

func TestMultilineStringListFormatting(t *testing.T) {
	// A string list with >1 items should be written one-item-per-line.
	input := `
resource "github_repository_ruleset" "rs" {
  rules {
    pull_request {
      allowed_merge_methods = ["merge"]
    }
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"rules": map[string]interface{}{
				"pull_request": map[string]interface{}{
					"allowed_merge_methods": []interface{}{"merge", "squash", "rebase"},
				},
			},
		})

	assertContains(t, out, "\"merge\",")
	assertContains(t, out, "\"squash\",")
	assertContains(t, out, "\"rebase\",")
	// Each item should be on its own line
	if strings.Count(out, "\n") < strings.Count(input, "\n")+2 {
		t.Errorf("expected multi-line list, got:\n%s", out)
	}
}

func TestSingleItemListStaysOnOneLine(t *testing.T) {
	// A single-item list should stay on one line (not multi-line).
	input := `
resource "github_repository_ruleset" "rs" {
  rules {
    pull_request {
      allowed_merge_methods = ["merge", "squash"]
    }
  }
}
`
	out := applyDriftToString(t, input, "github_repository_ruleset", "rs",
		map[string]interface{}{
			"rules": map[string]interface{}{
				"pull_request": map[string]interface{}{
					"allowed_merge_methods": []interface{}{"merge"},
				},
			},
		})

	assertContains(t, out, `"merge"`)
}
