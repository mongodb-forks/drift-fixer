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
        tf_files = self._get_terraform_files()

        if self.verbose:
            click.echo(f"Analyzing {len(tf_files)} Terraform files...")

        # tfparse requires a directory path, so parse each unique parent dir once
        # to validate which resource addresses actually exist in the config.
        known_addresses: set = set()
        parsed_dirs: set = set()
        for tf_file in tf_files:
            parent = tf_file.parent
            if parent in parsed_dirs:
                continue
            parsed_dirs.add(parent)
            try:
                parsed = tfparse.load_from_path(str(parent))
                if hasattr(parsed, 'resource') and parsed.resource:
                    for resource_type, resources in parsed.resource.items():
                        for resource_name in resources.keys():
                            known_addresses.add(f"{resource_type}.{resource_name}")
            except Exception as e:
                if self.verbose:
                    click.echo(f"  tfparse warning for {parent}: {e}")

        if self.verbose and known_addresses:
            click.echo(f"  tfparse found {len(known_addresses)} resource(s) in config")

        # Use text search to map each changed resource to its specific file.
        # Filter against known_addresses when tfparse succeeded; fall back to
        # all changed_resources when it didn't find anything (e.g. parse error).
        resources_to_locate = (
            [r for r in changed_resources if r.address in known_addresses]
            if known_addresses
            else changed_resources
        )

        for tf_file in tf_files:
            resources_in_file = self._fallback_text_search(tf_file, resources_to_locate)
            if resources_in_file:
                file_resources_map[str(tf_file)] = resources_in_file
                if self.verbose:
                    click.echo(f"  {tf_file.name}: {len(resources_in_file)} matching resources")

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
                # Count resource blocks via text search (tfparse needs a directory,
                # so per-file counting is done with a simple regex here)
                content = tf_file.read_text()
                resource_count = len(re.findall(r'^\s*resource\s+"', content, re.MULTILINE))

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