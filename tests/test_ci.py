"""Tests for the CI workflow generator."""

import yaml

from cortex_protocol.ci import generate_github_action


class TestGenerateGitHubAction:
    def test_returns_string(self):
        result = generate_github_action()
        assert isinstance(result, str)

    def test_valid_yaml(self):
        result = generate_github_action()
        data = yaml.safe_load(result)
        assert data is not None

    def test_workflow_has_name(self):
        result = generate_github_action()
        data = yaml.safe_load(result)
        assert "name" in data
        assert "Cortex" in data["name"]

    def test_triggers_on_pr_and_push(self):
        result = generate_github_action()
        # PyYAML 1.1 parses bare `on:` as boolean True
        on_block = yaml.safe_load(result).get(True) or yaml.safe_load(result).get("on")
        assert on_block is not None
        assert "pull_request" in on_block
        assert "push" in on_block

    def test_has_validate_step(self):
        result = generate_github_action()
        assert "validate" in result

    def test_has_lint_step(self):
        result = generate_github_action()
        assert "lint" in result

    def test_has_compile_step(self):
        result = generate_github_action()
        assert "compile" in result

    def test_default_spec_path_in_workflow(self):
        result = generate_github_action()
        assert "agent.yaml" in result

    def test_custom_spec_path_used(self):
        result = generate_github_action(spec_path="agents/my_bot.yaml")
        assert "agents/my_bot.yaml" in result

    def test_fail_on_error_in_lint_step(self):
        result = generate_github_action()
        assert "--fail-on error" in result

    def test_all_targets_in_compile_step(self):
        result = generate_github_action()
        assert "--target all" in result

    def test_has_two_jobs(self):
        result = generate_github_action()
        data = yaml.safe_load(result)
        assert len(data["jobs"]) == 2

    def test_pr_comment_job_exists(self):
        result = generate_github_action()
        data = yaml.safe_load(result)
        assert any("comment" in key.lower() or "lint" in key.lower()
                   for key in data["jobs"])

    def test_python_312_used(self):
        result = generate_github_action()
        assert "3.12" in result

    def test_upload_artifact_step_present(self):
        result = generate_github_action()
        assert "upload-artifact" in result
