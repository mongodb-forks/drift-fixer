"""Edit Terraform configuration files using hcledit CLI."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from .plan_parser import ResourceChange

# No hardcoded attribute lists needed.
# Drifted attributes are derived directly from the plan JSON by comparing
# change.before (live infra) vs change.after (what config wants). Computed
# fields (id, node_id, etc.) have the same value in both, so they never
# appear as drift. after_unknown=true attrs are skipped (not yet computed).


class ConfigEditor:
    """Edit Terraform configuration files using hcledit."""

    def __init__(self, project_path: Path, dry_run: bool = False,
                 verbose: bool = False, tf_bin: str = "tofu"):
        self.project_path = project_path
        self.dry_run = dry_run
        self.verbose = verbose
        self.tf_bin = tf_bin

        if not self._check_hcledit_available():
            raise RuntimeError(
                "hcledit CLI not found. Install from https://github.com/minamijoyo/hcledit/releases"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_resources(self, changed_resources: List[ResourceChange],
                         file_resources_map: Dict[str, List[ResourceChange]]) -> bool:
        if self.verbose:
            click.echo(f"  update_resources: {len(file_resources_map)} file(s) to process")

        success = True
        for file_path, resources in file_resources_map.items():
            click.echo(f"Processing file: {Path(file_path).name}")
            if self.verbose:
                for r in resources:
                    click.echo(f"  - {r.address} (change_type={r.change_type})")
            try:
                file_success = self._update_file(file_path, resources)
                if file_success:
                    click.echo(f"  ✅ Successfully updated {Path(file_path).name}")
                else:
                    click.echo(f"  ⚠️  No updates applied to {Path(file_path).name}")
                    success = False
            except Exception as e:
                click.echo(f"  ❌ Exception while updating {file_path}: {e}")
                if self.verbose:
                    import traceback
                    traceback.print_exc()
                success = False

        return success

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_hcledit_available(self) -> bool:
        try:
            result = subprocess.run(
                ["hcledit", "version"],
                capture_output=True, text=True, check=False
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _update_file(self, file_path: str, resources: List[ResourceChange]) -> bool:
        file_updated = False
        for resource in resources:
            if resource.change_type == "delete":
                click.echo(f"  Skipping delete for {resource.address} (manual review required)")
                continue
            if resource.change_type in ("create", "update", "replace"):
                click.echo(f"  Syncing {resource.address} (change_type={resource.change_type})...")
                if self._sync_resource(file_path, resource):
                    file_updated = True
                else:
                    click.echo(f"  ⚠️  Sync returned no changes for {resource.address}")
            else:
                click.echo(f"  ⚠️  Unknown change_type '{resource.change_type}' for {resource.address}, skipping")
        return file_updated

    def _sync_resource(self, file_path: str, resource: ResourceChange) -> bool:
        # Always use absolute path so hcledit works regardless of cwd
        file_path = str(Path(file_path).resolve())
        if self.dry_run:
            click.echo(f"    [DRY RUN] Would sync {resource.address}")
            return True

        # 1. Fetch the ACTUAL infrastructure values from the plan before-state.
        #    tofu show -json (no plan file) only reflects local state, not live
        #    infra — so attributes changed directly in GitHub would be missed.
        click.echo(f"    Running plan to capture live infrastructure values...")
        result = self._get_resource_actual_values(resource)
        if result is None:
            click.echo(f"    ❌ Could not read plan — aborting")
            return False
        actual_data, sensitive_keys = result
        if not actual_data:
            click.echo(f"    ❌ Address '{resource.address}' not found in plan changes")
            return False

        if self.verbose:
            click.echo(f"    Drifted attrs from plan: {sorted(actual_data.keys())}")
            if sensitive_keys:
                click.echo(f"    Sensitive keys (will skip): {sorted(sensitive_keys)}")

        # 2. actual_data already contains ONLY the attributes that differ between
        #    live infra and config (before != after, after_unknown=false).
        #    Still filter out anything OpenTofu marked sensitive.
        to_sync = {
            k: v for k, v in actual_data.items()
            if k not in sensitive_keys
        }
        if self.verbose:
            click.echo(f"    Attributes to sync: {sorted(to_sync.keys())}")

        if not to_sync:
            click.echo(f"    No syncable attributes found for {resource.address}")
            return False

        # 3. Compute which attributes actually differ from the config
        diffs = self._compute_diffs(file_path, resource, to_sync)
        if not diffs:
            click.echo(f"    ✅ Config already matches live infrastructure — no changes needed")
            return False

        click.echo(f"    Attributes with drift: {sorted(diffs.keys())}")

        # 4. Apply each diff with hcledit
        return self._apply_diffs_with_hcledit(file_path, resource, diffs)

    # ------------------------------------------------------------------
    # Fetch actual infrastructure values via plan before-state
    # ------------------------------------------------------------------

    def _get_resource_actual_values(self, resource: ResourceChange
                                     ) -> Optional[tuple[Dict[str, Any], set]]:
        """
        Run `tofu plan -out=<tmp>` then `tofu show -json <tmp>` and compare
        change.before (live infra) vs change.after (desired from config) to
        find ONLY the attributes that are actually drifting.
        Skips attrs where after_unknown=true (computed post-apply).
        Also reads change.before_sensitive and returns sensitive attr names.
        Returns (drifted_before_values, sensitive_attr_names) or None on error.
        Returns ({}, set()) when the resource address is not in plan changes.
        """
        import tempfile
        original_cwd = Path.cwd()
        plan_file = None
        os.chdir(self.project_path)
        try:
            with tempfile.NamedTemporaryFile(suffix=".tfplan", delete=False) as tmp:
                plan_file = tmp.name

            plan_cmd = [self.tf_bin, "plan", "-out", plan_file, "-no-color"]
            if self.verbose:
                click.echo(f"      Running: {' '.join(plan_cmd)} (cwd={self.project_path})")
            plan_result = subprocess.run(plan_cmd, capture_output=True, text=True, check=False)
            if self.verbose:
                click.echo(f"      plan exit code: {plan_result.returncode}")
            if plan_result.returncode not in (0, 2):
                click.echo(f"      ❌ plan failed (exit {plan_result.returncode})")
                if plan_result.stderr.strip():
                    click.echo(f"      stderr: {plan_result.stderr.strip()}")
                return None

            show_cmd = [self.tf_bin, "show", "-json", plan_file]
            if self.verbose:
                click.echo(f"      Running: {' '.join(show_cmd)}")
            show_result = subprocess.run(show_cmd, capture_output=True, text=True, check=False)
            if show_result.returncode != 0:
                click.echo(f"      ❌ show -json failed (exit {show_result.returncode})")
                return None

            plan_json = json.loads(show_result.stdout)
            resource_changes = plan_json.get("resource_changes", [])

            if self.verbose:
                addresses = [rc.get("address") for rc in resource_changes]
                click.echo(f"      Resource changes in plan: {addresses}")

            for rc in resource_changes:
                if rc.get("address") == resource.address:
                    change = rc.get("change", {})
                    before = change.get("before") or {}
                    after = change.get("after") or {}
                    after_unknown = change.get("after_unknown") or {}
                    # before_sensitive mirrors before's structure with True where sensitive
                    before_sensitive = change.get("before_sensitive") or {}
                    sensitive_keys = {
                        k for k, v in before_sensitive.items()
                        if v is True or (isinstance(v, dict) and v)
                    }
                    # Only return attrs that are actually drifting:
                    # before != after, and not computed post-apply
                    drifted = {
                        k: before[k]
                        for k in before
                        if before[k] != after.get(k)
                        and not after_unknown.get(k)
                    }
                    if self.verbose:
                        click.echo(f"      Drifted attrs (before != after): {sorted(drifted.keys())}")
                        if sensitive_keys:
                            click.echo(f"      sensitive keys: {sorted(sensitive_keys)}")
                    return drifted, sensitive_keys

            return {}, set()  # not found in plan changes

        except Exception as e:
            click.echo(f"      ❌ Exception reading plan: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None  # None signals a hard error (distinct from empty tuple)
        finally:
            os.chdir(original_cwd)
            if plan_file:
                try:
                    Path(plan_file).unlink(missing_ok=True)
                except Exception:
                    pass

    # Diff computation — uses hcledit attribute get to read current values
    # ------------------------------------------------------------------

    def _compute_diffs(self, file_path: str, resource: ResourceChange,
                       state_attrs: Dict[str, Any]) -> Dict[str, Any]:
        diffs = {}
        for attr, state_val in state_attrs.items():
            # Block-type values: hcledit attribute get won't work; pass through
            # and let _sync_block handle idempotency internally.
            if _is_block_value(state_val):
                diffs[attr] = state_val
                continue

            address = f"resource.{resource.resource_type}.{resource.resource_name}.{attr}"
            current_val = self._hcledit_get(file_path, address)

            if current_val is None:
                # Attribute missing from config entirely
                diffs[attr] = state_val
                if self.verbose:
                    click.echo(f"      {attr}: missing in config → {state_val!r}")
            else:
                state_hcl = _to_hcl_value(state_val)
                if current_val.strip() != state_hcl.strip():
                    diffs[attr] = state_val
                    if self.verbose:
                        click.echo(f"      {attr}: config={current_val.strip()!r} → state={state_hcl!r}")

        return diffs

    def _hcledit_get(self, file_path: str, address: str) -> Optional[str]:
        """
        Run `hcledit attribute get <address> -f <file>`.
        Returns the raw HCL value string, or None if the attribute is absent.
        """
        cmd = ["hcledit", "attribute", "get", address, "-f", file_path]
        if self.verbose:
            click.echo(f"      Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout.strip()

    # ------------------------------------------------------------------
    # hcledit-based edits
    # ------------------------------------------------------------------

    def _apply_diffs_with_hcledit(self, file_path: str, resource: ResourceChange,
                                   diffs: Dict[str, Any]) -> bool:
        any_changed = False
        base_address = f"resource.{resource.resource_type}.{resource.resource_name}"
        for attr, value in diffs.items():
            address = f"{base_address}.{attr}"
            if _is_block_value(value):
                # Block-type: use recursive block sync instead of attribute set.
                # Lists of dicts = repeated blocks (e.g. rules{}, conditions{}).
                # Sync only the first dict item — providers typically allow one.
                items = [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, dict)]
                if not items:
                    continue
                if self._sync_block(file_path, address, items[0]):
                    click.echo(f"      ✅ Synced block {attr}")
                    any_changed = True
                else:
                    click.echo(f"      ⚠️  Block '{attr}' unchanged or failed")
            else:
                hcl_value = _to_hcl_value(value)
                existing = self._hcledit_get(file_path, address)
                if existing is not None:
                    success = self._hcledit_set(file_path, address, hcl_value)
                    verb = "Updated "
                else:
                    success = self._hcledit_append(file_path, address, hcl_value)
                    verb = "Inserted"

                if success:
                    click.echo(f"      ✅ {verb} {attr} = {hcl_value}")
                    any_changed = True
                else:
                    click.echo(f"      ❌ Failed to write {attr}")

        return any_changed

    def _sync_block(self, file_path: str, block_address: str,
                    block_data: Dict[str, Any]) -> bool:
        """
        Ensure a block exists at block_address and sync its scalar attributes.
        Nested blocks are handled recursively.
        """
        # Create the block if it doesn't already exist.
        # Must use `block append <parent> <child_type>` — NOT `block new <full.address>`
        # because block new treats the dotted address as labels on a new top-level block.
        if not self._hcledit_block_exists(file_path, block_address):
            if self.verbose:
                click.echo(f"        Creating block: {block_address}")
            if "." not in block_address:
                click.echo(f"        ❌ Cannot append top-level block: {block_address}")
                return False
            parent_address, child_type = block_address.rsplit(".", 1)
            cmd = ["hcledit", "block", "append", parent_address, child_type, "-f", file_path, "-u"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                click.echo(f"        ❌ block append failed: {result.stderr.strip()}")
                return False

        any_changed = False
        for attr, value in block_data.items():
            child_address = f"{block_address}.{attr}"
            if _is_block_value(value):
                items = value if isinstance(value, list) else [value]
                for block_item in items:
                    if isinstance(block_item, dict):
                        if self._sync_block(file_path, child_address, block_item):
                            any_changed = True
            else:
                if value is None or value == []:
                    continue  # omit null/empty-list values — defaults, not real attrs
                hcl_value = _to_hcl_value(value)
                existing = self._hcledit_get(file_path, child_address)
                if existing is not None:
                    if existing.strip() == hcl_value.strip():
                        continue  # already correct
                    success = self._hcledit_set(file_path, child_address, hcl_value)
                else:
                    success = self._hcledit_append(file_path, child_address, hcl_value)
                if success:
                    if self.verbose:
                        click.echo(f"        ✅ {attr} = {hcl_value}")
                    any_changed = True
                else:
                    click.echo(f"        ❌ Failed to write {attr} in block {block_address}")

        return any_changed

    def _hcledit_block_exists(self, file_path: str, address: str) -> bool:
        """Check if a block exists using `hcledit block get` (returns empty output when absent)."""
        cmd = ["hcledit", "block", "get", address, "-f", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return bool(result.stdout.strip())

    def _hcledit_set(self, file_path: str, address: str, hcl_value: str) -> bool:
        """hcledit attribute set <address> <value> -f <file> -u"""
        cmd = ["hcledit", "attribute", "set", address, hcl_value, "-f", file_path, "-u"]
        if self.verbose:
            click.echo(f"        Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if self.verbose and result.stdout.strip():
            click.echo(f"        stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            click.echo(f"        stderr: {result.stderr.strip()}")
        if self.verbose:
            click.echo(f"        Exit code: {result.returncode}")
        return result.returncode == 0

    def _hcledit_append(self, file_path: str, address: str, hcl_value: str) -> bool:
        """hcledit attribute append <address> <value> -f <file> -u"""
        cmd = ["hcledit", "attribute", "append", address, hcl_value, "-f", file_path, "-u"]
        if self.verbose:
            click.echo(f"        Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if self.verbose and result.stdout.strip():
            click.echo(f"        stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            click.echo(f"        stderr: {result.stderr.strip()}")
        if self.verbose:
            click.echo(f"        Exit code: {result.returncode}")
        return result.returncode == 0


# ------------------------------------------------------------------
# Value conversion: Python → HCL literal
# ------------------------------------------------------------------

def _is_block_value(value: Any) -> bool:
    """Return True if the value should be written as an HCL block rather than an attribute."""
    return isinstance(value, dict) or (
        isinstance(value, list) and len(value) > 0 and any(isinstance(v, dict) for v in value)
    )


def _to_hcl_value(value: Any) -> str:
    """Convert a Python value from Terraform state JSON to an HCL literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        if not value:
            return "[]"
        items = ", ".join(_to_hcl_value(v) for v in value)
        return f"[{items}]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = "\n".join(f'  {k} = {_to_hcl_value(v)}' for k, v in value.items())
        return f"{{\n{lines}\n}}"
    return f'"{value}"'
