import sqlite3
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)


def resolve_database_path() -> Path:
    explicit_path = os.getenv('APP_DATABASE_PATH', '').strip()
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()

    default_path = DATA_DIR / 'corridor_fee_manager.db'
    legacy_paths = [
        DATA_DIR / 'corridor_fee.db',
        DATA_DIR / 'utility_corridor_fee_manager.db',
    ]

    if default_path.exists():
        return default_path

    for legacy_path in legacy_paths:
        if legacy_path.exists():
            return legacy_path

    return default_path


DATABASE_PATH = resolve_database_path()
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_expected_sqlite_columns():
    return {
        'pipeline_entries': {
            'entry_fee_tax_rate': 'FLOAT DEFAULT 0',
            'maintenance_fee_tax_rate': 'FLOAT DEFAULT 0',
            'entry_fee_discount': 'FLOAT DEFAULT 1',
            'maintenance_fee_discount': 'FLOAT DEFAULT 1',
            'charge_cycle': "VARCHAR(20) DEFAULT '年度'",
        },
        'contracts': {
            'pipeline_entry_id': 'INTEGER',
        },
        'fee_records': {
            'project_name': 'VARCHAR(200)',
            'last_reminder_sent_at': 'DATETIME',
            'last_reminder_for_date': 'DATE',
            'last_reminder_channel': 'VARCHAR(50)',
            'created_at': 'DATETIME',
            'updated_at': 'DATETIME',
        },
    }


def ensure_sqlite_schema():
    import logging
    logger = logging.getLogger(__name__)
    with sqlite3.connect(DATABASE_PATH) as connection:
        # 收费标准唯一索引（费用类型+管线类型+规格）：先自动去重（每组保留 id 最大的一条）再建索引
        try:
            dup_rows = connection.execute(
                """SELECT fee_type, pipeline_type, specification, MAX(id) AS keep_id, COUNT(*) AS c
                    FROM fee_standards GROUP BY fee_type, pipeline_type, specification HAVING c > 1"""
            ).fetchall()
            for fee_type, pipeline_type, spec, keep_id, cnt in dup_rows:
                connection.execute(
                    'DELETE FROM fee_standards WHERE fee_type IS ? AND pipeline_type IS ? '
                    'AND specification IS ? AND id != ?',
                    (fee_type, pipeline_type, spec, keep_id),
                )
                logger.warning(
                    'fee_standards 去重：费用类型=%s 管线=%s 规格=%s 删除 %d 条重复，保留 id=%s',
                    fee_type, pipeline_type, spec, cnt - 1, keep_id)
            connection.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_fee_standard_type_spec '
                'ON fee_standards (fee_type, pipeline_type, specification)'
            )
        except Exception:
            logger.exception('创建 fee_standards 唯一索引失败')
        for table_name, columns in get_expected_sqlite_columns().items():
            existing_columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info({table_name})')
            }
            for column_name, definition in columns.items():
                if column_name in existing_columns:
                    continue
                connection.execute(
                    f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}'
                )
        connection.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
