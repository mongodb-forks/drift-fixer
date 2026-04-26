#!/usr/bin/env python3
"""Main CLI interface for drift-fixer."""

import os
import sys
import click
from pathlib import Path
from typing import Optional

from .terraform_runner import TerraformRunner
from .plan_parser import PlanParser
from .file_analyzer import FileAnalyzer
from .config_editor import ConfigEditor
from .git_manager import GitManager


@click.command()
@click.option(
    '--path', '-p',
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path.cwd(),
    help='Path to the Terraform project directory (default: current directory)'
)
@click.option(
    '--dry-run', '-n',
    is_flag=True,
    help='Show what would be changed without making actual modifications'
)
@click.option(
    '--auto-commit', '-c',
    is_flag=True,
    default=True,
    help='Automatically commit changes if drift is fixed (default: True)'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='Enable verbose output'
)
@click.option(
    '--tf-bin',
    default='tofu',
    show_default=True,
    envvar='DRIFT_FIXER_TF_BIN',
    help='Path or name of the Terraform/OpenTofu CLI binary to use'
)
def cli(path: Path, dry_run: bool, auto_commit: bool, verbose: bool, tf_bin: str):
    """
    Terraform Drift Fixer - Automatically detect and fix configuration drift.
    
    This tool runs terraform plan to detect drift, analyzes which resources
    have changed, and automatically updates the Terraform configuration files
    to match the current infrastructure state.
    """
    if verbose:
        click.echo(f"Starting drift analysis in: {path}")
        click.echo(f"Using CLI binary: {tf_bin}")
    
    try:
        fixer = DriftFixer(path, dry_run, auto_commit, verbose, tf_bin)
        result = fixer.run()
        
        if result:
            click.echo("✅ Drift fixing completed successfully!")
            sys.exit(0)
        else:
            click.echo("❌ Drift fixing failed or no changes were needed.")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


class DriftFixer:
    """Main orchestrator for the drift fixing process."""
    
    def __init__(self, project_path: Path, dry_run: bool = False,
                 auto_commit: bool = True, verbose: bool = False,
                 tf_bin: str = 'tofu'):
        self.project_path = project_path
        self.dry_run = dry_run
        self.auto_commit = auto_commit
        self.verbose = verbose
        self.tf_bin = tf_bin
        
        # Initialize components
        self.terraform = TerraformRunner(project_path, verbose, tf_bin)
        self.plan_parser = PlanParser(verbose)
        self.file_analyzer = FileAnalyzer(project_path, verbose)
        self.config_editor = ConfigEditor(project_path, dry_run, verbose, tf_bin)
        self.git_manager = GitManager(project_path, verbose)
        
    def run(self) -> bool:
        """
        Main workflow to detect and fix drift.
        
        Returns:
            bool: True if drift was fixed successfully, False otherwise.
        """
        if self.verbose:
            click.echo("🔍 Step 1: Running initial terraform plan...")
            
        # Step 1: Run terraform plan to detect drift
        plan_output = self.terraform.run_plan()
        if not plan_output:
            if self.verbose:
                click.echo("ℹ️  No changes detected in terraform plan.")
            return True
            
        if self.verbose:
            click.echo(f"📋 Step 2: Parsing plan output ({len(plan_output)} lines)...")
            
        # Step 2: Parse the plan to identify changed resources
        changed_resources = self.plan_parser.parse_changes(plan_output)
        if not changed_resources:
            if self.verbose:
                click.echo("ℹ️  No resource changes found in plan.")
            return True
            
        click.echo(f"📊 Found {len(changed_resources)} resources with drift:")
        for resource in changed_resources:
            click.echo(f"  - {resource.resource_type}.{resource.resource_name}")
            
        if self.verbose:
            click.echo("🔍 Step 3: Analyzing configuration files...")
            
        # Step 3: Find which files contain the drifted resources
        file_resources_map = self.file_analyzer.find_resource_files(changed_resources)
        
        if self.verbose:
            click.echo(f"📝 Step 4: Updating {len(file_resources_map)} configuration files...")
            
        # Step 4: Edit the configuration files
        edit_success = self.config_editor.update_resources(changed_resources, file_resources_map)
        if not edit_success:
            click.echo("❌ Failed to update configuration files.")
            return False
            
        if self.dry_run:
            click.echo("🔍 Dry run completed - no files were modified.")
            return True
            
        if self.verbose:
            click.echo("✅ Step 5: Running validation plan...")
            
        # Step 5: Run terraform plan again to verify fixes
        validation_output = self.terraform.run_plan()
        if validation_output:
            click.echo("⚠️  Warning: Drift still detected after fixes.")
            click.echo("Manual review may be required.")
            return False
            
        # Step 6: Commit changes if auto-commit is enabled and git repo exists
        if self.auto_commit and self.git_manager.is_git_repo():
            if self.verbose:
                click.echo("📝 Step 6: Committing changes...")
            self.git_manager.commit_changes("Fix Terraform configuration drift")
            
        return True


if __name__ == "__main__":
    cli()