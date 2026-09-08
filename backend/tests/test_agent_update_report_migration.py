import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql


def test_update_report_migration_clears_legacy_false_and_restores_downgrade_default(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "updates.db"
    environment = os.environ | {"DATABASE_URL": f"sqlite:///{database.as_posix()}"}

    def alembic(*arguments):
        subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments], cwd=backend, env=environment, check=True)

    alembic("upgrade", "e8b4c6d912fa")
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO agents (id, name, platform, version, protocol_version, auto_update, created_at, updated_at) VALUES ('legacy', 'Legacy', 'linux', '1.0.0', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.commit()
    alembic("upgrade", "d4a7f2b9c801")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT auto_update FROM agents WHERE id='legacy'").fetchone()[0] is None
    alembic("downgrade", "e8b4c6d912fa")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT auto_update FROM agents WHERE id='legacy'").fetchone()[0] == 0


def test_update_report_migration_uses_postgresql_boolean_predicate():
    migration = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "d4a7f2b9c801_add_agent_update_reports.py"
    spec = importlib.util.spec_from_file_location("agent_update_migration", migration)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    sql = str(module._clear_legacy_auto_update_statement().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "auto_update IS false" in sql and "= 0" not in sql


def test_update_report_downgrade_uses_postgresql_boolean_assignment():
    migration = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "d4a7f2b9c801_add_agent_update_reports.py"
    spec = importlib.util.spec_from_file_location("agent_update_migration", migration)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    sql = str(module._restore_legacy_auto_update_statement().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "auto_update=false" in sql.replace(" ", "") and "=0" not in sql.replace(" ", "")
