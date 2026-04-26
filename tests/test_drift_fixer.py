"""Tests for drift_fixer package."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from drift_fixer.main import DriftFixer
from drift_fixer.plan_parser import PlanParser, ResourceChange
from drift_fixer.terraform_runner import TerraformRunner


class TestPlanParser:
    """Test the terraform plan parser."""
    
    def test_parse_simple_resource_change(self):
        """Test parsing a simple resource change."""
        parser = PlanParser()
        
        plan_output = [
            "Terraform will perform the following actions:",
            "",
            "  # github_repository.example will be updated in-place",
            "  ~ resource \"github_repository\" \"example\" {",
            "      ~ description = \"Old description\" -> \"New description\"",
            "        id          = \"example\"",
            "        # (10 unchanged attributes hidden)",
            "    }",
            "",
            "Plan: 0 to add, 1 to change, 0 to destroy."
        ]
        
        changes = parser.parse_changes(plan_output)
        
        assert len(changes) == 1
        assert changes[0].resource_type == "github_repository"
        assert changes[0].resource_name == "example"
        assert changes[0].change_type == "update"
        assert changes[0].address == "github_repository.example"
        
    def test_parse_multiple_resources(self):
        """Test parsing multiple resource changes."""
        parser = PlanParser()
        
        plan_output = [
            "  + resource \"github_repository\" \"new_repo\" {",
            "  ~ resource \"github_repository\" \"existing_repo\" {",
            "  - resource \"github_repository\" \"old_repo\" {",
        ]
        
        changes = parser.parse_changes(plan_output)
        
        assert len(changes) == 3
        
        # Check create
        create_change = next(c for c in changes if c.change_type == "create")
        assert create_change.resource_name == "new_repo"
        
        # Check update  
        update_change = next(c for c in changes if c.change_type == "update")
        assert update_change.resource_name == "existing_repo"
        
        # Check delete
        delete_change = next(c for c in changes if c.change_type == "delete")
        assert delete_change.resource_name == "old_repo"
        
        
class TestTerraformRunner:
    """Test the terraform runner."""
    
    @patch('subprocess.run')
    def test_run_plan_no_changes(self, mock_run):
        """Test terraform plan with no changes."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        
        runner = TerraformRunner(Path("/fake/path"))
        result = runner.run_plan()
        
        assert result is None
        
    @patch('subprocess.run')  
    def test_run_plan_with_changes(self, mock_run):
        """Test terraform plan with changes."""
        plan_output = "~ resource \"github_repository\" \"example\" {"
        mock_run.return_value = Mock(returncode=2, stdout=plan_output, stderr="")
        
        runner = TerraformRunner(Path("/fake/path"))
        result = runner.run_plan()
        
        assert result is not None
        assert isinstance(result, list)
        assert len(result) > 0
        
    @patch('subprocess.run')
    def test_run_plan_error(self, mock_run):
        """Test terraform plan with error."""
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error message")
        
        runner = TerraformRunner(Path("/fake/path"))
        
        with pytest.raises(RuntimeError, match="Terraform plan failed"):
            runner.run_plan()


class TestDriftFixer:
    """Test the main drift fixer."""
    
    def test_init(self):
        """Test drift fixer initialization."""
        fixer = DriftFixer(Path("/fake/path"))
        
        assert fixer.project_path == Path("/fake/path")
        assert fixer.dry_run is False
        assert fixer.auto_commit is True
        assert fixer.verbose is False


if __name__ == "__main__":
    pytest.main([__file__])