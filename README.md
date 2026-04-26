# Terraform Drift Fixer

A Python utility to automatically detect and fix configuration drift in Terraform repositories.

## Overview

This tool automatically detects infrastructure drift by comparing Terraform plans with the actual infrastructure state, then uses automated editing tools to update the Terraform configuration files to match the current infrastructure state.

## Features

- Detects drift by running `terraform plan`
- Parses plan output to identify changed resources
- Uses `tfparse` to locate configuration files containing drifted resources
- Uses `tfedit` CLI to automatically update configuration files
- Validates fixes by running a second `terraform plan`
- Commits changes automatically when drift is successfully resolved

## Workflow

1. Run `terraform plan` to detect changes
2. Parse the plan file to identify resources with drift
3. Use `tfparse` to find which files contain the drifted resources
4. Use `tfedit` to update the configuration files
5. Run `terraform plan` again to verify drift is fixed
6. Commit changes if no drift remains

## Installation

This is a UV project. Install UV first if you haven't already:

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install the project:

```bash
# Clone the repository
git clone <repository-url>
cd drift-fixer

# Install dependencies and create virtual environment
uv sync

# Install the tool for development
uv pip install -e .
```

## Usage

```bash
# Install and run with UV
uv run drift-fixer

# Or activate the virtual environment and run directly
source .venv/bin/activate
drift-fixer

# Fix drift in specific directory
drift-fixer --path /path/to/terraform/project

# Dry run (don't make changes)
drift-fixer --dry-run

# Verbose output
drift-fixer --verbose
```

## Requirements

- Python 3.12+ (managed by UV)
- Terraform CLI
- `tfparse` Python library (installed automatically)
- `tfedit` CLI utility (must be installed separately)

## Testing

Initially tested with the Terraform GitHub provider.

## Development

```bash
# Run in development mode
uv run python -m drift_fixer.main --help

# Run tests (when implemented)
uv run pytest

# Format code
uv run black drift_fixer/
uv run isort drift_fixer/
```