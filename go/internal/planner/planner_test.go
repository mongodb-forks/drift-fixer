package planner

import (
	"reflect"
	"sort"
	"testing"
)

// driftAddrs returns drift addresses sorted, for stable comparison.
func driftAddrs(drifts []ResourceDrift) []string {
	out := make([]string, 0, len(drifts))
	for _, d := range drifts {
		out = append(out, d.Address)
	}
	sort.Strings(out)
	return out
}

func findDrift(drifts []ResourceDrift, addr string) *ResourceDrift {
	for i, d := range drifts {
		if d.Address == addr {
			return &drifts[i]
		}
	}
	return nil
}

// TestParsePlanJSON_AttributeDrift covers the common case where an attribute
// changed in real infra: resource_changes has action=update with before!=after.
func TestParsePlanJSON_AttributeDrift(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_repository.foo",
			"type": "github_repository",
			"name": "foo",
			"change": {
				"actions": ["update"],
				"before": {"description": "old", "name": "foo"},
				"after":  {"description": "new", "name": "foo"},
				"before_sensitive": {},
				"after_unknown": {}
			}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 1 {
		t.Fatalf("want 1 drift, got %d", len(drifts))
	}
	d := drifts[0]
	if d.Address != "github_repository.foo" || d.Delete {
		t.Fatalf("unexpected drift: %+v", d)
	}
	if got := d.DriftedAttrs["description"]; got != "old" {
		t.Errorf("DriftedAttrs[description] = %v, want \"old\" (the before/real-infra value)", got)
	}
	if _, ok := d.DriftedAttrs["name"]; ok {
		t.Errorf("name should not be in DriftedAttrs (before == after)")
	}
}

// TestParsePlanJSON_BoolBeforeSensitive guards against the regression we hit
// when the whole resource value's sensitivity is encoded as a bare bool.
// Prior to the fix this failed unmarshalling with:
//
//	cannot unmarshal bool into Go struct field .before_sensitive of type map[string]interface{}
func TestParsePlanJSON_BoolBeforeSensitive(t *testing.T) {
	// before_sensitive=false (whole resource not sensitive),
	// after_unknown=false (after is null, nothing computed) — both bools.
	in := []byte(`{
		"resource_changes": [{
			"address": "github_branch_protection.foo",
			"type": "github_branch_protection",
			"name": "foo",
			"change": {
				"actions": ["create"],
				"before": null,
				"after":  {"pattern": "main"},
				"before_sensitive": false,
				"after_unknown": false
			}
		}]
	}`)
	if _, err := parsePlanJSON(in); err != nil {
		t.Fatalf("parsePlanJSON should accept bool before_sensitive/after_unknown, got: %v", err)
	}
}

// TestParsePlanJSON_BoolBeforeSensitiveTrue: when the whole before value is
// sensitive (bool true), every attribute should be treated as sensitive and
// excluded from DriftedAttrs.
func TestParsePlanJSON_BoolBeforeSensitiveTrue(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_repository.foo",
			"type": "github_repository",
			"name": "foo",
			"change": {
				"actions": ["update"],
				"before": {"description": "old"},
				"after":  {"description": "new"},
				"before_sensitive": true,
				"after_unknown": {}
			}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 0 {
		t.Fatalf("want 0 drifts (all sensitive), got %d: %+v", len(drifts), drifts)
	}
}

// TestParsePlanJSON_PerAttrSensitiveFiltered: per-attribute sensitivity flags
// should exclude only the sensitive attrs.
func TestParsePlanJSON_PerAttrSensitiveFiltered(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_repository.foo",
			"type": "github_repository",
			"name": "foo",
			"change": {
				"actions": ["update"],
				"before": {"description": "old", "secret_token": "abc"},
				"after":  {"description": "new", "secret_token": "xyz"},
				"before_sensitive": {"secret_token": true},
				"after_unknown": {}
			}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 1 {
		t.Fatalf("want 1 drift, got %d", len(drifts))
	}
	if _, ok := drifts[0].DriftedAttrs["secret_token"]; ok {
		t.Errorf("secret_token should be filtered out as sensitive")
	}
	if drifts[0].DriftedAttrs["description"] != "old" {
		t.Errorf("description should still drift, got %+v", drifts[0].DriftedAttrs)
	}
}

// TestParsePlanJSON_AfterUnknownSkipsAttr: an attribute marked unknown in
// after_unknown is computed post-apply and shouldn't be reported as drift.
func TestParsePlanJSON_AfterUnknownSkipsAttr(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_repository.foo",
			"type": "github_repository",
			"name": "foo",
			"change": {
				"actions": ["update"],
				"before": {"description": "old", "etag": "v1"},
				"after":  {"description": "new"},
				"before_sensitive": {},
				"after_unknown": {"etag": true}
			}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 1 {
		t.Fatalf("want 1 drift, got %d", len(drifts))
	}
	if _, ok := drifts[0].DriftedAttrs["etag"]; ok {
		t.Errorf("etag is computed (after_unknown), should be skipped")
	}
	if drifts[0].DriftedAttrs["description"] != "old" {
		t.Errorf("description should drift, got %+v", drifts[0].DriftedAttrs)
	}
}

// TestParsePlanJSON_DeletedInRealInfra is the user-reported scenario:
// a resource was deleted via the GitHub UI. resource_drift has action=delete
// and resource_changes has action=create (because config still has the block).
// The planner should emit a Delete drift so the editor removes the block.
func TestParsePlanJSON_DeletedInRealInfra(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_branch_protection.foo",
			"type": "github_branch_protection",
			"name": "foo",
			"change": {
				"actions": ["create"],
				"before": null,
				"after":  {"pattern": "main"},
				"before_sensitive": false,
				"after_unknown": false
			}
		}],
		"resource_drift": [{
			"address": "github_branch_protection.foo",
			"type": "github_branch_protection",
			"name": "foo",
			"change": {"actions": ["delete"]}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if got := driftAddrs(drifts); !reflect.DeepEqual(got, []string{"github_branch_protection.foo"}) {
		t.Fatalf("addresses = %v, want [github_branch_protection.foo]", got)
	}
	d := findDrift(drifts, "github_branch_protection.foo")
	if !d.Delete {
		t.Errorf("Delete = false, want true (resource removed from real infra)")
	}
}

// TestParsePlanJSON_PostFixValidation guards the cross-reference filter:
// after drift-fixer removed the block, refresh still notes resource_drift
// action=delete, but resource_changes no longer plans to create the resource
// (because config is empty). We should NOT re-emit the drift, otherwise
// validation re-flags it forever.
func TestParsePlanJSON_PostFixValidation(t *testing.T) {
	in := []byte(`{
		"resource_changes": [],
		"resource_drift": [{
			"address": "github_branch_protection.foo",
			"type": "github_branch_protection",
			"name": "foo",
			"change": {"actions": ["delete"]}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 0 {
		t.Fatalf("want 0 drifts (block already removed from config), got %d: %+v", len(drifts), drifts)
	}
}

// TestParsePlanJSON_NewResourceNotDrift: a resource newly added to config has
// resource_changes action=create but no matching resource_drift entry. That's
// not drift — apply will create it.
func TestParsePlanJSON_NewResourceNotDrift(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_repository.new",
			"type": "github_repository",
			"name": "new",
			"change": {
				"actions": ["create"],
				"before": null,
				"after":  {"name": "new"},
				"before_sensitive": false,
				"after_unknown": false
			}
		}],
		"resource_drift": []
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 0 {
		t.Fatalf("want 0 drifts (newly added resource), got %d: %+v", len(drifts), drifts)
	}
}

// TestParsePlanJSON_NoOpNoDrift: a resource_changes entry with action=no-op
// (or just before==after on update) should produce no drift.
func TestParsePlanJSON_NoOpNoDrift(t *testing.T) {
	in := []byte(`{
		"resource_changes": [{
			"address": "github_repository.foo",
			"type": "github_repository",
			"name": "foo",
			"change": {
				"actions": ["no-op"],
				"before": {"description": "same"},
				"after":  {"description": "same"},
				"before_sensitive": {},
				"after_unknown": {}
			}
		}]
	}`)
	drifts, err := parsePlanJSON(in)
	if err != nil {
		t.Fatalf("parsePlanJSON: %v", err)
	}
	if len(drifts) != 0 {
		t.Fatalf("want 0 drifts on no-op, got %d", len(drifts))
	}
}
