"""Edit Terraform configuration files using hcledit CLI."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from .plan_parser import ResourceChange

# Attributes that are safe to auto-sync from state.
# Omit computed-only / identity fields that should never appear in config.
DRIFTABLE_ATTRS = {
    "allow_auto_merge",
    "allow_merge_commit",
    "allow_rebase_merge",
    "allow_squash_merge",
    "allow_update_branch",
    "archived",
    "delete_branch_on_merge",
    "description",
    "has_discussions",
    "has_downloads",
    "has_issues",
    "has_projects",
    "has_wiki",
    "homepage_url",
    "is_template",
    "merge_commit_message",
    "merge_commit_title",
    "squash_merge_commit_message",
    "squash_merge_commit_title",
    "topics",
    "visibility",
    "vulnerability_alerts",
    "web_commit_signoff_required",
}


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
        actual_data = self._get_resource_actual_values(resource)
        if actual_data is None:
            click.echo(f"    ❌ Could not read plan — aborting")
            return False
        if not actual_data:
            click.echo(f"    ❌ Address '{resource.address}' not found in plan changes")
            return False

        if self.verbose:
            click.echo(f"    Actual (before) keys: {sorted(actual_data.keys())}")

        # 2. Filter to driftable attributes only
        to_sync = {k: v for k, v in actual_data.items() if k in DRIFTABLE_ATTRS}
        if self.verbose:
            click.echo(f"    Driftable attributes to sync: {sorted(to_sync.keys())}")

        if not to_sync:
            click.echo(f"    No driftable attributes found for {resource.address}")
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

    def _get_resource_actual_values(self, resource: ResourceChange) -> Optional[Dict[str, Any]]:
        """
        Run `tofu plan -out=<tmp>` then `tofu show -json <tmp>` to read
        resource_changes[].change.before — the ACTUAL values in live
        infrastructure, not just what is recorded in local state.
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
                    before = rc.get("change", {}).get("before") or {}
                    if self.verbose:
                        click.echo(f"      before keys: {sorted(before.keys())}")
                    return before

            return {}  # not found in plan changes

        except Exception as e:
            click.echo(f"      ❌ Exception reading plan: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None
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
        for attr, value in diffs.items():
            address = f"resource.{resource.resource_type}.{resource.resource_name}.{attr}"
            hcl_value = _to_hcl_value(value)

            # Decide: set (attribute exists) or append (attribute missing)
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
