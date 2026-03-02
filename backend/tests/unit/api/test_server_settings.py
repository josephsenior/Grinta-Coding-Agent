"""Tests for backend.api.settings Pydantic models."""


class TestPOSTProviderModel:
    def test_defaults(self):
        from backend.api.settings import POSTProviderModel

        model = POSTProviderModel()
        assert model.mcp_config is None
        assert model.provider_tokens == {}

    def test_with_tokens(self):
        from backend.api.settings import POSTProviderModel

        model = POSTProviderModel(provider_tokens={"openai": {"token": "sk-123"}})
        assert "openai" in model.provider_tokens


class TestPOSTCustomSecrets:
    def test_defaults(self):
        from backend.api.settings import POSTCustomSecrets

        model = POSTCustomSecrets()
        assert model.custom_secrets == {}


class TestCustomSecretModels:
    def test_without_value(self):
        from backend.api.settings import CustomSecretWithoutValueModel

        model = CustomSecretWithoutValueModel(name="MY_SECRET")
        assert model.name == "MY_SECRET"
        assert model.description is None

    def test_with_description(self):
        from backend.api.settings import CustomSecretWithoutValueModel

        model = CustomSecretWithoutValueModel(name="API_KEY", description="My API key")
        assert model.description == "My API key"

    def test_with_value(self):
        from backend.api.settings import CustomSecretModel

        model = CustomSecretModel(
            name="TOKEN", value="secret-value", description="A token"
        )
        assert model.name == "TOKEN"
        assert model.value.get_secret_value() == "secret-value"

    def test_inheritance(self):
        from backend.api.settings import (
            CustomSecretModel,
            CustomSecretWithoutValueModel,
        )

        assert issubclass(CustomSecretModel, CustomSecretWithoutValueModel)


class TestGETCustomSecrets:
    def test_defaults(self):
        from backend.api.settings import GETCustomSecrets

        model = GETCustomSecrets()
        assert model.custom_secrets is None

    def test_with_secrets(self):
        from backend.api.settings import (
            CustomSecretWithoutValueModel,
            GETCustomSecrets,
        )

        model = GETCustomSecrets(
            custom_secrets=[
                CustomSecretWithoutValueModel(name="KEY1"),
                CustomSecretWithoutValueModel(name="KEY2", description="desc"),
            ]
        )
        assert model.custom_secrets is not None
        assert len(model.custom_secrets) == 2
        assert model.custom_secrets[0].name == "KEY1"
