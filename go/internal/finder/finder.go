// Package finder locates which .tf file contains a given resource definition.
package finder

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/hclsyntax"
)

// FindResourceFiles returns a map of absolute file path → list of resource
// addresses whose definition lives in that file.
// addresses are in `type.name` format (as in plan JSON), e.g.
// "github_repository_ruleset.ruleset_15577636"
func FindResourceFiles(projectDir string, addresses []string) (map[string][]string, error) {
	// Build a set of addresses for O(1) lookup
	want := make(map[string]struct{}, len(addresses))
	for _, addr := range addresses {
		want[addr] = struct{}{}
	}

	result := make(map[string][]string)

	err := filepath.WalkDir(projectDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() && d.Name() == ".terraform" {
			return filepath.SkipDir
		}
		if !strings.HasSuffix(path, ".tf") {
			return nil
		}

		src, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read %s: %w", path, err)
		}

		file, diags := hclsyntax.ParseConfig(src, path, hcl.InitialPos)
		if diags.HasErrors() {
			// Skip files that don't parse (e.g. files with unsupported syntax)
			return nil
		}

		body, ok := file.Body.(*hclsyntax.Body)
		if !ok {
			return nil
		}

		for _, block := range body.Blocks {
			if block.Type != "resource" || len(block.Labels) != 2 {
				continue
			}
			addr := block.Labels[0] + "." + block.Labels[1]
			if _, found := want[addr]; found {
				result[path] = append(result[path], addr)
			}
		}
		return nil
	})
	return result, err
}
