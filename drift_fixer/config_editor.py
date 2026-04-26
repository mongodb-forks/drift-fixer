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
        success = True
        
        for file_path, resources in file_resources_map.items():
            try:
                if self.verbose:
                    click.echo(f"Processing file: {Path(file_path).name}")
                    
                file_success = self._update_file(file_path, resources)
                if not file_success:
                    success = False
                    
            except Exception as e:
                click.echo(f"Error updating {file_path}: {e}")
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
                    # For delete operations, we might want to remove the resource
                    # This is risky, so we'll skip delete operations for now
                    if self.verbose:
                        click.echo(f"  Skipping delete operation for {resource.address}")
                    continue
                    
                elif resource.change_type in ['create', 'update', 'replace']:
                    # For create/update/replace, we need to get the current state
                    updated = self._sync_resource_with_state(file_path, resource)
                    if updated:
                        file_updated = True
                        
            except Exception as e:
                if self.verbose:
                    click.echo(f"    Error updating {resource.address}: {e}")
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
                if self.verbose:
                    click.echo(f"    [DRY RUN] Would sync {resource.address}")
                return True
                
            # Get current state for the resource
            state_data = self._get_resource_state(resource)
            if not state_data:
                if self.verbose:
                    click.echo(f"    No state data found for {resource.address}")
                return False
                
            # Use tfedit to update the resource configuration
            # The exact command syntax depends on tfedit's interface
            success = self._run_tfedit_sync(file_path, resource, state_data)
            
            if success and self.verbose:
                click.echo(f"    ✅ Synced {resource.address}")
                
            return success
            
        except Exception as e:
            if self.verbose:
                click.echo(f"    ❌ Failed to sync {resource.address}: {e}")
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
            # Change to project directory
            original_cwd = Path.cwd()
            os.chdir(self.project_path)
            
            try:
                # Use tofu/terraform show to get resource state
                result = subprocess.run(
                    [self.tf_bin, 'show', '-json'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                state_json = json.loads(result.stdout)
                
                # Find the resource in the state
                if 'values' in state_json and 'root_module' in state_json['values']:
                    resources = state_json['values']['root_module'].get('resources', [])
                    
                    for res in resources:
                        if res.get('address') == resource.address:
                            return res.get('values', {})
                            
                return None
                
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            if self.verbose:
                click.echo(f"    Could not get state for {resource.address}: {e}")
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
        try:
            # This is a placeholder implementation - the exact syntax depends on tfedit
            # Different approaches for tfedit:
            
            # Approach 1: Direct resource update
            if self._try_direct_resource_update(file_path, resource, state_data):
                return True
                
            # Approach 2: Import and sync
            if self._try_import_and_sync(file_path, resource, state_data):
                return True
                
            # Approach 3: Manual attribute updates
            if self._try_manual_attribute_updates(file_path, resource, state_data):
                return True
                
            return False
            
        except Exception as e:
            if self.verbose:
                click.echo(f"    tfedit operation failed: {e}")
            return False
            
    def _try_direct_resource_update(self, file_path: str, resource: ResourceChange, 
                                   state_data: Dict[str, Any]) -> bool:
        """Try to update resource directly with tfedit."""
        try:
            # Example tfedit command (syntax may vary):
            # tfedit --file=file.tf --resource=type.name --sync-with-state
            
            cmd = [
                'tfedit',
                f'--file={file_path}',
                f'--resource={resource.address}',
                '--sync-with-state'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=self.project_path
            )
            
            return result.returncode == 0
            
        except Exception:
            return False
            
    def _try_import_and_sync(self, file_path: str, resource: ResourceChange, 
                           state_data: Dict[str, Any]) -> bool:
        """Try to import resource and sync configuration."""
        try:
            # This approach would import the resource and then sync the config
            # Implementation depends on tfedit capabilities
            return False  # Placeholder
            
        except Exception:
            return False
            
    def _try_manual_attribute_updates(self, file_path: str, resource: ResourceChange, 
                                    state_data: Dict[str, Any]) -> bool:
        """Try to manually update specific attributes."""
        try:
            # This would update individual attributes in the Terraform file
            # to match the current state
            
            # For now, we'll use a simple approach of updating common drift-prone attributes
            success = False
            
            for attr_name, attr_value in state_data.items():
                if self._is_driftable_attribute(attr_name):
                    if self._update_attribute(file_path, resource, attr_name, attr_value):
                        success = True
                        
            return success
            
        except Exception:
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
        """Update a specific attribute in the Terraform file."""
        try:
            # Use tfedit to update a specific attribute
            cmd = [
                'tfedit',
                f'--file={file_path}',
                f'--resource={resource.address}',
                f'--set={attr_name}={json.dumps(attr_value) if isinstance(attr_value, (dict, list)) else str(attr_value)}'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=self.project_path
            )
            
            if result.returncode == 0 and self.verbose:
                click.echo(f"      Updated {attr_name} = {attr_value}")
                
            return result.returncode == 0
            
        except Exception as e:
            if self.verbose:
                click.echo(f"      Failed to update {attr_name}: {e}")
            return False