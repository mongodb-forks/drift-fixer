package schema

import "testing"

// Trimmed from real `tofu providers schema -json` output for
// integrations/github v6.6.0.
const githubSchemaJSON = `{
  "format_version": "1.0",
  "provider_schemas": {
    "registry.opentofu.org/integrations/github": {
      "resource_schemas": {
        "github_organization_ruleset": {
          "block": {
            "attributes": {
              "name": {"type": "string"}
            },
            "block_types": {
              "conditions": {
                "nesting_mode": "list",
                "block": {
                  "attributes": {
                    "repository_id": {"type": ["list", "number"]}
                  },
                  "block_types": {
                    "ref_name": {
                      "nesting_mode": "list",
                      "block": {
                        "attributes": {
                          "include": {"type": ["list", "string"]}
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "github_actions_organization_permissions": {
          "block": {
            "block_types": {
              "enabled_repositories_config": {
                "nesting_mode": "list",
                "block": {
                  "attributes": {
                    "repository_ids": {"type": ["set", "number"]}
                  }
                }
              }
            }
          }
        },
        "example_nested": {
          "block": {
            "attributes": {
              "things": {
                "nested_type": {
                  "nesting_mode": "set",
                  "attributes": {
                    "tags": {"type": ["set", "string"]},
                    "order": {"type": ["list", "string"]}
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}`

func TestIsSet(t *testing.T) {
	s, err := Parse([]byte(githubSchemaJSON))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	cases := []struct {
		rType, path string
		want        bool
	}{
		{"github_actions_organization_permissions", "enabled_repositories_config.repository_ids", true},
		{"github_organization_ruleset", "conditions.repository_id", false},
		{"github_organization_ruleset", "conditions.ref_name.include", false},
		{"github_organization_ruleset", "name", false},
		{"github_organization_ruleset", "does_not_exist", false},
		{"unknown_resource", "anything", false},
		{"example_nested", "things", true},
		{"example_nested", "things.tags", true},
		{"example_nested", "things.order", false},
	}
	for _, c := range cases {
		if got := s.IsSet(c.rType, c.path); got != c.want {
			t.Errorf("IsSet(%q, %q) = %v, want %v", c.rType, c.path, got, c.want)
		}
	}
}

func TestNilSchemaIsNeverSet(t *testing.T) {
	var s *Schema
	if s.IsSet("github_actions_organization_permissions", "enabled_repositories_config.repository_ids") {
		t.Error("nil Schema should report false")
	}
}
