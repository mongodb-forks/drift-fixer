"""Parse Terraform plan output to extract changed resources."""

import re
from typing import List, Set, NamedTuple, Optional
from dataclasses import dataclass
import click


@dataclass
class ResourceChange:
    """Represents a resource change detected in terraform plan."""
    resource_type: str
    resource_name: str
    change_type: str  # 'create', 'update', 'delete', 'replace'
    address: str  # Full terraform address like "github_repository.example"
    

class PlanParser:
    """Parse terraform plan output to identify changed resources."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        
        # Regex patterns for parsing terraform plan output
        self.resource_patterns = [
            # Standard resource changes
            re.compile(r'^\s*[#~+-]\s+resource\s+"([^"]+)"\s+"([^"]+)"\s+{'),
            # Resource address patterns
            re.compile(r'^\s*[#~+-]\s+([a-zA-Z0-9_]+\.[a-zA-Z0-9_\[\].-]+)'),
        ]
        
        # Change type indicators
        self.change_indicators = {
            '+': 'create',
            '-': 'delete', 
            '~': 'update',
            '-/+': 'replace',
            '+/-': 'replace'
        }
        
    def parse_changes(self, plan_output: List[str]) -> List[ResourceChange]:
        """
        Parse terraform plan output to extract changed resources.
        
        Args:
            plan_output: Lines of terraform plan output.
            
        Returns:
            List[ResourceChange]: List of detected resource changes.
        """
        changes = []
        current_resource = None
        
        for line in plan_output:
            # Skip empty lines and comments
            if not line.strip() or line.strip().startswith('Terraform'):
                continue
                
            # Look for resource change indicators
            change_match = self._parse_resource_line(line)
            if change_match:
                changes.append(change_match)
                if self.verbose:
                    click.echo(f"  Found change: {change_match.address} ({change_match.change_type})")
        
        if self.verbose:
            click.echo(f"Parsed {len(changes)} resource changes from plan output.")
            
        return changes
        
    def _parse_resource_line(self, line: str) -> Optional[ResourceChange]:
        """
        Parse a single line from terraform plan to extract resource change.
        
        Args:
            line: A single line from terraform plan output.
            
        Returns:
            Optional[ResourceChange]: Parsed resource change or None.
        """
        line = line.strip()
        
        # Look for change indicators at the start of the line
        change_type = None
        for indicator, change_name in self.change_indicators.items():
            if line.startswith(indicator):
                change_type = change_name
                break
                
        if not change_type:
            return None
            
        # Try to extract resource information using different patterns
        
        # Pattern 1: Full resource declaration
        # Example: # resource "github_repository" "example" {
        resource_match = re.search(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*{', line)
        if resource_match:
            resource_type = resource_match.group(1)
            resource_name = resource_match.group(2)
            address = f"{resource_type}.{resource_name}"
            
            return ResourceChange(
                resource_type=resource_type,
                resource_name=resource_name,
                change_type=change_type,
                address=address
            )
        
        # Pattern 2: Resource address
        # Example: # github_repository.example will be updated in-place
        address_match = re.search(r'([a-zA-Z0-9_]+\.[a-zA-Z0-9_\[\].-]+)', line)
        if address_match:
            address = address_match.group(1)
            
            # Split address to get type and name
            parts = address.split('.', 1)
            if len(parts) >= 2:
                resource_type = parts[0]
                resource_name = parts[1]
                
                return ResourceChange(
                    resource_type=resource_type,
                    resource_name=resource_name,
                    change_type=change_type,
                    address=address
                )
        
        # Pattern 3: Simple resource reference
        # Try to extract from various terraform plan formats
        simple_match = re.search(r'([a-zA-Z0-9_]+)\.([a-zA-Z0-9_\[\].-]+)', line)
        if simple_match:
            resource_type = simple_match.group(1)
            resource_name = simple_match.group(2)
            address = f"{resource_type}.{resource_name}"
            
            return ResourceChange(
                resource_type=resource_type,
                resource_name=resource_name,
                change_type=change_type,
                address=address
            )
            
        return None
        
    def _deduplicate_changes(self, changes: List[ResourceChange]) -> List[ResourceChange]:
        """
        Remove duplicate resource changes.
        
        Args:
            changes: List of resource changes that may contain duplicates.
            
        Returns:
            List[ResourceChange]: Deduplicated list.
        """
        seen_addresses = set()
        unique_changes = []
        
        for change in changes:
            if change.address not in seen_addresses:
                unique_changes.append(change)
                seen_addresses.add(change.address)
                
        return unique_changes