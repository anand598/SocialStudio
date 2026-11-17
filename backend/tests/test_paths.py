"""The project must work from a folder whose path contains spaces (e.g. "Social Studio")."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_migrations_run_from_a_path_with_spaces(tmp_path):
    root = tmp_path / "Social Studio" / "backend"
    root.mkdir(parents=True)
    shutil.copy(BACKEND / "alembic.ini", root / "alembic.ini")
    (root / "alembic").symlink_to(BACKEND / "alembic")
    (root / "app").symlink_to(BACKEND / "app")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'jobs.db'}"}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-800:]
