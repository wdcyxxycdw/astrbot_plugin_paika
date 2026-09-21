import ast
import importlib.util
import sys
from pathlib import Path

from conftest import install_astrbot_stubs


ROOT = Path(__file__).resolve().parents[1]


def test_entrypoint_uses_astrbot_logger(monkeypatch):
    install_astrbot_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("paika_logging_test", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.logger is sys.modules["astrbot.api"].logger


def test_plugin_does_not_import_standard_logging():
    paths = [ROOT / "main.py", *sorted((ROOT / "paika").rglob("*.py"))]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(name.split(".")[0] == "logging" for name in names), path
