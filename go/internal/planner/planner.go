// Package planner runs tofu plan/show and extracts drifted resource attributes.
package planner

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
)

// ResourceDrift holds the drifted before-values for one resource.
type ResourceDrift struct {
	Address      string
	ResourceType string
	ResourceName string
	// Delete is true when the resource exists in config but has been deleted
	// from the real infrastructure (plan action = "delete").
	Delete bool
	// DriftedAttrs maps attribute name → live (before) value for attrs where
	// before != after. Only leaf attributes that are not sensitive are included.
	// Block-type values (map / []interface{}) are included as-is for the editor.
	DriftedAttrs map[string]interface{}
}

// Run runs `tofu plan -out <tmp>` + `tofu show -json <tmp>` in projectDir and
// returns one ResourceDrift per resource that has real drift (before != after).
func Run(projectDir, tfBin string, verbose bool) ([]ResourceDrift, error) {
	f, err := os.CreateTemp("", "drift-*.tfplan")
	if err != nil {
		return nil, fmt.Errorf("create tmpfile: %w", err)
	}
	planFile := f.Name()
	f.Close()
	defer os.Remove(planFile)

	planCmd := exec.Command(tfBin, "plan", "-out", planFile, "-no-color")
	planCmd.Dir = projectDir
	planOut, err := planCmd.CombinedOutput()
	if verbose {
		fmt.Printf("[plan] exit %v\n%s\n", planCmd.ProcessState.ExitCode(), string(planOut))
	}
	// exit 0 = no changes, exit 2 = changes; anything else is an error
	if code := planCmd.ProcessState.ExitCode(); code != 0 && code != 2 {
		return nil, fmt.Errorf("tofu plan failed (exit %d):\n%s", code, string(planOut))
	}

	showCmd := exec.Command(tfBin, "show", "-json", planFile)
	showCmd.Dir = projectDir
	showOut, err := showCmd.Output()
	if err != nil {
		return nil, fmt.Errorf("tofu show -json: %w", err)
	}

	// before_sensitive and after_unknown are polymorphic in Terraform/OpenTofu
	// plan JSON: a bool when the entire resource value is (un)sensitive/known,
	// an object when there is per-attribute info. Decode as interface{} and
	// branch on the concrete type at use.
	var planJSON struct {
		ResourceChanges []struct {
			Address string `json:"address"`
			Type    string `json:"type"`
			Name    string `json:"name"`
			Change  struct {
				Actions         []string               `json:"actions"`
				Before          map[string]interface{} `json:"before"`
				After           map[string]interface{} `json:"after"`
				AfterUnknown    interface{}            `json:"after_unknown"`
				BeforeSensitive interface{}            `json:"before_sensitive"`
			} `json:"change"`
		} `json:"resource_changes"`
		// resource_drift reports state-vs-real-infra drift detected during
		// refresh. We only need enough to spot resources that disappeared
		// from real infra; full attribute drift is already handled via
		// resource_changes above.
		ResourceDrift []struct {
			Address string `json:"address"`
			Type    string `json:"type"`
			Name    string `json:"name"`
			Change  struct {
				Actions []string `json:"actions"`
			} `json:"change"`
		} `json:"resource_drift"`
	}
	if err := json.Unmarshal(showOut, &planJSON); err != nil {
		return nil, fmt.Errorf("parse plan JSON: %w", err)
	}

	var drifts []ResourceDrift
	for _, rc := range planJSON.ResourceChanges {
		ch := rc.Change
		if ch.Before == nil {
			continue
		}
		// Determine the action type
		isUpdate, isDelete := false, false
		for _, a := range ch.Actions {
			switch a {
			case "update", "replace":
				isUpdate = true
			case "delete":
				isDelete = true
			}
		}

		if isDelete && !isUpdate {
			// Resource was deleted from infra — record it so the editor can
			// remove the block from config.
			drifts = append(drifts, ResourceDrift{
				Address:      rc.Address,
				ResourceType: rc.Type,
				ResourceName: rc.Name,
				Delete:       true,
			})
			continue
		}
		if !isUpdate {
			continue
		}

		drifted := make(map[string]interface{})
		for k, beforeVal := range ch.Before {
			if isSensitive(ch.BeforeSensitive, k) {
				continue
			}
			if isAfterUnknown(ch.AfterUnknown, k) {
				continue // computed post-apply, skip
			}
			afterVal := ch.After[k]
			if !deepEqual(beforeVal, afterVal) {
				drifted[k] = beforeVal
			}
		}
		if len(drifted) == 0 {
			continue
		}
		drifts = append(drifts, ResourceDrift{
			Address:      rc.Address,
			ResourceType: rc.Type,
			ResourceName: rc.Name,
			DriftedAttrs: drifted,
		})
	}

	// A resource removed from real infra (e.g. deleted in a provider's web
	// console) appears in resource_drift with action=delete, but in
	// resource_changes with action=create — which the loop above skips. Pick
	// those up here so the editor can remove the corresponding block.
	seen := make(map[string]bool, len(drifts))
	for _, d := range drifts {
		seen[d.Address] = true
	}
	for _, rd := range planJSON.ResourceDrift {
		if seen[rd.Address] {
			continue
		}
		for _, a := range rd.Change.Actions {
			if a == "delete" {
				drifts = append(drifts, ResourceDrift{
					Address:      rd.Address,
					ResourceType: rd.Type,
					ResourceName: rd.Name,
					Delete:       true,
				})
				break
			}
		}
	}
	return drifts, nil
}

// isSensitive reports whether attribute key in a resource's before-state is
// marked sensitive in the plan. The top-level value may be a bool (whole
// resource is sensitive / not) or an object mapping attribute names to bool
// or nested-object indicators.
func isSensitive(sens interface{}, key string) bool {
	switch v := sens.(type) {
	case bool:
		return v
	case map[string]interface{}:
		sub, ok := v[key]
		if !ok {
			return false
		}
		switch sv := sub.(type) {
		case bool:
			return sv
		case map[string]interface{}:
			return len(sv) > 0
		}
	}
	return false
}

// isAfterUnknown reports whether attribute key will be computed post-apply.
// after_unknown is bool when the entire after value is null/known, or an
// object with per-attribute bools when after is a populated object.
func isAfterUnknown(au interface{}, key string) bool {
	m, ok := au.(map[string]interface{})
	if !ok {
		return false
	}
	v, ok := m[key]
	if !ok {
		return false
	}
	b, ok := v.(bool)
	return ok && b
}

// deepEqual does a JSON-normalized equality check.
func deepEqual(a, b interface{}) bool {
	aj, _ := json.Marshal(a)
	bj, _ := json.Marshal(b)
	return string(aj) == string(bj)
}
