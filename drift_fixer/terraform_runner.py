"""Handle running Terraform commands and processing their output."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List
import click


class TerraformRunner:
    """Handles running Terraform CLI commands."""
    
    def __init__(self, project_path: Path, verbose: bool = False):
        self.project_path = project_path
        self.verbose = verbose
        
    def run_plan(self) -> Optional[List[str]]:
        """
        Run terraform plan and return the output lines if changes are detected.
        
        Returns:
            Optional[List[str]]: Plan output lines if changes detected, None if no changes.
        """
        try:
            if self.verbose:
                click.echo(f"Running terraform plan in {self.project_path}")
                
            # Change to the project directory
            original_cwd = Path.cwd()
            os.chdir(self.project_path)
            
            try:
                # Run terraform plan with machine-readable output
                result = subprocess.run(
                    ['terraform', 'plan', '-detailed-exitcode', '-no-color'],
                    capture_output=True,
                    text=True,
                    check=False  # Don't raise exception on non-zero exit
                )
                
                # Terraform plan exit codes:
                # 0 = No changes
                # 1 = Error
                # 2 = Changes detected
                
                if result.returncode == 0:
                    if self.verbose:
                        click.echo("No changes detected.")
                    return None
                elif result.returncode == 1:
                    raise RuntimeError(f"Terraform plan failed: {result.stderr}")
                elif result.returncode == 2:
                    if self.verbose:
                        click.echo("Changes detected in terraform plan.")
                    return result.stdout.splitlines()
                else:
                    raise RuntimeError(f"Unexpected exit code from terraform plan: {result.returncode}")
                    
            finally:
                os.chdir(original_cwd)
                
        except FileNotFoundError:
            raise RuntimeError("Terraform CLI not found. Please install Terraform.")
        except Exception as e:
            raise RuntimeError(f"Failed to run terraform plan: {e}")
            
    def run_init(self) -> bool:
        """
        Run terraform init if needed.
        
        Returns:
            bool: True if successful.
        """
        try:
            if self.verbose:
                click.echo("Running terraform init...")
                
            original_cwd = Path.cwd()
            os.chdir(self.project_path)
            
            try:
                result = subprocess.run(
                    ['terraform', 'init'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                if self.verbose:
                    click.echo("Terraform init completed successfully.")
                return True
                
            finally:
                os.chdir(original_cwd)
                
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Terraform init failed: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError("Terraform CLI not found. Please install Terraform.")
            
    def validate_terraform_project(self) -> bool:
        """
        Validate that the current directory is a valid Terraform project.
        
        Returns:
            bool: True if valid Terraform project.
        """
        # Check for .tf files
        tf_files = list(self.project_path.glob("*.tf"))
        if not tf_files:
            raise RuntimeError(f"No .tf files found in {self.project_path}")
            
        # Check if terraform init has been run
        terraform_dir = self.project_path / ".terraform"
        if not terraform_dir.exists():
            if self.verbose:
                click.echo("Terraform not initialized. Running terraform init...")
            self.run_init()
            
        return True