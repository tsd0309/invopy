import os
import sys
import subprocess
from dotenv import load_dotenv
from app import app, db, User, Permission
from werkzeug.security import generate_password_hash
import psycopg2
from sqlalchemy import text, inspect

# Load environment variables
load_dotenv()

def test_db_connection():
    """Test direct connection to Neon database"""
    database_url = os.getenv('DATABASE_URL')
    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute('SELECT version();')
        version = cur.fetchone()
        print(f"Successfully connected to Neon PostgreSQL: {version[0]}")
        
        # Check if tables exist
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = cur.fetchall()
        print("Existing tables:", [table[0] for table in tables])
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error connecting to database: {str(e)}")
        return False

def check_env_variables():
    """Check if all required environment variables are set"""
    required_vars = [
        'DATABASE_URL',
        'SQLALCHEMY_DATABASE_URI',
        'SECRET_KEY',
        'FLASK_ENV'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"Missing environment variables: {', '.join(missing_vars)}")
        return False
    
    return True

def set_flask_app_env():
    """Set Flask app environment variables"""
    os.environ['FLASK_APP'] = 'app.py'
    os.environ['FLASK_ENV'] = 'production'
    
    database_url = os.getenv('SQLALCHEMY_DATABASE_URI') or os.getenv('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    os.environ['SQLALCHEMY_DATABASE_URI'] = database_url
    os.environ['DATABASE_URL'] = database_url
    
    print(f"Set FLASK_APP to {os.environ.get('FLASK_APP')}")
    print(f"Set FLASK_ENV to {os.environ.get('FLASK_ENV')}")
    print(f"Database URL configured (first 20 chars): {database_url[:20]}...")

def force_create_tables():
    """Force create all tables by dropping existing ones"""
    with app.app_context():
        try:
            # Drop all tables
            print("Dropping existing tables...")
            db.drop_all()
            print("All tables dropped successfully")
            
            # Create all tables
            print("Creating new tables...")
            db.create_all()
            print("All tables created successfully")
            return True
        except Exception as e:
            print(f"Error creating tables: {str(e)}")
            return False

def verify_tables():
    """Verify if tables exist in the database"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"Verified tables in database: {', '.join(tables)}")
            return len(tables) > 0
        except Exception as e:
            print(f"Error verifying tables: {str(e)}")
            return False

def init_permissions():
    with app.app_context():
        try:
            default_permissions = [
                ('view_customers', 'Can view customers list'),
                ('edit_customers', 'Can create, edit and delete customers'),
                ('view_products', 'Can view products list'),
                ('edit_products', 'Can create, edit and delete products'),
                ('edit_product_price', 'Can edit product prices'),
                ('edit_product_stock', 'Can edit product stock levels'),
                ('edit_product_restock', 'Can edit product restock levels'),
                ('edit_product_locations', 'Can edit product storage locations'),
                ('view_invoices', 'Can view invoices list'),
                ('create_invoices', 'Can create new invoices'),
                ('edit_invoices', 'Can edit existing invoices'),
                ('delete_invoices', 'Can delete invoices'),
                ('view_product_tags', 'Can view product tags'),
                ('edit_product_tags', 'Can edit product tags'),
                ('view_product_notes', 'Can view product notes'),
                ('edit_product_notes', 'Can edit product notes'),
                ('view_product_suppliers', 'Can view product suppliers'),
                ('view_reports', 'Can view reports'),
                ('manage_settings', 'Can manage system settings'),
                ('manage_users', 'Can manage users'),
                ('view_suppliers', 'Can view suppliers list'),
                ('edit_suppliers', 'Can create, edit and delete suppliers')
            ]
            
            for name, description in default_permissions:
                if not Permission.query.filter_by(name=name).first():
                    permission = Permission(name=name, description=description)
                    db.session.add(permission)
                    print(f"Added permission: {name}")
            
            db.session.commit()
            print("All permissions committed successfully")
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Error initializing permissions: {str(e)}")
            return False

def init_admin():
    with app.app_context():
        try:
            # Force create admin user
            admin_user = User.query.filter_by(username='admin').first()
            if admin_user:
                print("Deleting existing admin user...")
                db.session.delete(admin_user)
                db.session.commit()
            
            print("Creating new admin user...")
            admin_user = User(
                username='admin',
                password=generate_password_hash('admin'),
                role='admin'
            )
            db.session.add(admin_user)
            db.session.commit()
            
            # Verify admin user was created
            created_admin = User.query.filter_by(username='admin').first()
            if created_admin:
                print(f"Admin user created successfully - ID: {created_admin.id}")
                return True
            else:
                print("Failed to create admin user")
                return False
        except Exception as e:
            db.session.rollback()
            print(f"Error creating admin user: {str(e)}")
            return False

def setup_schema():
    print("\nStarting schema setup...")
    
    # Step 1: Force create tables
    if not force_create_tables():
        print("Failed to create tables")
        return False
    
    # Step 2: Initialize permissions
    if not init_permissions():
        print("Failed to initialize permissions")
        return False
    
    # Step 3: Create admin user
    if not init_admin():
        print("Failed to create admin user")
        return False
    
    print("\nSchema setup completed successfully!")
    return True

def main():
    print("=== Neon PostgreSQL Schema Setup ===")
    
    if not check_env_variables():
        print("Error: Missing environment variables")
        return
    
    print("\n1. Testing database connection...")
    if not test_db_connection():
        print("Error: Could not connect to database")
        return
    
    print("\n2. Setting up Flask environment...")
    set_flask_app_env()
    
    print("\n3. Setting up schema and initial data...")
    if setup_schema():
        print("\nSetup completed successfully!")
        print("You can now login with:")
        print("Username: admin")
        print("Password: admin")
        
        # Final verification
        print("\nVerifying setup...")
        verify_tables()
        with app.app_context():
            admin = User.query.filter_by(username='admin').first()
            if admin:
                print(f"Admin user verified - ID: {admin.id}, Role: {admin.role}")
            else:
                print("Warning: Admin user not found in final verification!")
    else:
        print("\nSetup failed. Please check the error messages above.")

if __name__ == "__main__":
    main() 