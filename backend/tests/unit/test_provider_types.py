"""Tests for backend.core.provider_types — Provider models and enums."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from backend.core.provider_types import (
    AuthenticationError,
    CreatePlaybook,
    CustomSecret,
    ProviderToken,
    ProviderType,
    SuggestedTask,
    TaskType,
)


# ── ProviderType ─────────────────────────────────────────────────────


class TestProviderType:
    def test_enterprise_sso(self):
        assert ProviderType.ENTERPRISE_SSO.value == "enterprise_sso"


# ── TaskType ─────────────────────────────────────────────────────────


class TestTaskType:
    def test_values(self):
        expected = {
            "MERGE_CONFLICTS",
            "FAILING_CHECKS",
            "UNRESOLVED_COMMENTS",
            "OPEN_ISSUE",
            "OPEN_PR",
            "CREATE_PLAYBOOK",
        }
        actual = {t.value for t in TaskType}
        assert actual == expected


# ── ProviderToken ────────────────────────────────────────────────────


class TestProviderToken:
    def test_defaults(self):
        pt = ProviderToken()
        assert pt.token is None
        assert pt.user_id is None
        assert pt.host is None

    def test_from_value_with_token_instance(self):
        pt = ProviderToken(token=SecretStr("abc"))
        result = ProviderToken.from_value(pt)
        assert result is pt

    def test_from_value_with_dict(self):
        pt = ProviderToken.from_value({"token": "secret", "user_id": "u1", "host": "gh.co"})
        assert pt.token.get_secret_value() == "secret"
        assert pt.user_id == "u1"
        assert pt.host == "gh.co"

    def test_from_value_dict_no_token(self):
        pt = ProviderToken.from_value({"user_id": "u1"})
        assert pt.token.get_secret_value() == ""

    def test_from_value_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported"):
            ProviderToken.from_value(42)

    def test_frozen_model(self):
        pt = ProviderToken(token=SecretStr("x"))
        with pytest.raises(Exception):
            pt.token = SecretStr("y")

    def test_empty_user_id_rejected(self):
        with pytest.raises(Exception):
            ProviderToken(user_id="")

    def test_empty_host_rejected(self):
        with pytest.raises(Exception):
            ProviderToken(host="")


# ── CustomSecret ─────────────────────────────────────────────────────


class TestCustomSecret:
    def test_defaults(self):
        cs = CustomSecret()
        assert cs.secret.get_secret_value() == ""
        assert cs.description == ""

    def test_from_value_with_instance(self):
        cs = CustomSecret(secret=SecretStr("mykey"), description="api key")
        result = CustomSecret.from_value(cs)
        assert result is cs

    def test_from_value_with_dict(self):
        cs = CustomSecret.from_value({"secret": "val", "description": "desc"})
        assert cs.secret.get_secret_value() == "val"
        assert cs.description == "desc"

    def test_from_value_dict_defaults(self):
        cs = CustomSecret.from_value({})
        assert cs.secret.get_secret_value() == ""
        assert cs.description == ""

    def test_from_value_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported"):
            CustomSecret.from_value(123)


# ── SuggestedTask ────────────────────────────────────────────────────


class TestSuggestedTask:
    def test_valid_task(self):
        st = SuggestedTask(
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            task_type=TaskType.OPEN_ISSUE,
            repo="owner/repo",
            issue_number=42,
            title="Fix bug",
        )
        assert st.repo == "owner/repo"
        assert st.issue_number == 42

    def test_get_prompt_for_task(self):
        st = SuggestedTask(
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            task_type=TaskType.OPEN_ISSUE,
            repo="org/project",
            issue_number=10,
            title="Add tests",
        )
        prompt = st.get_prompt_for_task()
        assert "OPEN_ISSUE" in prompt
        assert "Add tests" in prompt
        assert "#10" in prompt
        assert "org/project" in prompt

    def test_empty_repo_rejected(self):
        with pytest.raises(Exception):
            SuggestedTask(
                vcs_provider=ProviderType.ENTERPRISE_SSO,
                task_type=TaskType.OPEN_ISSUE,
                repo="",
                issue_number=1,
                title="x",
            )

    def test_issue_number_ge_1(self):
        with pytest.raises(Exception):
            SuggestedTask(
                vcs_provider=ProviderType.ENTERPRISE_SSO,
                task_type=TaskType.OPEN_ISSUE,
                repo="a/b",
                issue_number=0,
                title="x",
            )


# ── CreatePlaybook ───────────────────────────────────────────────────


class TestCreatePlaybook:
    def test_valid(self):
        cp = CreatePlaybook(repo="owner/repo")
        assert cp.repo == "owner/repo"
        assert cp.vcs_provider is None
        assert cp.title is None

    def test_with_provider_and_title(self):
        cp = CreatePlaybook(
            repo="org/proj",
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            title="My Playbook",
        )
        assert cp.vcs_provider == ProviderType.ENTERPRISE_SSO
        assert cp.title == "My Playbook"

    def test_empty_repo_rejected(self):
        with pytest.raises(Exception):
            CreatePlaybook(repo="")

    def test_empty_title_rejected(self):
        with pytest.raises(Exception):
            CreatePlaybook(repo="a/b", title="")


# ── AuthenticationError ──────────────────────────────────────────────


class TestAuthenticationError:
    def test_is_value_error(self):
        err = AuthenticationError("bad token")
        assert isinstance(err, ValueError)
        assert str(err) == "bad token"
