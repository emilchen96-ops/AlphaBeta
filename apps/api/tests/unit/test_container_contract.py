from pathlib import Path
from tempfile import NamedTemporaryFile


def test_api_image_contains_test_contract_and_writable_app_directory() -> None:
    container_app = Path("/app")

    if container_app.is_dir():
        assert (container_app / "pyproject.toml").is_file()
        assert (container_app / "tests/integration/test_dependencies.py").is_file()
        with NamedTemporaryFile(dir=container_app):
            pass
        return

    api_root = Path(__file__).resolve().parents[2]
    dockerfile = (api_root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY pyproject.toml ./pyproject.toml" in dockerfile
    assert "COPY tests ./tests" in dockerfile
    assert "RUN chown -R alphadesk:alphadesk /app" in dockerfile
