// Package schema loads provider schemas via `tofu providers schema -json` and
// answers questions about attribute types that the plan JSON alone can't —
// chiefly whether a collection attribute is a set (order-insensitive) or a
// list (order-sensitive).
package schema

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
)

// Schema indexes the collection kind ("list", "set", "map", …) of every
// attribute, keyed by resource type and dot-separated attribute path from the
// resource root (e.g. "conditions.repository_id"). Nested block names appear
// in the path without indices, matching the paths the editor builds.
type Schema struct {
	kinds map[string]map[string]string // resource type → path → collection kind
}

// Load runs `<tfBin> providers schema -json` in projectDir. The directory must
// already be initialised.
func Load(projectDir, tfBin string) (*Schema, error) {
	cmd := exec.Command(tfBin, "providers", "schema", "-json")
	cmd.Dir = projectDir
	out, err := cmd.Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("%s providers schema -json: %w\n%s", tfBin, err, ee.Stderr)
		}
		return nil, fmt.Errorf("%s providers schema -json: %w", tfBin, err)
	}
	return Parse(out)
}

type jsonBlock struct {
	Attributes map[string]jsonAttribute `json:"attributes"`
	BlockTypes map[string]struct {
		Block jsonBlock `json:"block"`
	} `json:"block_types"`
}

type jsonAttribute struct {
	// Type is a cty JSON type: "string", or ["list","number"], ["set",…], …
	Type json.RawMessage `json:"type"`
	// NestedType is used by protocol-6 providers for nested attributes.
	NestedType *struct {
		Attributes  map[string]jsonAttribute `json:"attributes"`
		NestingMode string                   `json:"nesting_mode"`
	} `json:"nested_type"`
}

// Parse builds a Schema from `providers schema -json` output.
func Parse(data []byte) (*Schema, error) {
	var doc struct {
		ProviderSchemas map[string]struct {
			ResourceSchemas map[string]struct {
				Block jsonBlock `json:"block"`
			} `json:"resource_schemas"`
		} `json:"provider_schemas"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil, fmt.Errorf("parse provider schema JSON: %w", err)
	}
	s := &Schema{kinds: map[string]map[string]string{}}
	for _, p := range doc.ProviderSchemas {
		for rType, rs := range p.ResourceSchemas {
			if s.kinds[rType] == nil {
				s.kinds[rType] = map[string]string{}
			}
			walkBlock(rs.Block, "", s.kinds[rType])
		}
	}
	return s, nil
}

func walkBlock(b jsonBlock, prefix string, out map[string]string) {
	for name, a := range b.Attributes {
		walkAttr(a, join(prefix, name), out)
	}
	for name, bt := range b.BlockTypes {
		walkBlock(bt.Block, join(prefix, name), out)
	}
}

func walkAttr(a jsonAttribute, path string, out map[string]string) {
	if a.NestedType != nil {
		out[path] = a.NestedType.NestingMode
		for name, na := range a.NestedType.Attributes {
			walkAttr(na, join(path, name), out)
		}
		return
	}
	var tuple []json.RawMessage
	if json.Unmarshal(a.Type, &tuple) == nil && len(tuple) > 0 {
		var kind string
		if json.Unmarshal(tuple[0], &kind) == nil {
			out[path] = kind
		}
	}
}

func join(prefix, name string) string {
	if prefix == "" {
		return name
	}
	return prefix + "." + name
}

// IsSet reports whether the attribute at path on resourceType is a set.
// Unknown resources/attributes (and a nil Schema) report false, so callers
// treat them as ordered lists — writing infra's order is always correct for
// a list and at worst cosmetic churn for a set.
func (s *Schema) IsSet(resourceType, path string) bool {
	if s == nil {
		return false
	}
	return s.kinds[resourceType][strings.TrimPrefix(path, ".")] == "set"
}
