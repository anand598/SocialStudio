"""The project must work from a folder whose path contains spaces (e.g. "Social Studio")."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_migrations_run_from_a_path_with_spaces(tmp_path):
    project = tmp_path / "Social Studio"
    root = project / "backend"
    root.mkdir(parents=True)
    shutil.copy(BACKEND / "alembic.ini", root / "alembic.ini")
    # Copy rather than symlink: symlinks need extra privileges on Windows.
    skip = shutil.ignore_patterns("__pycache__")
    shutil.copytree(BACKEND / "alembic", root / "alembic", ignore=skip)
    shutil.copytree(BACKEND / "app", root / "app", ignore=skip)
    # The database path contains the space too, like scripts/dev-local.sh uses.
    db_dir = project / "storage"
    db_dir.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    # Without PYTHONPATH, alembic.ini's prepend_sys_path is the only way to import `app`.
    env["DATABASE_URL"] = f"sqlite:///{db_dir / 'jobs.db'}"
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-800:]
    assert (db_dir / "jobs.db").exists()
