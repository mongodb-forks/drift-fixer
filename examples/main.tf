# Test configuration targeting Trevor159/drift-test
# Auth: set GITHUB_TOKEN env var to your PAT before running tofu commands

terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "github" {
  # The GitHub provider automatically reads the GITHUB_TOKEN env var.
  # No need to hardcode a token here.
  owner = "Trevor159"
}

import {
  to = github_repository.drift_test
  id = "drift-test"
}




resource "github_repository" "drift_test" {
  allow_auto_merge            = false
  allow_forking               = true
  allow_merge_commit          = false
  allow_rebase_merge          = false
  allow_squash_merge          = false
  allow_update_branch         = false
  archive_on_destroy          = null
  archived                    = false
  auto_init                   = false
  delete_branch_on_merge      = false
  description                 = "test2"
  etag                        = "W/\"7342f62a1deec60046e38a9ac6e82af3616833c0c30008091113806429970a75\""
  fork                        = "false"
  gitignore_template          = null
  has_discussions             = false
  has_issues                  = true
  has_projects                = true
  has_wiki                    = false
  homepage_url                = ""
  is_template                 = false
  license_template            = null
  merge_commit_message        = ""
  merge_commit_title          = ""
  name                        = "drift-test"
  source_owner                = ""
  source_repo                 = ""
  squash_merge_commit_message = ""
  squash_merge_commit_title   = ""
  topics                      = []
  visibility                  = "public"
  web_commit_signoff_required = false
}

