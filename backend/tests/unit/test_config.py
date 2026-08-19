from app.config import Settings


def test_settings_accept_explicit_cors_origins() -> None:
    settings = Settings(cors_origins=["http://localhost:4173"])

    assert settings.cors_origins == ["http://localhost:4173"]
