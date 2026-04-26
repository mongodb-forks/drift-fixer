# Example Terraform configuration for testing drift detection
# This example uses the GitHub provider

terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 5.0"
    }
  }
}

provider "github" {
  # Configuration options
}

# Example repository that might experience drift
resource "github_repository" "example" {
  name        = "drift-test-repo"
  description = "A test repository for drift detection"
  
  visibility = "private"
  
  # These attributes commonly experience drift
  homepage_url = "https://example.com"
  topics       = ["terraform", "drift", "test"]
  
  has_issues   = true
  has_projects = false
  has_wiki     = true
  
  allow_merge_commit     = true
  allow_squash_merge     = true
  allow_rebase_merge     = false
  
  delete_branch_on_merge = true
  
  archived = false
}

# Another repository for testing multiple resources
resource "github_repository" "another_example" {
  name        = "another-drift-test"
  description = "Another test repository"
  
  visibility = "public"
  
  topics = ["example", "public"]
  
  has_issues   = false
  has_projects = true
  has_wiki     = false
  
  allow_merge_commit = false
  allow_squash_merge = true
  allow_rebase_merge = true
}