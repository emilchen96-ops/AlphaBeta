import ast
import inspect
from pathlib import Path

from alphadesk_domain.repositories import (
    AuditLogRepository,
    DomainEventRepository,
    FillRepository,
    RiskDecisionRepository,
)


def test_domain_package_has_no_framework_dependencies() -> None:
    domain_root = Path(__file__).resolve().parents[2] / "src" / "alphadesk_domain"
    forbidden = {"fastapi", "sqlalchemy", "alembic", "redis", "starlette"}
    imported: set[str] = set()
    for source_file in domain_root.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden)


def test_append_only_repository_ports_have_no_update_or_delete() -> None:
    for repository in (
        DomainEventRepository,
        AuditLogRepository,
        FillRepository,
        RiskDecisionRepository,
    ):
        methods = {name for name, _ in inspect.getmembers(repository, inspect.isfunction)}
        assert "update" not in methods
        assert "delete" not in methods


def test_sqlalchemy_repositories_do_not_commit() -> None:
    repository_file = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "alphadesk_api"
        / "infrastructure"
        / "repositories.py"
    )
    assert ".commit(" not in repository_file.read_text(encoding="utf-8")
