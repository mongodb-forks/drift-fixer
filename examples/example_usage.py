#!/usr/bin/env python3
"""
Example usage of the drift fixer.

This script demonstrates how to use the drift-fixer programmatically.
"""

from pathlib import Path
from drift_fixer.main import DriftFixer


def main():
    """Example of using drift fixer programmatically."""
    
    # Path to your Terraform project
    terraform_project_path = Path("./examples")
    
    print(f"🔍 Analyzing Terraform project: {terraform_project_path}")
    
    try:
        # Create drift fixer instance
        fixer = DriftFixer(
            project_path=terraform_project_path,
            dry_run=True,  # Set to False to make actual changes
            auto_commit=False,  # Set to True to auto-commit fixes
            verbose=True
        )
        
        # Run the drift fixing process
        success = fixer.run()
        
        if success:
            print("✅ Drift analysis completed successfully!")
        else:
            print("❌ Drift analysis failed or no changes needed.")
            
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()