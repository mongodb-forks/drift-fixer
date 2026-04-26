"""Analyze Terraform files to find resources using tfparse."""

import os
import re
from pathlib import Path
from typing import List, Dict, Set, Optional
import click

try:
    import tfparse
except ImportError:
    tfparse = None

from .plan_parser import ResourceChange


class FileAnalyzer:
    """Analyze Terraform configuration files to locate resources."""
    
    def __init__(self, project_path: Path, verbose: bool = False):
        self.project_path = project_path
        self.verbose = verbose
        
        if tfparse is None:
            raise RuntimeError("tfparse library not found. Install with: pip install tfparse")
            
    def find_resource_files(self, changed_resources: List[ResourceChange]) -> Dict[str, List[ResourceChange]]:
        """
        Find which files contain the changed resources.
        
        Args:
            changed_resources: List of resources that have changed.
            
        Returns:
            Dict[str, List[ResourceChange]]: Mapping of file paths to resources they contain.
        """
        file_resources_map = {}
        
        # Get all .tf files in the project
        tf_files = self._get_terraform_files()
        
        if self.verbose:
            click.echo(f"Analyzing {len(tf_files)} Terraform files...")
            
        for tf_file in tf_files:
            try:
                resources_in_file = self._analyze_file(tf_file, changed_resources)
                if resources_in_file:
                    file_resources_map[str(tf_file)] = resources_in_file
                    if self.verbose:
                        click.echo(f"  {tf_file.name}: {len(resources_in_file)} matching resources")
                        
            except Exception as e:
                if self.verbose:
                    click.echo(f"  Warning: Could not analyze {tf_file}: {e}")
                continue
                
        return file_resources_map
        
    def _get_terraform_files(self) -> List[Path]:
        """
        Get all .tf files in the project directory.
        
        Returns:
            List[Path]: List of Terraform configuration files.
        """
        tf_files = []
        
        # Find all .tf files (excluding .terraform directory)
        for tf_file in self.project_path.rglob("*.tf"):
            # Skip files in .terraform directory
            if ".terraform" in tf_file.parts:
                continue
            tf_files.append(tf_file)
            
        return tf_files
        
    def _analyze_file(self, tf_file: Path, changed_resources: List[ResourceChange]) -> List[ResourceChange]:
        """
        Analyze a single Terraform file to find matching resources.
        
        Args:
            tf_file: Path to the Terraform file.
            changed_resources: List of resources to look for.
            
        Returns:
            List[ResourceChange]: Resources found in this file.
        """
        try:
            # Parse the Terraform file using tfparse
            parsed = tfparse.load_from_path(str(tf_file))
            
            resources_in_file = []
            
            # Check if the file has resources
            if not hasattr(parsed, 'resource') or not parsed.resource:
                return resources_in_file
                
            # Iterate through resources in the parsed file
            for resource_type, resources in parsed.resource.items():
                for resource_name in resources.keys():
                    resource_address = f"{resource_type}.{resource_name}"
                    
                    # Check if this resource matches any of our changed resources
                    for changed_resource in changed_resources:
                        if self._resource_matches(changed_resource, resource_type, resource_name, resource_address):
                            resources_in_file.append(changed_resource)
                            
            return resources_in_file
            
        except Exception as e:
            # If tfparse fails, try a simple text-based search as fallback
            if self.verbose:
                click.echo(f"    tfparse failed for {tf_file}, falling back to text search: {e}")
            return self._fallback_text_search(tf_file, changed_resources)
            
    def _resource_matches(self, changed_resource: ResourceChange, 
                         file_resource_type: str, file_resource_name: str, 
                         file_resource_address: str) -> bool:
        """
        Check if a changed resource matches a resource found in a file.
        
        Args:
            changed_resource: The resource change we're looking for.
            file_resource_type: Resource type found in file.
            file_resource_name: Resource name found in file.
            file_resource_address: Full address found in file.
            
        Returns:
            bool: True if they match.
        """
        # Direct address match
        if changed_resource.address == file_resource_address:
            return True
            
        # Type and name match
        if (changed_resource.resource_type == file_resource_type and 
            changed_resource.resource_name == file_resource_name):
            return True
            
        # Handle array/indexed resources (e.g., resource.name[0])
        base_address = changed_resource.address.split('[')[0]
        if base_address == file_resource_address:
            return True
            
        return False
        
    def _fallback_text_search(self, tf_file: Path, changed_resources: List[ResourceChange]) -> List[ResourceChange]:
        """
        Fallback method to search for resources using simple text matching.
        
        Args:
            tf_file: Path to the Terraform file.
            changed_resources: List of resources to search for.
            
        Returns:
            List[ResourceChange]: Resources found in this file.
        """
        try:
            content = tf_file.read_text()
            found_resources = []
            
            for resource in changed_resources:
                # Look for resource block declarations
                resource_pattern = f'resource\\s+"{resource.resource_type}"\\s+"{resource.resource_name}"'
                if re.search(resource_pattern, content):
                    found_resources.append(resource)
                    continue
                    
                # Look for resource references
                if resource.address in content:
                    found_resources.append(resource)
                    
            return found_resources
            
        except Exception as e:
            if self.verbose:
                click.echo(f"    Text search also failed for {tf_file}: {e}")
            return []
            
    def get_file_structure(self) -> Dict[str, any]:
        """
        Get a summary of the project's Terraform file structure.
        
        Returns:
            Dict[str, any]: Structure information.
        """
        tf_files = self._get_terraform_files()
        structure = {
            'total_files': len(tf_files),
            'files': [],
            'total_resources': 0
        }
        
        for tf_file in tf_files:
            try:
                parsed = tfparse.load_from_path(str(tf_file))
                resource_count = 0
                
                if hasattr(parsed, 'resource') and parsed.resource:
                    for resource_type, resources in parsed.resource.items():
                        resource_count += len(resources)
                        
                structure['files'].append({
                    'path': str(tf_file.relative_to(self.project_path)),
                    'resource_count': resource_count
                })
                structure['total_resources'] += resource_count
                
            except Exception:
                structure['files'].append({
                    'path': str(tf_file.relative_to(self.project_path)),
                    'resource_count': 0,
                    'error': 'Could not parse file'
                })
                
        return structure