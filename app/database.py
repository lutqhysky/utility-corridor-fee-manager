import sqlite3
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR / 'corridor_fee_manager.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def ensure_sqlite_schema():
    expected_columns = {
        'pipeline_entries': {
            'entry_fee_tax_rate': 'FLOAT DEFAULT 0',
            'maintenance_fee_tax_rate': 'FLOAT DEFAULT 0',
            'entry_fee_discount': 'FLOAT DEFAULT 1',
            'maintenance_fee_discount': 'FLOAT DEFAULT 1',
        },
    }

    database_path = DATA_DIR / 'corridor_fee_manager.db'
    with sqlite3.connect(database_path) as connection:
        for table_name, columns in expected_columns.items():
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
