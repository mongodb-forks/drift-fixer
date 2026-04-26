"""Handle Git operations for committing drift fixes."""

import subprocess
import os
from pathlib import Path
from typing import List, Optional
import click


class GitManager:
    """Handle Git operations for the drift fixer."""
    
    def __init__(self, project_path: Path, verbose: bool = False):
        self.project_path = project_path
        self.verbose = verbose
        
    def is_git_repo(self) -> bool:
        """
        Check if the project directory is a Git repository.
        
        Returns:
            bool: True if it's a Git repository.
        """
        git_dir = self.project_path / ".git"
        return git_dir.exists()
        
    def has_changes(self) -> bool:
        """
        Check if there are any uncommitted changes.
        
        Returns:
            bool: True if there are uncommitted changes.
        """
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            
            # If there's any output, there are changes
            return bool(result.stdout.strip())
            
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            if self.verbose:
                click.echo("Git not found - cannot check for changes")
            return False
            
    def get_changed_files(self) -> List[str]:
        """
        Get list of files that have been changed.
        
        Returns:
            List[str]: List of changed file paths.
        """
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            
            changed_files = []
            for line in result.stdout.strip().split('\\n'):
                if line:
                    # Git status format: "XY filename"
                    filename = line[3:]  # Skip the status codes and space
                    changed_files.append(filename)
                    
            return changed_files
            
        except subprocess.CalledProcessError:
            return []
        except FileNotFoundError:
            return []
            
    def add_files(self, file_paths: Optional[List[str]] = None) -> bool:
        """
        Add files to Git staging area.
        
        Args:
            file_paths: Specific files to add, or None to add all .tf files.
            
        Returns:
            bool: True if successful.
        """
        try:
            if file_paths is None:
                # Add all .tf files
                tf_files = list(self.project_path.glob("*.tf"))
                tf_files.extend(list(self.project_path.glob("**/*.tf")))
                
                # Filter out files in .terraform directory
                tf_files = [f for f in tf_files if ".terraform" not in f.parts]
                
                if not tf_files:
                    if self.verbose:
                        click.echo("No .tf files found to add")
                    return True
                    
                file_paths = [str(f.relative_to(self.project_path)) for f in tf_files]
                
            for file_path in file_paths:
                result = subprocess.run(
                    ['git', 'add', file_path],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=self.project_path
                )
                
                if self.verbose:
                    click.echo(f"  Added {file_path} to Git staging")
                    
            return True
            
        except subprocess.CalledProcessError as e:
            if self.verbose:
                click.echo(f"Failed to add files to Git: {e.stderr}")
            return False
        except FileNotFoundError:
            if self.verbose:
                click.echo("Git not found")
            return False
            
    def commit_changes(self, message: str) -> bool:
        """
        Commit the staged changes.
        
        Args:
            message: Commit message.
            
        Returns:
            bool: True if successful.
        """
        try:
            # First check if there are any changes to commit
            if not self.has_changes():
                if self.verbose:
                    click.echo("No changes to commit")
                return True
                
            # Add changed .tf files
            if not self.add_files():
                return False
                
            # Check if there are staged changes
            result = subprocess.run(
                ['git', 'diff', '--cached', '--name-only'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            
            if not result.stdout.strip():
                if self.verbose:
                    click.echo("No staged changes to commit")
                return True
                
            # Commit the changes
            result = subprocess.run(
                ['git', 'commit', '-m', message],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            
            if self.verbose:
                click.echo(f"✅ Committed changes: {message}")
                click.echo(f"   Commit: {self._get_last_commit_hash()}")
                
            return True
            
        except subprocess.CalledProcessError as e:
            if self.verbose:
                click.echo(f"Failed to commit changes: {e.stderr}")
            return False
        except FileNotFoundError:
            if self.verbose:
                click.echo("Git not found")
            return False
            
    def _get_last_commit_hash(self) -> str:
        """Get the hash of the last commit."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"
            
    def create_branch(self, branch_name: str) -> bool:
        """
        Create and switch to a new branch.
        
        Args:
            branch_name: Name of the new branch.
            
        Returns:
            bool: True if successful.
        """
        try:
            # Create and switch to new branch
            result = subprocess.run(
                ['git', 'checkout', '-b', branch_name],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            
            if self.verbose:
                click.echo(f"Created and switched to branch: {branch_name}")
                
            return True
            
        except subprocess.CalledProcessError as e:
            if self.verbose:
                click.echo(f"Failed to create branch {branch_name}: {e.stderr}")
            return False
        except FileNotFoundError:
            if self.verbose:
                click.echo("Git not found")
            return False
            
    def get_current_branch(self) -> Optional[str]:
        """
        Get the name of the current branch.
        
        Returns:
            Optional[str]: Current branch name or None if not available.
        """
        try:
            result = subprocess.run(
                ['git', 'branch', '--show-current'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_path
            )
            
            return result.stdout.strip()
            
        except subprocess.CalledProcessError:
            return None
        except FileNotFoundError:
            return None