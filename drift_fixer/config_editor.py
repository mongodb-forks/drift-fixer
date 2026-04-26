"""Edit Terraform configuration files using tfedit CLI utility."""

import subprocess
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
import click
import json
import tempfile

from .plan_parser import ResourceChange


class ConfigEditor:
    """Edit Terraform configuration files using tfedit."""
    
    def __init__(self, project_path: Path, dry_run: bool = False, verbose: bool = False,
                 tf_bin: str = 'tofu'):
        self.project_path = project_path
        self.dry_run = dry_run
        self.verbose = verbose
        self.tf_bin = tf_bin
        
        # Check if tfedit is available
        if not self._check_tfedit_available():
            raise RuntimeError("tfedit CLI utility not found. Please install tfedit.")
            
    def _check_tfedit_available(self) -> bool:
        """
        Check if tfedit CLI is available.
        
        Returns:
            bool: True if tfedit is available.
        """
        try:
            result = subprocess.run(
                ['tfedit', 'version'],
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
            
    def update_resources(self, changed_resources: List[ResourceChange],
                        file_resources_map: Dict[str, List[ResourceChange]]) -> bool:
        """
        Update Terraform configuration files for the changed resources.

        Args:
            changed_resources: List of all changed resources.
            file_resources_map: Mapping of files to resources they contain.

        Returns:
            bool: True if all updates were successful.
        """
        if self.verbose:
            click.echo(f"  update_resources: {len(file_resources_map)} file(s) to process")

        success = True

        for file_path, resources in file_resources_map.items():
            click.echo(f"Processing file: {Path(file_path).name}")
            if self.verbose:
                click.echo(f"  Resources to update in this file:")
                for r in resources:
                    click.echo(f"    - {r.address} (change_type={r.change_type})")
            try:
                file_success = self._update_file(file_path, resources)
                if not file_success:
                    click.echo(f"  ⚠️  No updates applied to {Path(file_path).name}")
                    success = False
                else:
                    click.echo(f"  ✅ Successfully updated {Path(file_path).name}")
            except Exception as e:
                click.echo(f"  ❌ Exception while updating {file_path}: {e}")
                import traceback
                if self.verbose:
                    traceback.print_exc()
                success = False

        return success
        
    def _update_file(self, file_path: str, resources: List[ResourceChange]) -> bool:
        """
        Update a single Terraform file using tfedit.
        
        Args:
            file_path: Path to the Terraform file.
            resources: Resources in this file that need updating.
            
        Returns:
            bool: True if successful.
        """
        file_updated = False

        for resource in resources:
            try:
                if resource.change_type == 'delete':
                    click.echo(f"  Skipping delete operation for {resource.address} (manual review required)")
                    continue

                elif resource.change_type in ['create', 'update', 'replace']:
                    click.echo(f"  Syncing {resource.address} (change_type={resource.change_type})...")
                    updated = self._sync_resource_with_state(file_path, resource)
                    if updated:
                        file_updated = True
                    else:
                        click.echo(f"  ⚠️  Sync returned False for {resource.address}")

                else:
                    click.echo(f"  ⚠️  Unknown change_type '{resource.change_type}' for {resource.address}, skipping")

            except Exception as e:
                click.echo(f"  ❌ Exception processing {resource.address}: {e}")
                if self.verbose:
                    import traceback
                    traceback.print_exc()
                continue

        return file_updated
        
    def _sync_resource_with_state(self, file_path: str, resource: ResourceChange) -> bool:
        """
        Sync a resource configuration with its current state using tfedit.
        
        Args:
            file_path: Path to the Terraform file.
            resource: Resource to sync.
            
        Returns:
            bool: True if successful.
        """
        try:
            if self.dry_run:
                click.echo(f"    [DRY RUN] Would sync {resource.address}")
                return True

            # Get current state for the resource
            click.echo(f"    Fetching state for {resource.address} via `{self.tf_bin} show -json`...")
            state_data = self._get_resource_state(resource)
            if not state_data:
                click.echo(f"    ❌ No state data found for {resource.address} — is the resource in the state file?")
                return False

            if self.verbose:
                click.echo(f"    State keys for {resource.address}: {list(state_data.keys())}")

            success = self._run_tfedit_sync(file_path, resource, state_data)

            if success:
                click.echo(f"    ✅ Synced {resource.address}")
            else:
                click.echo(f"    ❌ All tfedit approaches failed for {resource.address}")

            return success

        except Exception as e:
            click.echo(f"    ❌ Exception syncing {resource.address}: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return False
            
    def _get_resource_state(self, resource: ResourceChange) -> Optional[Dict[str, Any]]:
        """
        Get the current state of a resource from Terraform state.
        
        Args:
            resource: Resource to get state for.
            
        Returns:
            Optional[Dict[str, Any]]: Resource state data or None.
        """
        try:
            original_cwd = Path.cwd()
            os.chdir(self.project_path)

            try:
                cmd = [self.tf_bin, 'show', '-json']
                if self.verbose:
                    click.echo(f"      Running: {' '.join(cmd)} (cwd={self.project_path})")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )

                if self.verbose:
                    click.echo(f"      Exit code: {result.returncode}")
                if result.stderr.strip():
                    click.echo(f"      stderr: {result.stderr.strip()}")

                if result.returncode != 0:
                    click.echo(f"      ❌ `{self.tf_bin} show -json` failed (exit {result.returncode})")
                    return None

                state_json = json.loads(result.stdout)
                resources_in_state = (
                    state_json.get('values', {})
                              .get('root_module', {})
                              .get('resources', [])
                )

                if self.verbose:
                    addresses = [r.get('address') for r in resources_in_state]
                    click.echo(f"      Resources in state: {addresses}")

                for res in resources_in_state:
                    if res.get('address') == resource.address:
                        return res.get('values', {})

                click.echo(f"      ⚠️  Address '{resource.address}' not found in state")
                return None

            finally:
                os.chdir(original_cwd)

        except Exception as e:
            click.echo(f"      ❌ Exception reading state: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None
            
    def _run_tfedit_sync(self, file_path: str, resource: ResourceChange, 
                        state_data: Dict[str, Any]) -> bool:
        """
        Run tfedit to sync resource configuration with state.
        
        Args:
            file_path: Path to Terraform file.
            resource: Resource to sync.
            state_data: Current state data for the resource.
            
        Returns:
            bool: True if successful.
        """
        click.echo(f"    Attempting tfedit approaches for {resource.address}...")
        try:
            # Approach 1: Direct resource update
            click.echo(f"      Approach 1: direct resource update")
            if self._try_direct_resource_update(file_path, resource, state_data):
                click.echo(f"      ✅ Approach 1 succeeded")
                return True
            click.echo(f"      ✗ Approach 1 failed")

            # Approach 2: Manual attribute updates
            click.echo(f"      Approach 2: manual attribute updates")
            if self._try_manual_attribute_updates(file_path, resource, state_data):
                click.echo(f"      ✅ Approach 2 succeeded")
                return True
            click.echo(f"      ✗ Approach 2 failed")

            return False

        except Exception as e:
            click.echo(f"    ❌ Exception in _run_tfedit_sync: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return False
            
    def _try_direct_resource_update(self, file_path: str, resource: ResourceChange,
                                   state_data: Dict[str, Any]) -> bool:
        """Try to update resource directly with tfedit."""
        try:
            cmd = [
                'tfedit',
                'block', 'replace-attrs',
                '--from-json', '-',
                file_path,
                f'{resource.resource_type}.{resource.resource_name}',
            ]

            state_input = json.dumps(state_data)
            if self.verbose:
                click.echo(f"        Running: {' '.join(cmd)}")
                click.echo(f"        stdin JSON keys: {list(state_data.keys())}")

            result = subprocess.run(
                cmd,
                input=state_input,
                capture_output=True,
                text=True,
                check=False,
                cwd=self.project_path
            )

            click.echo(f"        Exit code: {result.returncode}")
            if result.stdout.strip():
                click.echo(f"        stdout: {result.stdout.strip()}")
            if result.stderr.strip():
                click.echo(f"        stderr: {result.stderr.strip()}")

            return result.returncode == 0

        except Exception as e:
            click.echo(f"        Exception in direct update: {e}")
            return False
            
    def _try_manual_attribute_updates(self, file_path: str, resource: ResourceChange,
                                    state_data: Dict[str, Any]) -> bool:
        """Try to manually update specific attributes one at a time."""
        try:
            driftable = {k: v for k, v in state_data.items() if self._is_driftable_attribute(k)}
            if self.verbose:
                click.echo(f"        Driftable attributes to attempt: {list(driftable.keys())}")

            success = False
            for attr_name, attr_value in driftable.items():
                if self._update_attribute(file_path, resource, attr_name, attr_value):
                    success = True

            return success

        except Exception as e:
            click.echo(f"        Exception in manual attribute update: {e}")
            return False
            
    def _is_driftable_attribute(self, attr_name: str) -> bool:
        """Check if an attribute commonly drifts and should be updated."""
        # Common attributes that drift and are safe to update
        driftable_attrs = {
            'description', 'tags', 'name', 'visibility', 'default_branch',
            'homepage_url', 'topics', 'archived', 'has_issues', 'has_projects',
            'has_wiki', 'allow_merge_commit', 'allow_squash_merge', 'allow_rebase_merge'
        }
        return attr_name in driftable_attrs
        
    def _update_attribute(self, file_path: str, resource: ResourceChange,
                         attr_name: str, attr_value: Any) -> bool:
        """Update a specific attribute in the Terraform file using tfedit."""
        try:
            if isinstance(attr_value, bool):
                value_str = str(attr_value).lower()
            elif isinstance(attr_value, (dict, list)):
                value_str = json.dumps(attr_value)
            else:
                value_str = str(attr_value)

            cmd = [
                'tfedit',
                'block', 'set-attr',
                file_path,
                f'{resource.resource_type}.{resource.resource_name}',
                attr_name,
                value_str,
            ]

            if self.verbose:
                click.echo(f"        Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=self.project_path
            )

            if self.verbose:
                click.echo(f"        Exit code: {result.returncode}")
                if result.stdout.strip():
                    click.echo(f"        stdout: {result.stdout.strip()}")
            if result.stderr.strip():
                click.echo(f"        stderr: {result.stderr.strip()}")

            if result.returncode == 0:
                click.echo(f"        ✅ Set {attr_name} = {value_str}")

            return result.returncode == 0

        except Exception as e:
            click.echo(f"        ❌ Exception setting {attr_name}: {e}")
            return False