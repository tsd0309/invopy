import os
import sys
import subprocess
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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
    # Set Flask environment variables
    os.environ['FLASK_APP'] = 'app.py'
    os.environ['FLASK_ENV'] = 'production'
    
    # Set database URL
    database_url = os.getenv('SQLALCHEMY_DATABASE_URI') or os.getenv('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    os.environ['SQLALCHEMY_DATABASE_URI'] = database_url
    os.environ['DATABASE_URL'] = database_url
    
    print(f"Set FLASK_APP to {os.environ.get('FLASK_APP')}")
    print(f"Set FLASK_ENV to {os.environ.get('FLASK_ENV')}")
    print(f"Set DATABASE_URL to {database_url[:20]}...")

def run_flask_migrations():
    """Run Flask migrations to set up the database schema"""
    print("Running Flask migrations...")
    try:
        # Check if Flask-Migrate is installed
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'Flask-Migrate'], check=True)
        
        # Run migrations
        result = subprocess.run([sys.executable, '-m', 'flask', 'db', 'current'], capture_output=True, text=True)
        print(f"Current migration: {result.stdout}")
        
        # Run upgrade
        result = subprocess.run([sys.executable, '-m', 'flask', 'db', 'upgrade'], check=True, capture_output=True, text=True)
        print(f"Migration output: {result.stdout}")
        
        print("Flask migrations completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running Flask migrations: {e}")
        print(f"Error output: {e.stderr}")
        return False

def main():
    print("=== Neon PostgreSQL Schema Setup ===")
    
    # Check environment variables
    if not check_env_variables():
        print("Please set all required environment variables in .env file.")
        return
    
    # Set Flask app environment
    set_flask_app_env()
    
    # Run Flask migrations
    if run_flask_migrations():
        print("Database schema setup completed successfully.")
        print("You can now run the migration script to migrate your data.")
    else:
        print("Database schema setup failed. Please check the error messages above.")

if __name__ == "__main__":
    main() 