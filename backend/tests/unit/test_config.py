from app.config import Settings


def test_settings_accept_explicit_cors_origins() -> None:
    settings = Settings(cors_origins=["http://localhost:4173"])

    assert settings.cors_origins == ["http://localhost:4173"]


def test_model_api_key_is_secret_and_model_is_configurable() -> None:
    settings = Settings(
        quote_extraction_model="test-extraction-model",
        openai_api_key="super-secret-test-key",
    )

    assert settings.quote_extraction_model == "test-extraction-model"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "super-secret-test-key"
    assert "super-secret-test-key" not in repr(settings)
