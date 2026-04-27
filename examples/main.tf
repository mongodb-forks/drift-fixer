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

import {
  to = github_repository_ruleset.ruleset_15577636
  id = "drift-test:15577636"
}

resource "github_repository_ruleset" "ruleset_15577636" {
  enforcement = "disabled"
  name        = "main"
  repository  = "drift-test"
  target      = "branch"
  conditions {
    ref_name {
      exclude = []
      include = ["~DEFAULT_BRANCH"]
    }
  }
  rules {
    creation                      = false
    deletion                      = true
    non_fast_forward              = true
    required_linear_history       = false
    required_signatures           = false
    update                        = false
    update_allows_fetch_and_merge = false
    pull_request {
      allowed_merge_methods             = ["merge", "squash", "rebase"]
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_approving_review_count   = 1
      required_review_thread_resolution = false
    }
    required_status_checks {
      do_not_enforce_on_create = false
      required_check {
        context        = "test_check"
        integration_id = 0
      }
      strict_required_status_checks_policy = false
    }
  }
  bypass_actors {
    actor_type  = "Integration"
    bypass_mode = "exempt"
    actor_id    = 946600
  }
  bypass_actors {
    actor_id    = 1236702
    actor_type  = "Integration"
    bypass_mode = "always"
  }
}


resource "github_repository" "drift_test" {
  allow_auto_merge            = false
  allow_forking               = true
  allow_merge_commit          = true
  allow_rebase_merge          = true
  allow_squash_merge          = true
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
  merge_commit_message        = "PR_TITLE"
  merge_commit_title          = "MERGE_MESSAGE"
  name                        = "drift-test"
  source_owner                = ""
  source_repo                 = ""
  squash_merge_commit_message = "COMMIT_MESSAGES"
  squash_merge_commit_title   = "COMMIT_OR_PR_TITLE"
  topics                      = []
  visibility                  = "public"
  web_commit_signoff_required = false
}

