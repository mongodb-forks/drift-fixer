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

	var planJSON struct {
		ResourceChanges []struct {
			Address string `json:"address"`
			Type    string `json:"type"`
			Name    string `json:"name"`
			Change  struct {
				Actions         []string               `json:"actions"`
				Before          map[string]interface{} `json:"before"`
				After           map[string]interface{} `json:"after"`
				AfterUnknown    map[string]interface{} `json:"after_unknown"`
				BeforeSensitive map[string]interface{} `json:"before_sensitive"`
			} `json:"change"`
		} `json:"resource_changes"`
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
		// Only process updates / replaces (not creates / deletes)
		isUpdate := false
		for _, a := range ch.Actions {
			if a == "update" || a == "replace" {
				isUpdate = true
			}
		}
		if !isUpdate {
			continue
		}

		sensitiveKeys := sensitiveSet(ch.BeforeSensitive)
		drifted := make(map[string]interface{})
		for k, beforeVal := range ch.Before {
			if sensitiveKeys[k] {
				continue
			}
			afterVal := ch.After[k]
			if afterUnknown, ok := ch.AfterUnknown[k]; ok {
				if b, ok := afterUnknown.(bool); ok && b {
					continue // computed post-apply, skip
				}
			}
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
	return drifts, nil
}

func sensitiveSet(m map[string]interface{}) map[string]bool {
	out := map[string]bool{}
	for k, v := range m {
		switch val := v.(type) {
		case bool:
			if val {
				out[k] = true
			}
		case map[string]interface{}:
			if len(val) > 0 {
				out[k] = true
			}
		}
	}
	return out
}

// deepEqual does a JSON-normalized equality check.
func deepEqual(a, b interface{}) bool {
	aj, _ := json.Marshal(a)
	bj, _ := json.Marshal(b)
	return string(aj) == string(bj)
}
