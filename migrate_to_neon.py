import os
import sqlite3
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine
import time
import traceback
import sys

# Load environment variables
load_dotenv()

# Get Neon PostgreSQL connection string
DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('SQLALCHEMY_DATABASE_URI')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# SQLite database path
SQLITE_DB_PATH = 'app.db'

def connect_to_sqlite():
    """Connect to SQLite database"""
    print("Connecting to SQLite database...")
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        print("SQLite connection successful!")
        return conn
    except Exception as e:
        print(f"Error connecting to SQLite: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

def connect_to_postgres():
    """Connect to PostgreSQL database"""
    print(f"Connecting to PostgreSQL database using URL: {DATABASE_URL[:20]}...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("PostgreSQL connection successful!")
        return conn
    except Exception as e:
        print(f"Error connecting to PostgreSQL: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

def get_table_names(sqlite_conn):
    """Get all table names from SQLite database"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    return [table[0] for table in tables if not table[0].startswith('sqlite_') and not table[0].startswith('alembic_')]

def get_table_schema(sqlite_conn, table_name):
    """Get schema for a table"""
    cursor = sqlite_conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()
    return columns

def test_postgres_connection():
    """Test connection to PostgreSQL and verify table structure"""
    try:
        print("Testing PostgreSQL connection...")
        pg_conn = connect_to_postgres()
        pg_cursor = pg_conn.cursor(cursor_factory=DictCursor)
        
        # Check if product table exists
        pg_cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'product');")
        table_exists = pg_cursor.fetchone()[0]
        
        if not table_exists:
            print("ERROR: 'product' table does not exist in PostgreSQL database.")
            print("Please run Flask migrations first: python -m flask db upgrade")
            return False
        
        # Get column names from product table
        pg_cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'product';")
        columns = pg_cursor.fetchall()
        print(f"PostgreSQL product table columns: {[col[0] for col in columns]}")
        
        pg_conn.close()
        print("PostgreSQL connection test successful!")
        return True
    except Exception as e:
        print(f"Error testing PostgreSQL connection: {str(e)}")
        traceback.print_exc()
        return False

def migrate_products():
    """Migrate products from SQLite to PostgreSQL"""
    try:
        # Test PostgreSQL connection first
        if not test_postgres_connection():
            return
        
        # Connect to both databases
        sqlite_conn = connect_to_sqlite()
        pg_conn = connect_to_postgres()
        pg_cursor = pg_conn.cursor(cursor_factory=DictCursor)
        
        print("Migrating products...")
        
        # Get products from SQLite
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT * FROM product;")
        products = sqlite_cursor.fetchall()
        
        # Get column names
        column_names = [description[0] for description in sqlite_cursor.description]
        print(f"SQLite product table columns: {column_names}")
        
        # Check if products exist
        if not products:
            print("No products found in SQLite database.")
            return
        
        print(f"Found {len(products)} products to migrate.")
        
        # Clear existing products in PostgreSQL if any
        pg_cursor.execute("DELETE FROM product;")
        pg_conn.commit()
        print("Cleared existing products in PostgreSQL.")
        
        # Prepare SQL for insertion
        columns_str = ", ".join(column_names)
        placeholders = ", ".join(["%s"] * len(column_names))
        insert_sql = f"INSERT INTO product ({columns_str}) VALUES ({placeholders});"
        
        # Insert products into PostgreSQL in batches
        batch_size = 100
        total_migrated = 0
        
        for i in range(0, len(products), batch_size):
            batch = products[i:i+batch_size]
            try:
                for product in batch:
                    pg_cursor.execute(insert_sql, product)
                pg_conn.commit()
                total_migrated += len(batch)
                print(f"Migrated batch {i//batch_size + 1}/{(len(products)-1)//batch_size + 1} ({total_migrated}/{len(products)} products)")
            except Exception as e:
                pg_conn.rollback()
                print(f"Error migrating batch starting at index {i}: {str(e)}")
                print(f"First product in failed batch: {batch[0]}")
                traceback.print_exc()
        
        # Verify migration
        pg_cursor.execute("SELECT COUNT(*) FROM product;")
        count = pg_cursor.fetchone()[0]
        print(f"Verification: {count} products in PostgreSQL database.")
        
        if count == len(products):
            print(f"Successfully migrated all {len(products)} products to PostgreSQL.")
        else:
            print(f"WARNING: Only {count} out of {len(products)} products were migrated.")
        
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        traceback.print_exc()
    finally:
        # Close connections
        if 'sqlite_conn' in locals():
            sqlite_conn.close()
        if 'pg_conn' in locals():
            pg_conn.close()

def migrate_all_data():
    """Migrate all data from SQLite to PostgreSQL"""
    try:
        # Test PostgreSQL connection first
        if not test_postgres_connection():
            return
            
        # Create SQLAlchemy engines for both databases
        print("Creating database engines...")
        sqlite_engine = create_engine(f'sqlite:///{SQLITE_DB_PATH}')
        pg_engine = create_engine(DATABASE_URL)
        
        # Connect to SQLite to get table names
        sqlite_conn = connect_to_sqlite()
        tables = get_table_names(sqlite_conn)
        sqlite_conn.close()
        
        print(f"Found {len(tables)} tables to migrate: {tables}")
        
        # Migrate each table
        for table in tables:
            try:
                print(f"Migrating table: {table}")
                
                # Read data from SQLite
                df = pd.read_sql_table(table, sqlite_engine)
                
                if df.empty:
                    print(f"Table {table} is empty, skipping.")
                    continue
                
                print(f"Found {len(df)} rows in {table}.")
                print(f"Columns: {df.columns.tolist()}")
                
                # Write to PostgreSQL
                # Use if_exists='replace' to replace the table if it exists
                df.to_sql(table, pg_engine, if_exists='replace', index=False)
                
                # Verify migration
                verify_df = pd.read_sql_table(table, pg_engine)
                print(f"Verification: {len(verify_df)} rows in PostgreSQL {table} table.")
                
                if len(verify_df) == len(df):
                    print(f"Successfully migrated table: {table}")
                else:
                    print(f"WARNING: Only {len(verify_df)} out of {len(df)} rows were migrated for table {table}.")
                
                # Small delay to avoid overwhelming the database
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error migrating table {table}: {str(e)}")
                traceback.print_exc()
    
    except Exception as e:
        print(f"Error during full migration: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    print("Starting migration to Neon PostgreSQL...")
    print(f"Using database URL: {DATABASE_URL[:20]}...")
    
    if not DATABASE_URL:
        print("ERROR: No database URL found. Please check your .env file.")
        sys.exit(1)
    
    # Choose migration method
    choice = input("Do you want to migrate only products (p) or all data (a)? ").lower()
    
    if choice == 'p':
        migrate_products()
    elif choice == 'a':
        migrate_all_data()
    else:
        print("Invalid choice. Please run again and select 'p' or 'a'.")
    
    print("Migration process completed.") 