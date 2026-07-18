"""
Database Utilities - PostgreSQL + TimescaleDB operations
Consolidated from data_pipeline/db_utils.py into data_service/db_utils.py
"""

import os
import sys
import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
from datetime import datetime as dt
import logging

logger = logging.getLogger(__name__)

# ── Default Connection Parameters ──────────────────────────────────────────
DEFAULT_DB_NAME = "postgres"
DEFAULT_DB_USER = "postgres"
DEFAULT_DB_PASSWORD = "123"
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = "5432"


def get_db_config(config: dict = None) -> dict:
    """Get DB config from dict or env vars with fallbacks"""
    if config:
        return {
            'dbname': config.get('db_name', 'spot_db'),
            'user': config.get('user', DEFAULT_DB_USER),
            'password': config.get('password', DEFAULT_DB_PASSWORD),
            'host': config.get('host', DEFAULT_DB_HOST),
            'port': config.get('port', DEFAULT_DB_PORT),
        }
    return {
        'dbname': os.getenv('DB_NAME', 'spot_db'),
        'user': os.getenv('DB_USER', DEFAULT_DB_USER),
        'password': os.getenv('DB_PASSWORD', DEFAULT_DB_PASSWORD),
        'host': os.getenv('DB_HOST', DEFAULT_DB_HOST),
        'port': os.getenv('DB_PORT', DEFAULT_DB_PORT),
    }


def create_connection(db_name=None, user=None, password=None, host=None, port=None):
    """Create a PostgreSQL connection"""
    conn_params = {
        'dbname': db_name or DEFAULT_DB_NAME,
        'user': user or DEFAULT_DB_USER,
        'password': password or DEFAULT_DB_PASSWORD,
        'host': host or DEFAULT_DB_HOST,
        'port': port or DEFAULT_DB_PORT,
    }
    return psycopg2.connect(**conn_params)


def create_all_db(db_list=None):
    """Create databases if they don't exist"""
    if db_list is None:
        db_list = ["spot_db"]

    try:
        conn = create_connection(db_name=DEFAULT_DB_NAME)
        conn.autocommit = True
        cursor = conn.cursor()

        for db in db_list:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (db,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db))
                )
                logger.info(f"Database '{db}' created successfully")
            else:
                logger.info(f"Database '{db}' already exists")

        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error creating database: {e}")


def crate_table_spot_data(db_name, table_name):
    """Create spot data table with TimescaleDB hypertable"""
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()

        cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            time TIMESTAMP NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume DOUBLE PRECISION
        );
        """
        cursor.execute(create_table_query)

        # Convert to hypertable (ignore if already exists)
        try:
            cursor.execute(f"SELECT create_hypertable('{table_name}', 'time', if_not_exists => TRUE);")
        except Exception:
            pass  # Already a hypertable or other issue

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Table '{table_name}' ready in DB '{db_name}'")
    except Exception as e:
        logger.error(f"Error creating table {table_name}: {e}")


def crate_table_option_data(db_name, table_name):
    """Create option data table with TimescaleDB hypertable"""
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()

        cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            time TIMESTAMP NOT NULL,
            symbol TEXT NOT NULL,
            expiry_date DATE NOT NULL,
            option_type TEXT NOT NULL,
            strike_price DOUBLE PRECISION,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT
        );
        """
        cursor.execute(create_table_query)

        try:
            cursor.execute(f"SELECT create_hypertable('{table_name}', 'time', if_not_exists => TRUE);")
        except Exception:
            pass

        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"Option table '{table_name}' ready")
    except Exception as e:
        logger.error(f"Error creating option table {table_name}: {e}")


def list_databases():
    """List all databases"""
    try:
        conn = create_connection(db_name=DEFAULT_DB_NAME)
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
        databases = cursor.fetchall()
        cursor.close()
        conn.close()
        return [db[0] for db in databases]
    except Exception as e:
        logger.error(f"Error listing databases: {e}")
        return []


def list_tables_in_database(db_name):
    """List all tables in a database"""
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()
        query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        AND table_type = 'BASE TABLE';
        """
        cursor.execute(query)
        tables = cursor.fetchall()
        cursor.close()
        conn.close()
        return tables
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        return []


def get_table_columns(db_name, table_name):
    """Get column names for a table"""
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()
        query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = %s
        ORDER BY ordinal_position;
        """
        cursor.execute(query, (table_name,))
        columns = cursor.fetchall()
        cursor.close()
        conn.close()
        return [col[0] for col in columns]
    except Exception as e:
        logger.error(f"Error getting columns for {table_name}: {e}")
        return []


def print_all_db_tables():
    """Print all databases and their tables"""
    databases = list_databases()
    print("Databases on the server:")
    for db in databases:
        print(f"- {db}")

    for db in databases:
        print(f"\nTables in database '{db}':")
        tables = list_tables_in_database(db)
        for schema, table in tables:
            if schema == "public":
                columns = get_table_columns(db_name=db, table_name=table)
                print(f"  db:{db} Schema: {schema}, Table: {table}   {columns}")


def delete_databases(db_list=None):
    """Delete specified databases"""
    if db_list is None:
        db_list = ["financial_data"]

    try:
        conn = create_connection(db_name=DEFAULT_DB_NAME)
        conn.autocommit = True
        cursor = conn.cursor()

        for db in db_list:
            cursor.execute(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{db}'
                AND pid <> pg_backend_pid();
            """)
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db))
            )
            logger.info(f"Database '{db}' deleted")

        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error deleting database: {e}")


def delete_all_databases():
    """Delete all user databases (keeps postgres, template0, template1)"""
    try:
        conn = create_connection(db_name=DEFAULT_DB_NAME)
        conn.autocommit = True
        cursor = conn.cursor()

        cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
        db_list = [db[0] for db in cursor.fetchall()]

        protected = {"postgres", "template0", "template1"}
        for db in db_list:
            if db not in protected:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db))
                )
                logger.info(f"Database '{db}' deleted")

        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error deleting all databases: {e}")


def insert_dataframe_to_table(df, db_name, table_name, chunk_size=1000):
    """Insert DataFrame into PostgreSQL table in chunks"""
    if df is None or df.empty:
        logger.warning(f"No data to insert into {table_name}")
        return

    conn = None
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()

        # Ensure column names match
        columns = ",".join(df.columns)
        insert_query = f"INSERT INTO {table_name} ({columns}) VALUES %s;"

        data_tuples = [tuple(row) for row in df.to_numpy()]

        for i in range(0, len(data_tuples), chunk_size):
            chunk = data_tuples[i:i + chunk_size]
            execute_values(cursor, insert_query, chunk)
            conn.commit()
            logger.info(f"Inserted {len(chunk)} rows into '{table_name}'")

        logger.info(f"All data inserted into '{table_name}' ({len(df)} total rows)")

    except Exception as e:
        logger.error(f"Error inserting into {table_name}: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cursor.close()
            conn.close()


def get_table_content(db_name, table_name, schema_name="public", start_date=None, end_date=None):
    """Retrieve table content as DataFrame with optional date filtering"""

    if start_date and isinstance(start_date, dt):
        start_date = start_date.strftime('%Y-%m-%d %H:%M:%S')
    if end_date and isinstance(end_date, dt):
        end_date = end_date.strftime('%Y-%m-%d %H:%M:%S')

    conn = None
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()

        query = f"SELECT * FROM {schema_name}.\"{table_name}\""

        where_clauses = []
        if start_date:
            where_clauses.append(f"time >= '{start_date}'")
        if end_date:
            where_clauses.append(f"time <= '{end_date}'")

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY time ASC"

        cursor.execute(query)
        rows = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]

        df = pd.DataFrame(rows, columns=column_names)
        return df

    except Exception as e:
        logger.error(f"Error retrieving from {schema_name}.{table_name}: {e}")
        return None
    finally:
        if conn:
            cursor.close()
            conn.close()


def delete_old_data(db_name, table_name, num_days, schema_name="public"):
    """Delete data older than num_days from current date"""
    conn = None
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()

        query = f"""
        DELETE FROM {schema_name}.\"{table_name}\"
        WHERE time < CURRENT_DATE - INTERVAL '{num_days} days'
        """

        cursor.execute(query)
        rows_deleted = cursor.rowcount
        conn.commit()

        logger.info(f"Deleted {rows_deleted} rows from '{table_name}' older than {num_days} days")
        return rows_deleted

    except Exception as e:
        logger.error(f"Error deleting old data from {table_name}: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            cursor.close()
            conn.close()


def get_latest_data_date(db_name, table_name):
    """Get the latest timestamp from a table"""
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = %s
            );
        """, (table_name,))

        if not cursor.fetchone()[0]:
            cursor.close()
            conn.close()
            return None

        cursor.execute(f'SELECT MAX(time) FROM "{table_name}"')
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        return result[0].date() if result[0] else None

    except Exception as e:
        logger.error(f"Error getting latest date for {table_name}: {e}")
        return None


def table_exists(db_name, table_name):
    """Check if a table exists"""
    try:
        conn = create_connection(db_name=db_name)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = %s
            );
        """, (table_name,))
        exists = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return exists
    except Exception as e:
        logger.error(f"Error checking table existence: {e}")
        return False


if __name__ == "__main__":
    print_all_db_tables()