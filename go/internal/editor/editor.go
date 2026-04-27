// Package editor applies drift fixes to .tf files using hclwrite.
package editor

import (
	"fmt"
	"math/big"
	"os"
	"strings"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/hclsyntax"
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
	if err := os.WriteFile(filePath, hclwrite.Format(f.Bytes()), 0644); err != nil {
		return false, fmt.Errorf("write %s: %w", filePath, err)
	}
	return true, nil
}

// ApplyDrift reads filePath, applies the drifted attribute values for the
// resource identified by (resourceType, resourceName), and writes it back.
// Only attributes where before != after are passed in driftedAttrs.
// Returns true if any changes were written.
// syncCtx carries per-run context through syncBody and its helpers so that
// individual functions do not need long parameter lists.
type syncCtx struct {
	verbose bool
	rType   string      // resource type, e.g. "github_repository_ruleset"
	rName   string      // resource name, e.g. "ruleset_15577636"
	hook    CommentHook // may be nil
}

func ApplyDrift(filePath, resourceType, resourceName string, driftedAttrs map[string]interface{}, verbose bool, hook CommentHook) (bool, error) {
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

	ctx := syncCtx{verbose: verbose, rType: resourceType, rName: resourceName, hook: hook}
	changed := syncBody(resourceBlock.Body(), driftedAttrs, ctx, "  ", "")
	if !changed {
		return false, nil
	}

	if err := os.WriteFile(filePath, hclwrite.Format(f.Bytes()), 0644); err != nil {
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
// path is the dot-separated attribute path from the resource root, e.g. "conditions.ref_name".
func syncBody(body *hclwrite.Body, attrs map[string]interface{}, ctx syncCtx, indent, path string) bool {
	changed := false
	for key, val := range attrs {
		if val == nil {
			continue
		}
		// Build the path for this key.
		childPath := key
		if path != "" {
			childPath = path + "." + key
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
					if ctx.verbose {
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
					if syncBody(target.Body(), blockData, ctx, indent+"  ", childPath) {
						if ctx.verbose {
							fmt.Printf("%s[block] added %s[%d]\n", indent, key, i)
						}
						changed = true
					}
				}
			} else {
				// Block type already present. Sync by index up to min(existing, plan).
				for i := 0; i < len(existing) && i < len(items); i++ {
					if syncBody(existing[i].Body(), items[i], ctx, indent+"  ", childPath) {
						if ctx.verbose {
							fmt.Printf("%s[block] synced %s[%d]\n", indent, key, i)
						}
						changed = true
					}
				}
				if len(existing) > len(items) {
					// Config has more instances than infra — remove the excess.
					// This happens when a block was deleted from infra.
					for _, b := range existing[len(items):] {
						body.RemoveBlock(b)
						if ctx.verbose {
							fmt.Printf("%s[block] removed excess %s (infra has fewer)\n", indent, key)
						}
						changed = true
					}
				}
				// If existing < items: user intentionally has fewer blocks than infra
				// (they removed some from config to delete them). Leave as-is.
			}
		} else {
			// Scalar attribute.
			if err := setAttributeVal(body, key, val, ctx, childPath); err != nil {
				fmt.Printf("%s[warn] skip %s: %v\n", indent, key, err)
				continue
			}
			if ctx.verbose {
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

// itemComment holds any comments associated with a single list item.
type itemComment struct {
	before hclwrite.Tokens // comment line(s) on their own line(s) preceding the value
	inline *hclwrite.Token // trailing comment on the same line as the value (may be nil)
}

// extractItemComments parses the existing list attribute on body (if any) and
// returns a map from rendered-value-string → itemComment.
// Keying by value content means comments survive list reordering and insertions.
//
// Token ordering in hclwrite: value, comma, [inline-comment], newline, [before-comments…], next-value
// So "inline" is detected by a comment arriving after the comma before any newline.
func extractItemComments(body *hclwrite.Body, key string) map[string]itemComment {
	attr := body.GetAttribute(key)
	if attr == nil {
		return nil
	}
	exprToks := attr.Expr().BuildTokens(nil)
	result := make(map[string]itemComment)
	inList := false
	betweenItems := false // after newline-following-comma, until next value
	justComma := false    // after comma, before any newline
	var beforeComments hclwrite.Tokens
	var valueBuf []byte
	var prevKey string // key of the item whose comma we just passed
	for _, t := range exprToks {
		switch t.Type {
		case hclsyntax.TokenOBrack:
			inList = true
			betweenItems = true
		case hclsyntax.TokenCBrack:
			// flush last item (no comma follows it)
			if len(valueBuf) > 0 && len(beforeComments) > 0 {
				k := strings.TrimSpace(string(valueBuf))
				c := result[k]
				c.before = beforeComments
				result[k] = c
			}
			inList = false
		case hclsyntax.TokenComment:
			if !inList {
				break
			}
			if justComma {
				// Inline: comment is on the same line as the comma.
				// The comment token includes its trailing \n, so treat it as the
				// line ending — transition to betweenItems so any further comments
				// are treated as before-comments for the next value.
				c := result[prevKey]
				c.inline = t
				result[prevKey] = c
				justComma = false
				betweenItems = true
			} else if betweenItems {
				// Preceding-line: comment on its own line before the next value
				beforeComments = append(beforeComments, t)
			}
		case hclsyntax.TokenComma:
			if inList {
				// Commit the current item's before-comments; inline arrives next.
				if len(valueBuf) > 0 {
					k := strings.TrimSpace(string(valueBuf))
					if len(beforeComments) > 0 {
						c := result[k]
						c.before = beforeComments
						result[k] = c
					}
					prevKey = k
				}
				beforeComments = nil
				valueBuf = nil
				justComma = true
				betweenItems = false
			}
		case hclsyntax.TokenNewline:
			if inList && justComma {
				justComma = false
				betweenItems = true
			}
		default:
			if inList {
				if betweenItems || justComma {
					betweenItems = false
					justComma = false
				}
				valueBuf = append(valueBuf, t.Bytes...)
			}
		}
	}
	if len(result) == 0 {
		return nil
	}
	return result
}

// setAttributeVal sets a scalar attribute on body. Lists with more than one
// item are formatted one-item-per-line; everything else uses SetAttributeValue.
// Existing comments are preserved; the hook (if set) provides comments for new values.
func setAttributeVal(body *hclwrite.Body, key string, val interface{}, ctx syncCtx, path string) error {
	if lst, ok := val.([]interface{}); ok && len(lst) > 1 {
		comments := extractItemComments(body, key)
		toks, err := multilineListTokens(lst, comments, ctx, path)
		if err == nil {
			body.SetAttributeRaw(key, toks)
			return nil
		}
		// Fall through to SetAttributeValue on error
	}
	ctyVal, err := toCty(val)
	if err != nil {
		return err
	}
	// For scalar (non-list) attributes, ask the hook for a comment.
	if ctx.hook != nil {
		valToks := hclwrite.TokensForValue(ctyVal)
		var keyBuf []byte
		for _, vt := range valToks {
			keyBuf = append(keyBuf, vt.Bytes...)
		}
		if comment := ctx.hook(ctx.rType, ctx.rName, path, strings.TrimSpace(string(keyBuf))); comment != "" {
			body.SetAttributeRaw(key, append(valToks,
				&hclwrite.Token{Type: hclsyntax.TokenComment, Bytes: []byte(" # " + comment + "\n")},
			))
			return nil
		}
	}
	body.SetAttributeValue(key, ctyVal)
	return nil
}

// multilineListTokens builds tokens for a multi-line list of any scalar type:
//
//	= [
//	  # before comment
//	  "a",  # inline comment
//	  42,
//	]
//
// Existing comments (from extractItemComments) are preserved. For list items
// that have no existing comment, the hook (if set) is asked for one.
// path is the dot-separated attribute path of the list itself.
func multilineListTokens(items []interface{}, comments map[string]itemComment, ctx syncCtx, path string) (hclwrite.Tokens, error) {
	tok := func(t hclsyntax.TokenType, b string) *hclwrite.Token {
		return &hclwrite.Token{Type: t, Bytes: []byte(b)}
	}
	toks := hclwrite.Tokens{
		tok(hclsyntax.TokenOBrack, "["),
		tok(hclsyntax.TokenNewline, "\n"),
	}
	for _, item := range items {
		ctyVal, err := toCty(item)
		if err != nil {
			return nil, err
		}
		valToks := hclwrite.TokensForValue(ctyVal)
		var keyBuf []byte
		for _, vt := range valToks {
			keyBuf = append(keyBuf, vt.Bytes...)
		}
		valKey := strings.TrimSpace(string(keyBuf))
		c := comments[valKey]
		// If no existing inline comment and hook is set, ask for one.
		if c.inline == nil && ctx.hook != nil {
			if hookComment := ctx.hook(ctx.rType, ctx.rName, path, valKey); hookComment != "" {
				ct := &hclwrite.Token{
					Type:  hclsyntax.TokenComment,
					Bytes: []byte(" # " + hookComment + "\n"),
				}
				c.inline = ct
			}
		}
		// Emit any preceding-line comments.
		toks = append(toks, c.before...)
		// Emit the value itself.
		toks = append(toks, valToks...)
		// Emit comma; if there's an inline comment it carries its own trailing
		// newline in its bytes, so skip our explicit newline in that case.
		toks = append(toks, tok(hclsyntax.TokenComma, ","))
		if c.inline != nil {
			toks = append(toks, c.inline)
		} else {
			toks = append(toks, tok(hclsyntax.TokenNewline, "\n"))
		}
	}
	toks = append(toks, tok(hclsyntax.TokenCBrack, "]"))
	return toks, nil
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
