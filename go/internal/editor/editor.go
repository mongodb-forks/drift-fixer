// Package editor applies drift fixes to .tf files using hclwrite.
package editor

import (
	"fmt"
	"math/big"
	"os"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/hclwrite"
	"github.com/zclconf/go-cty/cty"
)

// RemoveResource removes the `resource "rType" "rName" { ... }` block from
// filePath and writes the result back. Returns true if the block was found
// and removed.
func RemoveResource(filePath, resourceType, resourceName string) (bool, error) {
	src, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Errorf("read %s: %w", filePath, err)
	}
	f, diags := hclwrite.ParseConfig(src, filePath, hcl.InitialPos)
	if diags.HasErrors() {
		return false, fmt.Errorf("parse HCL %s: %s", filePath, diags.Error())
	}
	block := findResourceBlock(f.Body(), resourceType, resourceName)
	if block == nil {
		return false, nil
	}
	f.Body().RemoveBlock(block)
	if err := os.WriteFile(filePath, f.Bytes(), 0644); err != nil {
		return false, fmt.Errorf("write %s: %w", filePath, err)
	}
	return true, nil
}

// ApplyDrift reads filePath, applies the drifted attribute values for the
// resource identified by (resourceType, resourceName), and writes it back.
// Only attributes where before != after are passed in driftedAttrs.
// Returns true if any changes were written.
func ApplyDrift(filePath, resourceType, resourceName string, driftedAttrs map[string]interface{}, verbose bool) (bool, error) {
	src, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Errorf("read %s: %w", filePath, err)
	}

	f, diags := hclwrite.ParseConfig(src, filePath, hcl.InitialPos)
	if diags.HasErrors() {
		return false, fmt.Errorf("parse HCL %s: %s", filePath, diags.Error())
	}

	resourceBlock := findResourceBlock(f.Body(), resourceType, resourceName)
	if resourceBlock == nil {
		return false, fmt.Errorf("resource %q %q not found in %s", resourceType, resourceName, filePath)
	}

	changed := syncBody(resourceBlock.Body(), driftedAttrs, verbose, "  ")
	if !changed {
		return false, nil
	}

	if err := os.WriteFile(filePath, f.Bytes(), 0644); err != nil {
		return false, fmt.Errorf("write %s: %w", filePath, err)
	}
	return true, nil
}

// findResourceBlock finds the first `resource "rType" "rName" { ... }` block.
func findResourceBlock(body *hclwrite.Body, rType, rName string) *hclwrite.Block {
	for _, block := range body.Blocks() {
		if block.Type() != "resource" {
			continue
		}
		labels := block.Labels()
		if len(labels) == 2 && labels[0] == rType && labels[1] == rName {
			return block
		}
	}
	return nil
}

// syncBody applies driftedAttrs onto body. Returns true if anything changed.
func syncBody(body *hclwrite.Body, attrs map[string]interface{}, verbose bool, indent string) bool {
	changed := false
	for key, val := range attrs {
		if val == nil {
			continue
		}
		// Empty slice: could be "zero-instance block type" (infra deleted all
		// instances) OR a scalar list attribute being set to empty.
		// We disambiguate below: if existing config blocks of this type exist,
		// remove them. Otherwise skip (it's just an unset scalar list).
		if lst, ok := val.([]interface{}); ok && len(lst) == 0 {
			existing := blocksOfType(body, key)
			if len(existing) > 0 {
				for _, b := range existing {
					body.RemoveBlock(b)
					if verbose {
						fmt.Printf("%s[block] removed %s (empty in infra)\n", indent, key)
					}
					changed = true
				}
			}
			// If no existing blocks, nothing to do — skip writing `= []`
			continue
		}
		if isBlockValue(val) {
			// Nested block — may appear multiple times (e.g. bypass_actors).
			items := toBlockItems(val)
			if len(items) == 0 {
				continue
			}
			existing := blocksOfType(body, key)
			if len(existing) == 0 {
				// Block type entirely absent from config: add all instances from plan.
				for i, blockData := range items {
					target := body.AppendNewBlock(key, nil)
					if syncBody(target.Body(), blockData, verbose, indent+"  ") {
						if verbose {
							fmt.Printf("%s[block] added %s[%d]\n", indent, key, i)
						}
						changed = true
					}
				}
			} else {
				// Block type already present: only update existing instances.
				// Do NOT add new ones — the user controls how many blocks exist
				// (e.g. they may have intentionally removed one to delete it from infra).
				for i, target := range existing {
					if i >= len(items) {
						break
					}
					if syncBody(target.Body(), items[i], verbose, indent+"  ") {
						if verbose {
							fmt.Printf("%s[block] synced %s[%d]\n", indent, key, i)
						}
						changed = true
					}
				}
			}
		} else {
			// Scalar attribute — convert to cty and set
			ctyVal, err := toCty(val)
			if err != nil {
				fmt.Printf("%s[warn] skip %s: %v\n", indent, key, err)
				continue
			}
			// Check if already equal to avoid unnecessary rewrites
			existing := body.GetAttribute(key)
			_ = existing
			body.SetAttributeValue(key, ctyVal)
			if verbose {
				fmt.Printf("%s[attr] set %s = %v\n", indent, key, val)
			}
			changed = true
		}
	}
	return changed
}

// blocksOfType returns all blocks of the given type from body, in order.
func blocksOfType(body *hclwrite.Body, blockType string) []*hclwrite.Block {
	var out []*hclwrite.Block
	for _, b := range body.Blocks() {
		if b.Type() == blockType {
			out = append(out, b)
		}
	}
	return out
}

// toBlockItems returns all map instances from a block value (map or list-of-maps).
func toBlockItems(v interface{}) []map[string]interface{} {
	switch val := v.(type) {
	case map[string]interface{}:
		return []map[string]interface{}{val}
	case []interface{}:
		var out []map[string]interface{}
		for _, item := range val {
			if m, ok := item.(map[string]interface{}); ok {
				out = append(out, m)
			}
		}
		return out
	}
	return nil
}

// isBlockValue returns true if the JSON value represents an HCL block
// (a map or a non-empty list of maps).
func isBlockValue(v interface{}) bool {
	switch val := v.(type) {
	case map[string]interface{}:
		return true
	case []interface{}:
		for _, item := range val {
			if _, ok := item.(map[string]interface{}); ok {
				return true
			}
		}
	}
	return false
}

// toCty converts a JSON-unmarshalled value to a cty.Value suitable for hclwrite.
func toCty(v interface{}) (cty.Value, error) {
	if v == nil {
		return cty.NullVal(cty.DynamicPseudoType), nil
	}
	switch val := v.(type) {
	case bool:
		return cty.BoolVal(val), nil
	case float64:
		// JSON numbers are always float64. If the value is a whole number,
		// use NumberIntVal to avoid scientific notation (e.g. 1.236702e+06).
		if val == float64(int64(val)) {
			return cty.NumberIntVal(int64(val)), nil
		}
		return cty.NumberVal(new(big.Float).SetFloat64(val)), nil
	case string:
		return cty.StringVal(val), nil
	case []interface{}:
		if len(val) == 0 {
			return cty.ListValEmpty(cty.String), nil
		}
		// Homogeneous string list (common case: topics, allowed_merge_methods)
		strs := make([]cty.Value, 0, len(val))
		for _, item := range val {
			s, ok := item.(string)
			if !ok {
				return cty.NilVal, fmt.Errorf("mixed-type list not supported for attr")
			}
			strs = append(strs, cty.StringVal(s))
		}
		return cty.ListVal(strs), nil
	case map[string]interface{}:
		// Inline object — only used when the provider exposes it as an attribute rather than a block.
		// Build a cty.ObjectVal.
		attrTypes := map[string]cty.Type{}
		attrVals := map[string]cty.Value{}
		for k, elem := range val {
			cv, err := toCty(elem)
			if err != nil {
				return cty.NilVal, err
			}
			attrTypes[k] = cv.Type()
			attrVals[k] = cv
		}
		return cty.ObjectVal(attrVals), nil
	}
	return cty.NilVal, fmt.Errorf("unsupported type %T", v)
}
