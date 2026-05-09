import psycopg2
from psycopg2 import sql
import pandas as pd
import os
from psycopg2.extras import execute_values
from datetime import datetime as dt

# Connection parameters for the default PostgreSQL database
DEFAULT_DB_NAME = "postgres"  # Default database that always exists
DEFAULT_DB_USER = "postgres"
DEFAULT_DB_PASSWORD = "123"
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = "5432"

def create_all_db(db_list=["spot_db"]):
    # Connect to the default PostgreSQL database
    try:
        conn = psycopg2.connect(
            dbname=DEFAULT_DB_NAME,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        conn.autocommit = True  # Enable autocommit for database creation
        cursor = conn.cursor()

        for i in range(len(db_list)):
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_list[i])))
            print(f"Database '{db_list[i]}' created successfully!")

        # Close the connection to the default database
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error creating database: {e}")



def crate_table_spot_data(db_name,table_name):
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()

        # Enable TimescaleDB extension
        cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        print("TimescaleDB extension enabled!")

        # Create a table for stock prices
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
        #print(f"Table '{table_name}' created successfully!")

        # Convert the table into a hypertable
        create_hypertable_query = f"""
        SELECT create_hypertable('{table_name}', 'time');
        """
        cursor.execute(create_hypertable_query)
        #print(f"Table '{table_name}' converted to a hypertable!")

        # Commit changes and close the connection
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error setting up the new database: {e}")





def crate_table_option_data(db_name,table_name):
    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()

        # Enable TimescaleDB extension
        cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        print("TimescaleDB extension enabled!")




        create_table_query = f"""CREATE TABLE {table_name} (
            time TIMESTAMP NOT NULL,          -- Timestamp of the data point
            symbol TEXT NOT NULL,             -- Underlying asset symbol (e.g., AAPL)
            expiry_date DATE NOT NULL,        -- Expiry date of the option
            option_type TEXT NOT NULL,        -- 'call' or 'put'
            strike_price DOUBLE PRECISION,    -- Strike price of the option
            open DOUBLE PRECISION,            -- Opening price
            high DOUBLE PRECISION,            -- High price
            low DOUBLE PRECISION,             -- Low price
            close DOUBLE PRECISION,           -- Closing price
            volume BIGINT                    -- Trading volume
        );
        """


        cursor.execute(create_table_query)
        print(f"Table '{table_name}' created successfully!")

        # Convert the table into a hypertable
        create_hypertable_query = f"""
        SELECT create_hypertable('{table_name}', 'time');
        """
        cursor.execute(create_hypertable_query)
        #print(f"Table '{table_name}' converted to a hypertable!")

        # Commit changes and close the connection
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error setting up the new database: {e}")








# Function to list all databases
def list_databases():
    try:
        # Connect to the default PostgreSQL database
        conn = psycopg2.connect(
            dbname=DEFAULT_DB_NAME,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        conn.autocommit = True  # Enable autocommit for database operations
        cursor = conn.cursor()

        # Query to list all databases
        cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
        databases = cursor.fetchall()

        # Close the connection
        cursor.close()
        conn.close()

        # Return the list of databases
        return [db[0] for db in databases]
    except Exception as e:
        print(f"Error listing databases: {e}")
        return []




# Function to list all tables in a database
def list_tables_in_database(db_name):
    try:
        # Connect to the specified database
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()

        # Query to list all tables
        query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        AND table_type = 'BASE TABLE';
        """
        cursor.execute(query)
        tables = cursor.fetchall()

        # Close the connection
        cursor.close()
        conn.close()

        # Return the list of tables
        return tables
    except Exception as e:
        print(f"Error listing tables in database '{db_name}': {e}")
        return []

def get_table_columns(db_name, table_name):
    try:
        # Connect to the specified database
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()

        # Query to get column names
        query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'  -- Replace with the schema name if different
        AND table_name = %s
        ORDER BY ordinal_position;
        """
        cursor.execute(query, (table_name,))
        columns = cursor.fetchall()

        # Close the connection
        cursor.close()
        conn.close()

        # Extract column names from the result
        column_names = [col[0] for col in columns]
        return column_names
    except Exception as e:
        print(f"Error retrieving column names for table '{table_name}': {e}")
        return []




def print_all_db_tables():
    # List all databases
    databases = list_databases()
    print("Databases on the server:")
    for db in databases:
        print(f"- {db}")

    # List all tables in each database
    for db in databases:
        print(f"\nTables in database '{db}':")
        tables = list_tables_in_database(db)
        for schema, table in tables:
            if(schema=="public"):
                columns=get_table_columns(db_name=db, table_name=table)
                print(f" db:{db}  Schema: {schema}, Table: {table}   {columns}")





def delete_databases(db_list=["financial_data"]):
    try:
        conn = psycopg2.connect(
            dbname=DEFAULT_DB_NAME,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        conn.autocommit = True  # Enable autocommit for database deletion
        cursor = conn.cursor()



        # Drop the database
        for i in range(len(db_list)):
            db_name=db_list[i]
            cursor.execute(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{db_name}'
                  AND pid <> pg_backend_pid();
            """)
            print(f"Terminated all active connections to database '{db_name}'.")


            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_list[i])))
            print(f"Database {db_list[i]} deleted successfully!")

        # Close the connection
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error deleting database: {e}")


def delete_all_databases():
    try:
        conn = psycopg2.connect(
            dbname=DEFAULT_DB_NAME,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        conn.autocommit = True  # Enable autocommit for database deletion
        cursor = conn.cursor()
        db_list = list_databases()
        print(f"Databse list: {db_list}")
        db_list.remove("postgres")

        # Drop the database
        for i in range(len(db_list)):
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_list[i])))
            print(f"Database {db_list[i]} deleted successfully!")

        # Close the connection
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error deleting database: {e}")





def insert_dataframe_to_table(df, db_name, table_name, chunk_size=1000):
    """
    Inserts data from a Pandas DataFrame into a PostgreSQL table in chunks.

    Parameters:
        df (pd.DataFrame): The DataFrame containing the data to insert.
        db_name (str): The name of the database.
        table_name (str): The name of the table (including schema, e.g., 'public.ultracemco5m').
        chunk_size (int): Number of rows to insert at a time.
    """

    # Connect to the database
    try:
        # Connect to the specified database
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()


        # Prepare the data for insertion
        data_tuples = [tuple(row) for row in df.to_numpy()]

        # Generate the column names for the INSERT query
        columns = ",".join(df.columns)

        # Generate the INSERT query
        insert_query = f"""
        INSERT INTO {table_name} ({columns})
        VALUES %s;
        """

        # Insert data in chunks
        for i in range(0, len(data_tuples), chunk_size):
            chunk = data_tuples[i:i + chunk_size]
            execute_values(cursor, insert_query, chunk)
            conn.commit()
            print(f"Inserted {len(chunk)} rows into table '{table_name}'.")

        print(f"All data inserted successfully into table '{table_name}'!")

    except Exception as e:
        print(f"Error inserting data into table '{table_name}': {e}")
        conn.rollback()  # Rollback in case of error


def get_table_content(db_name, table_name, schema_name="public",start_date=None,end_date=None):
    """
    Retrieves and displays the content of a PostgreSQL table.

    Parameters:
        db_name (str): The name of the database.
        table_name (str): The name of the table.
        schema_name (str): The name of the schema (default is 'public').
    """
    # Connect to the database

    if start_date and isinstance(start_date, dt):
        start_date = start_date.strftime('%Y-%m-%d %H:%M:%S')
    if end_date and isinstance(end_date, dt):
        end_date = end_date.strftime('%Y-%m-%d %H:%M:%S')



    try:
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()

        # Query to retrieve table content
        query = f"""
        SELECT *
        FROM {schema_name}.{table_name}
        """


        where_clauses = []
        if start_date:
            where_clauses.append(f"time >= '{start_date}'")
        if end_date:
            where_clauses.append(f"time <= '{end_date}'")

        # Only add WHERE clause if there are conditions
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)



        cursor.execute(query)
        query += " ORDER BY time ASC"

        # Fetch all rows
        rows = cursor.fetchall()

        # Get column names
        column_names = [desc[0] for desc in cursor.description]

        # Convert to a Pandas DataFrame for better display
        df = pd.DataFrame(rows, columns=column_names)

        # Display the table content
        #print(f"Content of table '{schema_name}.{table_name}':")
        #print(df)
        return(df)

    except Exception as e:
        print(f"Error retrieving content from table '{schema_name}.{table_name}': {e}")

    finally:
        # Close the connection
        if conn:
            cursor.close()
            conn.close()

def delete_old_data(db_name, table_name, num_days, schema_name="public"):
    """
    Deletes data from the specified table that is older than num_days from current date.
    
    Parameters:
        db_name (str): The name of the database.
        table_name (str): The name of the table.
        num_days (int): Number of days to keep (data older than this will be deleted).
        schema_name (str): The name of the schema (default is 'public').
    
    Returns:
        int: Number of rows deleted, or None if error.
    """
    conn = None
    cursor = None

    try:
        # Connect to the database
        conn = psycopg2.connect(
            dbname=db_name,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT
        )
        cursor = conn.cursor()

        # Calculate the cutoff date (current date minus num_days)
        cutoff_date = f"CURRENT_DATE - INTERVAL '{num_days} days'"

        # Quote the table name to handle special characters like hyphens
        query = f"""
        DELETE FROM {schema_name}."{table_name}"
        WHERE time > {cutoff_date}
        """

        # Execute the delete query
        cursor.execute(query)

        # Get the number of rows deleted
        rows_deleted = cursor.rowcount

        # Commit the transaction
        conn.commit()

        print(f"Successfully deleted {rows_deleted} rows from '{schema_name}.{table_name}' "
              f"that were older than {num_days} days from current date")

        return rows_deleted

    except Exception as e:
        print(f"Error deleting data from table '{schema_name}.{table_name}': {e}")
        if conn:
            conn.rollback()
        return None

    finally:
        # Close the connection
        if cursor:
            cursor.close()
        if conn:
            conn.close()

#if you have locally saved df
def load_all_data_to_spot_db(data_path="/home/zhedge/trade/jaimakali_idx_fyers/data/historical_data/"):
    #data_path="/home/zhedge/trade/jaimakali_idx_fyers/data/historical_data/"
    db_name="spot_db"
    all_files=os.listdir(data_path)

    for i in range(len(all_files)):
        table_name=all_files[i].replace("NSE:","").replace("Dmin.csv","1D").replace("-EQ_","EQ").replace("min.csv","M").replace("-INDEX_","INDEX")
        print(table_name)
        df=pd.read_csv(data_path+all_files[i])
        

        crate_table_spot_data(db_name="spot_db",table_name=table_name)
        insert_dataframe_to_table(df, db_name, table_name, chunk_size=100000)
        df=get_table_content(db_name="spot_db", table_name=table_name, schema_name="public")




if __name__=="__main__":
    import os 
    os.system("service postgresql start")

    print_all_db_tables()
    create_all_db(db_list=["spot_db","option_db","future_db"])
    print_all_db_tables()
    pass
    """
    import datetime as dt
    end_date=dt.datetime.utcnow()
    start_date = dt.datetime.utcnow() - dt.timedelta(days=200)
    get_table_content(db_name="spot_db", table_name="nifty50index1m",schema_name="public",start_date=start_date,end_date=end_date)


    #delete_databases(db_list=["spot_db","live_db"])
    delete_all_databases()
    print_all_db_tables()
    create_all_db(db_list=["spot_db","option_db","future_db"])
    print_all_db_tables()
    load_all_data_to_spot_db() 
    print_all_db_tables()
 
    #crate_table_spot_data(db_name="spot_db",table_name="nifty50")
    #crate_table_option_data(db_name="option_db",table_name="nifty_opt")
    """


