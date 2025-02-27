import os
import subprocess
import sys
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_vercel_cli():
    """Check if Vercel CLI is installed"""
    try:
        subprocess.run(['vercel', '--version'], capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def install_vercel_cli():
    """Install Vercel CLI"""
    print("Installing Vercel CLI...")
    try:
        subprocess.run(['npm', 'install', '-g', 'vercel'], check=True)
        print("Vercel CLI installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install Vercel CLI: {e}")
        return False

def login_to_vercel():
    """Login to Vercel"""
    print("Logging in to Vercel...")
    try:
        subprocess.run(['vercel', 'login'], check=True)
        print("Logged in to Vercel successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to login to Vercel: {e}")
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

def update_vercel_json():
    """Update vercel.json with environment variables from .env"""
    try:
        # Read current vercel.json
        with open('vercel.json', 'r') as f:
            vercel_config = json.load(f)
        
        # Update environment variables
        vercel_config['env'] = {
            'PYTHONPATH': '.',
            'FLASK_ENV': os.getenv('FLASK_ENV', 'production'),
            'DATABASE_URL': os.getenv('DATABASE_URL'),
            'SQLALCHEMY_DATABASE_URI': os.getenv('SQLALCHEMY_DATABASE_URI'),
            'SECRET_KEY': os.getenv('SECRET_KEY')
        }
        
        # Write updated vercel.json
        with open('vercel.json', 'w') as f:
            json.dump(vercel_config, f, indent=4)
        
        print("Updated vercel.json with environment variables.")
        return True
    except Exception as e:
        print(f"Failed to update vercel.json: {e}")
        return False

def deploy_to_vercel():
    """Deploy to Vercel"""
    print("Deploying to Vercel...")
    try:
        # Run vercel with production flag
        subprocess.run(['vercel', '--prod'], check=True)
        print("Deployed to Vercel successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to deploy to Vercel: {e}")
        return False

def main():
    print("=== Vercel Deployment Helper ===")
    
    # Check if Vercel CLI is installed
    if not check_vercel_cli():
        print("Vercel CLI is not installed.")
        if not install_vercel_cli():
            print("Please install Vercel CLI manually: npm install -g vercel")
            return
    
    # Check environment variables
    if not check_env_variables():
        print("Please set all required environment variables in .env file.")
        return
    
    # Update vercel.json
    if not update_vercel_json():
        print("Failed to update vercel.json. Please check the file.")
        return
    
    # Login to Vercel if needed
    print("Do you need to login to Vercel? (y/n)")
    if input().lower() == 'y':
        if not login_to_vercel():
            print("Failed to login to Vercel. Please try again.")
            return
    
    # Deploy to Vercel
    if deploy_to_vercel():
        print("Your application has been deployed to Vercel!")
        print("You can now access your application at the URL provided by Vercel.")
    else:
        print("Deployment failed. Please check the error messages above.")

if __name__ == "__main__":
    main() 