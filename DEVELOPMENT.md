# Development Guide

This guide helps you set up and contribute to the drift-fixer project.

## Setup for Development

1. **Install UV** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone and setup the project**:
   ```bash
   git clone <repository-url>
   cd drift-fixer
   uv sync --dev  # Install all dependencies including dev dependencies
   ```

3. **Activate the virtual environment**:
   ```bash
   source .venv/bin/activate
   ```

## Development Workflow

### Running the Tool

```bash
# Run directly with UV
uv run drift-fixer --help

# Or with the virtual environment activated
drift-fixer --help

# Run in development mode
uv run python -m drift_fixer.main --verbose --dry-run
```

### Code Quality

```bash
# Format code
uv run black drift_fixer/ tests/
uv run isort drift_fixer/ tests/

# Type checking
uv run mypy drift_fixer/

# Linting
uv run flake8 drift_fixer/

# Run all quality checks
uv run black --check drift_fixer/ tests/
uv run isort --check-only drift_fixer/ tests/
uv run mypy drift_fixer/
uv run flake8 drift_fixer/
```

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=drift_fixer --cov-report=html

# Run specific test file
uv run pytest tests/test_drift_fixer.py

# Run specific test
uv run pytest tests/test_drift_fixer.py::TestPlanParser::test_parse_simple_resource_change
```

### Project Structure

```
drift-fixer/
├── drift_fixer/           # Main package
│   ├── __init__.py        # Package initialization
│   ├── main.py           # CLI interface and main orchestration
│   ├── terraform_runner.py # Terraform CLI operations
│   ├── plan_parser.py    # Parse terraform plan output
│   ├── file_analyzer.py  # Analyze .tf files with tfparse
│   ├── config_editor.py  # Edit configs with tfedit
│   └── git_manager.py    # Git operations
├── tests/                # Test suite
│   └── test_drift_fixer.py # Main test file
├── examples/             # Example configurations
│   ├── main.tf          # Example Terraform config
│   ├── example_usage.py # Programmatic usage example
│   └── drift-fixer.toml # Configuration file example
├── main.py              # Entry point script
├── pyproject.toml       # Project configuration
├── README.md            # Project documentation
└── .gitignore           # Git ignore rules
```

## Key Components

### 1. TerraformRunner (`terraform_runner.py`)
- Handles running `terraform plan` and `terraform init`
- Parses exit codes to determine if changes exist
- Manages working directory changes

### 2. PlanParser (`plan_parser.py`)
- Parses `terraform plan` output to extract resource changes
- Identifies resource types, names, and change types (create/update/delete)
- Returns structured `ResourceChange` objects

### 3. FileAnalyzer (`file_analyzer.py`)
- Uses `tfparse` library to analyze .tf files
- Maps changed resources to their source files
- Falls back to text search if tfparse fails

### 4. ConfigEditor (`config_editor.py`)
- Uses `tfedit` CLI to modify Terraform configurations
- Syncs configuration with current infrastructure state
- Handles different types of resource changes

### 5. GitManager (`git_manager.py`)
- Handles Git operations for committing fixes
- Checks for Git repository and uncommitted changes
- Commits changes with descriptive messages

## Prerequisites

The tool requires these external dependencies:

1. **Terraform CLI**: For running `terraform plan` and `terraform show`
2. **tfedit CLI**: For editing Terraform configuration files
3. **Git**: For version control operations (optional)

Install them before using the tool:

```bash
# Terraform (example for Linux)
wget https://releases.hashicorp.com/terraform/1.5.7/terraform_1.5.7_linux_amd64.zip
unzip terraform_1.5.7_linux_amd64.zip
sudo mv terraform /usr/local/bin/

# tfedit (check https://github.com/minamijoyo/tfedit for installation)
# Installation method depends on your system

# Git (usually pre-installed)
sudo apt-get install git  # Ubuntu/Debian
brew install git          # macOS
```

## Testing Strategy

### Unit Tests
- Test individual components in isolation
- Mock external dependencies (subprocess calls, file operations)
- Focus on parsing logic and error handling

### Integration Tests (TODO)
- Test with real Terraform configurations
- Test with actual GitHub provider
- Validate end-to-end workflow

### Example Test Data
Use the files in `examples/` directory for testing:
- `main.tf`: Example Terraform configuration
- Test against this config to verify parsing works correctly

## Contributing

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature`
3. **Make changes and add tests**
4. **Run quality checks**: `uv run black . && uv run mypy . && uv run pytest`
5. **Commit changes**: `git commit -am 'Add your feature'`
6. **Push to branch**: `git push origin feature/your-feature`
7. **Create Pull Request**

## Known Limitations

1. **tfedit dependency**: Requires external CLI tool
2. **Provider-specific**: Initially designed for GitHub provider
3. **State access**: Requires read access to Terraform state
4. **Limited attribute handling**: Not all resource attributes are safe to auto-fix

## Future Enhancements

- [ ] Support for more Terraform providers
- [ ] Configuration file support for customizing behavior
- [ ] Better error handling and recovery
- [ ] Integration with CI/CD pipelines
- [ ] Web UI for reviewing changes before applying
- [ ] Support for Terraform Cloud/Enterprise