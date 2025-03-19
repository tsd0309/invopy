from app import app, db, User, Permission

def fix_user_permissions():
    with app.app_context():
        # Get all permissions
        all_permissions = Permission.query.all()
        print(f"Total permissions: {len(all_permissions)}")
        
        # Get regular user
        user = User.query.filter_by(username='user').first()
        if not user:
            print("User not found")
            return
            
        # Basic permissions every user should have
        basic_permissions = [
            'view_products',
            'view_product_prices',
            'view_product_stock',
            'view_product_descriptions',
            'view_product_tamil_names',
            'view_product_uom',
            'view_invoices',
            'create_invoices'
        ]
        
        # Get Permission objects for basic permissions
        permissions_to_add = []
        for perm_name in basic_permissions:
            perm = Permission.query.filter_by(name=perm_name).first()
            if perm and perm not in user.permissions:
                permissions_to_add.append(perm)
        
        # Add permissions
        if permissions_to_add:
            print(f"Adding {len(permissions_to_add)} permissions to user")
            user.permissions.extend(permissions_to_add)
            db.session.commit()
            print("Permissions added successfully")
        else:
            print("User already has all basic permissions")
            
        # Print current permissions
        print("\nCurrent user permissions:")
        for perm in user.permissions:
            print(f"- {perm.name}")

if __name__ == '__main__':
    fix_user_permissions() 