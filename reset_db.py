from app import app, db, User, Permission, init_db
import os

def reset_database():
    try:
        # Get the database file path
        basedir = os.path.abspath(os.path.dirname(__file__))
        db_path = os.path.join(basedir, 'app.db')
        
        # Remove existing database file if it exists
        if os.path.exists(db_path):
            print(f"Removing existing database file: {db_path}")
            os.remove(db_path)
        
        with app.app_context():
            print("Creating new database...")
            db.create_all()
            
            print("Initializing database...")
            init_db()
            
            # Verify admin user
            admin = User.query.filter_by(username='admin').first()
            if admin:
                print(f"Admin user verified - ID: {admin.id}")
                print(f"Admin role: {admin.role}")
                print(f"2FA enabled: {admin.totp_enabled}")
            else:
                print("WARNING: Admin user not found!")
            
            # Verify permissions
            permissions = Permission.query.all()
            print(f"\nTotal permissions: {len(permissions)}")
            for p in permissions:
                print(f"- {p.name}: {p.description}")
            
            print("\nDatabase reset completed successfully!")
            
    except Exception as e:
        print(f"Error resetting database: {str(e)}")
        raise

if __name__ == '__main__':
    reset_database() 