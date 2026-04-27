package editor

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// CommentHook is a function called whenever drift-fixer writes a value (scalar
// attribute or individual list item). It receives the resource context and the
// rendered value string. It should return a comment body (without the leading
// "# "), or an empty string if no comment is desired.
//
// A nil CommentHook means no hook is active.
type CommentHook func(resourceType, resourceName, attrPath, value string) string

// LoadCommentHook reads the DRIFT_FIXER_COMMENT_SCRIPT environment variable.
// If set, it returns a CommentHook that invokes that script for every written
// value. The script receives context via environment variables:
//
//	DRIFT_RESOURCE_TYPE  – e.g. "github_repository_ruleset"
//	DRIFT_RESOURCE_NAME  – e.g. "ruleset_15577636"
//	DRIFT_ATTR_PATH      – e.g. "conditions.ref_name.include"
//	DRIFT_ATTR_VALUE     – e.g. "~DEFAULT_BRANCH"
//
// Whatever the script prints to stdout (trimmed) is used as the comment text.
// An empty output means no comment is added.
// If DRIFT_FIXER_COMMENT_SCRIPT is unset, LoadCommentHook returns nil.
func LoadCommentHook(verbose bool) CommentHook {
	script := os.Getenv("DRIFT_FIXER_COMMENT_SCRIPT")
	if script == "" {
		return nil
	}
	return func(resourceType, resourceName, attrPath, value string) string {
		cmd := exec.Command(script)
		cmd.Env = append(os.Environ(),
			"DRIFT_RESOURCE_TYPE="+resourceType,
			"DRIFT_RESOURCE_NAME="+resourceName,
			"DRIFT_ATTR_PATH="+attrPath,
			"DRIFT_ATTR_VALUE="+value,
		)
		out, err := cmd.Output()
		if err != nil {
			if verbose {
				fmt.Fprintf(os.Stderr, "[hook] script error for %s.%s=%s: %v\n",
					attrPath, resourceType, value, err)
			}
			return ""
		}
		return strings.TrimSpace(string(out))
	}
}
