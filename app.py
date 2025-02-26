from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, render_template_string, make_response, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, date, timedelta
import os
from dotenv import load_dotenv
import io
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
import pandas as pd  # Import pandas
import openpyxl
import xlrd
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps, lru_cache
from pyotp import random_base32, TOTP
import traceback
import psycopg2
from psycopg2.extras import DictCursor

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24))
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Cache configuration
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1 year
app.config['STATIC_FOLDER'] = 'static'

# Cache decorators
def cache_for(seconds):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = f.__name__ + str(args) + str(kwargs)
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            result = f(*args, **kwargs)
            cache.set(cache_key, result, timeout=seconds)
            return result
        return decorated_function
    return decorator

# Simple in-memory cache
class SimpleCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, key):
        if key in self._cache:
            item = self._cache[key]
            if item['expires'] > datetime.utcnow():
                return item['value']
            else:
                del self._cache[key]
        return None
        
    def set(self, key, value, timeout=300):
        self._cache[key] = {
            'value': value,
            'expires': datetime.utcnow() + timedelta(seconds=timeout)
        }
        
    def delete(self, key):
        if key in self._cache:
            del self._cache[key]

cache = SimpleCache()

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Models
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.String(200), nullable=False)
    tamil_name = db.Column(db.String(200))  # Optional Tamil name
    uom = db.Column(db.String(10), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    restock_level = db.Column(db.Integer, default=0)  # Level at which to restock
    stock_locations = db.Column(db.String(500))  # Comma-separated location tags
    tags = db.Column(db.String(500))  # Comma-separated tags
    notes = db.Column(db.Text)  # Product notes

    @property
    def serialize(self):
        return {
            'id': self.id,
            'item_code': self.item_code,
            'description': self.description,
            'tamil_name': self.tamil_name,
            'uom': self.uom,
            'price': self.price,
            'stock': self.stock,
            'restock_level': self.restock_level,
            'stock_locations': self.stock_locations,
            'tags': self.tags,
            'notes': self.notes
        }

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    balance = db.Column(db.Float, default=0.0)  # Positive means customer owes money, negative means surplus
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    invoices = db.relationship('Invoice', backref='customer', lazy=True)
    transactions = db.relationship('CustomerTransaction', backref='customer', lazy=True)
    receivables = db.relationship('CustomerReceivable', backref='customer', lazy=True)

    def update_balance(self):
        # Start with 0 balance
        total_balance = 0.0
        
        # Add receivables (amounts customer owes)
        for receivable in self.receivables:
            total_balance += receivable.amount + receivable.additional_amount
        
        # Subtract payments (reduce balance) or add refunds (increase balance)
        for transaction in self.transactions:
            if transaction.transaction_type == 'payment':
                total_balance -= transaction.amount
            elif transaction.transaction_type == 'refund':
                total_balance += transaction.amount
        
        # Update the balance
        self.balance = round(total_balance, 2)
        db.session.commit()

class CustomerTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'payment' or 'refund'
    payment_method = db.Column(db.String(50))  # 'cash', 'card', 'upi', etc.
    notes = db.Column(db.Text)
    reference_number = db.Column(db.String(50))  # For tracking payment references

class CustomerReceivable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))  # Optional, for linked invoices
    additional_amount = db.Column(db.Float, default=0.0)  # For additional amounts on linked invoices
    
    # Remove the duplicate backref and use foreign_keys for clarity
    invoice = db.relationship('Invoice', backref='receivable')

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(3), nullable=False)  # Daily 3-digit number
    date = db.Column(db.Date, nullable=False, default=date.today)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    customer_name = db.Column(db.String(200))
    total_amount = db.Column(db.Float, default=0.0)
    total_items = db.Column(db.Integer, default=0)
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade="all, delete-orphan")
    payment_status = db.Column(db.String(20), default='pending')  # pending, partial, paid

    @classmethod
    def generate_order_number(cls):
        # Get the latest invoice for today
        today = date.today()
        latest_invoice = cls.query.filter(
            func.date(cls.date) == today
        ).order_by(cls.id.desc()).first()
        
        if latest_invoice:
            last_number = int(latest_invoice.order_number)
            new_number = str(last_number + 1).zfill(3)
        else:
            new_number = '001'
        
        return new_number

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    product = db.relationship('Product', backref='invoice_items')

class PrintTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'invoice' or 'summary'
    content = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Models
class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

# User-Permission association table
user_permissions = db.Table('user_permissions',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # Increased length for hashed password
    role = db.Column(db.String(20), nullable=False, default='user')
    totp_secret = db.Column(db.String(32))
    totp_enabled = db.Column(db.Boolean, default=False)
    permissions = db.relationship('Permission', secondary=user_permissions, lazy='subquery',
        backref=db.backref('users', lazy=True))

    def verify_totp(self, token):
        if not self.totp_enabled or not self.totp_secret:
            return True
        totp = TOTP(self.totp_secret)
        return totp.verify(token)

    def has_permission(self, permission_name):
        if self.role == 'admin':  # Admin has all permissions
            return True
        return any(p.name == permission_name for p in self.permissions)

    def has_any_permission(self, permission_names):
        if self.role == 'admin':  # Admin has all permissions
            return True
        return any(p.name in permission_names for p in self.permissions)

# Function to initialize default permissions
def init_permissions():
    default_permissions = [
        ('view_customers', 'Can view customers list and details'),
        ('edit_customers', 'Can create, edit and delete customers'),
        ('view_invoices', 'Can view invoices'),
        ('create_invoices', 'Can create new invoices'),
        ('edit_invoices', 'Can edit existing invoices'),
        ('delete_invoices', 'Can delete invoices'),
        ('view_products', 'Can view products list'),
        ('edit_products', 'Can create, edit and delete products'),
        ('import_products', 'Can import products from Excel/CSV'),
        ('export_products', 'Can export products to Excel/CSV'),
        ('manage_stock', 'Can update product stock levels'),
        ('delete_products', 'Can delete products'),
        # Product field-specific permissions
        ('view_product_code', 'Can view product item codes'),
        ('edit_product_code', 'Can edit product item codes'),
        ('view_product_description', 'Can view product descriptions'),
        ('edit_product_description', 'Can edit product descriptions'),
        ('view_product_tamil', 'Can view product Tamil names'),
        ('edit_product_tamil', 'Can edit product Tamil names'),
        ('view_product_uom', 'Can view product UOM'),
        ('edit_product_uom', 'Can edit product UOM'),
        ('view_product_price', 'Can view product prices'),
        ('edit_product_price', 'Can edit product prices'),
        ('view_product_stock', 'Can view product stock levels'),
        ('edit_product_stock', 'Can edit product stock levels'),
        ('view_product_restock', 'Can view product restock levels'),
        ('edit_product_restock', 'Can edit product restock levels'),
        ('view_product_locations', 'Can view product locations'),
        ('edit_product_locations', 'Can edit product locations'),
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
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error initializing permissions: {str(e)}")

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    calculator_code = db.Column(db.String(20), default='9999')
    wallpaper_path = db.Column(db.String(200))  # Path to the wallpaper file

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Permission required decorator
def permission_required(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            
            user = User.query.get(session['user_id'])
            if not user:
                return redirect(url_for('login'))
            
            if not user.has_permission(permission_name):
                flash('You do not have permission to access this page')
                return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            flash('Admin access required')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Add helper function for getting user info
def get_user(user_id):
    return User.query.get(user_id)

# Add to template context
app.jinja_env.globals.update(get_user=get_user)

# Create tables and add sample data
def init_db():
    with app.app_context():
        # Drop all tables
        db.drop_all()
        # Create all tables
        db.create_all()
        
        # Initialize permissions first
        init_permissions()
        
        # Create admin user if none exists
        admin_user = User.query.filter_by(role='admin').first()
        if not admin_user:
            admin_user = User(
                username='admin',
                password=generate_password_hash('admin'),
                role='admin'
            )
            db.session.add(admin_user)
            db.session.commit()

        # Initialize settings if not exists
        settings = Settings.query.first()
        if not settings:
            settings = Settings(calculator_code='9999')
            db.session.add(settings)
            db.session.commit()
        
        # Add some sample customers
        sample_customers = [
            Customer(
                name='John Doe',
                phone='1234567890',
                email='john@example.com',
                address='123 Main St'
            ),
            Customer(
                name='Jane Smith',
                phone='9876543210',
                email='jane@example.com',
                address='456 Oak Ave'
            )
        ]
        
        for customer in sample_customers:
            db.session.add(customer)
        
        # Add some sample products with restock levels
        sample_products = [
            Product(
                item_code='2714',
                description='AGAL FANCY RPS 1',
                uom='PCS',
                price=55.0,
                stock=100,
                restock_level=50,
                stock_locations='Shelf A, Rack 1',
                tags='pooja items, agal',
                notes='Popular item during festival season'
            ),
            Product(
                item_code='33846',
                description='11423 3 CANDANPIYALI',
                uom='PCS',
                price=210.0,
                stock=50,
                restock_level=75,
                stock_locations='Shelf B, Box 3',
                tags='fragile, premium',
                notes='Handle with care, premium product'
            ),
            Product(
                item_code='2959',
                description='ABISHEKAM SIVLING RPS',
                uom='kgs',
                price=900.0,
                stock=75,
                restock_level=100,
                stock_locations='Shelf C',
                tags='heavy, temple items',
                notes='Special packaging required'
            ),
            Product(
                item_code='2324',
                description='AGAL KAMAL DEEP 1 LW',
                uom='PCS',
                price=60.0,
                stock=200,
                restock_level=150,
                stock_locations='Shelf A, Rack 2',
                tags='pooja items, agal, popular',
                notes='High demand during Diwali'
            ),
        ]
        
        for product in sample_products:
            db.session.add(product)
        
        db.session.commit()

# Helper function to delete invoices and invoice items
def _delete_all_invoices():
    InvoiceItem.query.delete()
    Invoice.query.delete()

# Helper function to delete products, invoices and invoice items
def _delete_all_products():
    InvoiceItem.query.delete()
    Invoice.query.delete()
    Product.query.delete()

# Routes
@app.route('/')
@login_required
def index():
    cached_data = cache.get('dashboard_data')
    if cached_data is not None:
        return cached_data
        
    # Get current user
    user = User.query.get(session['user_id'])
    
    # Get products that are at or below their restock level
    low_stock_products = Product.query.filter(Product.stock <= Product.restock_level).all()
    
    # Get recent invoices
    recent_invoices = Invoice.query.order_by(Invoice.date.desc()).limit(5).all()
    
    response = render_template('index.html', 
                             user=user,
                             low_stock_products=low_stock_products,
                             recent_invoices=recent_invoices)
    
    # Calculate total inventory cost
    total_inventory_cost = sum(product.stock * product.price for product in Product.query.all())
    
    # Calculate stock-out count
    stockout_count = Product.query.filter(Product.stock == 0).count()
    
    # Calculate average stock-to-sales ratio
    products = Product.query.all()
    total_ratio = 0
    products_with_sales = 0
    for product in products:
        total_sales = db.session.query(func.sum(InvoiceItem.quantity)).filter(
            InvoiceItem.product_id == product.id
        ).scalar() or 0
        if total_sales > 0:
            total_ratio += product.stock / total_sales
            products_with_sales += 1
    avg_stock_sales_ratio = total_ratio / products_with_sales if products_with_sales > 0 else 0
    
    stats = {
        'total_products': Product.query.count(),
        'total_invoices': Invoice.query.count(),
        'total_sales': db.session.query(db.func.sum(Invoice.total_amount)).scalar() or 0,
        'recent_invoices': Invoice.query.order_by(Invoice.date.desc()).limit(5).all(),
        'low_stock_products': low_stock_products,
        'total_inventory_cost': total_inventory_cost,
        'stockout_count': stockout_count,
        'avg_stock_sales_ratio': avg_stock_sales_ratio,
        'slow_moving_count': 0,
        'stockout_frequency': []
    }
    return render_template('index.html', stats=stats, wallpaper_url=wallpaper_url)

@app.route('/products/search')
@login_required
def search_products():
    query = request.args.get('q', '').lower()
    search_terms = [term.strip() for term in query.split() if term.strip()]
    
    if not search_terms:
        return jsonify([])
    
    # Build the search query
    search_query = Product.query
    
    # Search across multiple fields with OR conditions
    search_conditions = []
    for term in search_terms:
        term_conditions = []
        # Search in item_code
        term_conditions.append(Product.item_code.ilike(f'%{term}%'))
        # Search in description
        term_conditions.append(Product.description.ilike(f'%{term}%'))
        # Search in tamil_name
        term_conditions.append(Product.tamil_name.ilike(f'%{term}%'))
        # Search in stock_locations
        term_conditions.append(Product.stock_locations.ilike(f'%{term}%'))
        # Search in tags
        term_conditions.append(Product.tags.ilike(f'%{term}%'))
        # Search in notes
        term_conditions.append(Product.notes.ilike(f'%{term}%'))
        # Search in UOM
        term_conditions.append(Product.uom.ilike(f'%{term}%'))
        
        # Combine conditions for this term with OR
        search_conditions.append(db.or_(*term_conditions))
    
    # Apply all term conditions with AND
    search_query = search_query.filter(db.and_(*search_conditions))
    
    # Execute query and get results
    products = search_query.order_by(Product.item_code).all()
    
    # Return serialized results with additional fields
    return jsonify([{
        **product.serialize,
        'stock_locations_display': product.stock_locations or '',
        'tags_display': product.tags or '',
        'notes_display': product.notes or ''
    } for product in products])

@app.route('/products', methods=['GET', 'POST'])
@login_required
@permission_required('view_products')
def products():
    if request.method == 'POST':
        # Check if user has edit permission
        current_user = User.query.get(session['user_id'])
        if not (current_user.role == 'admin' or current_user.has_permission('edit_products')):
            return jsonify({'success': False, 'error': 'Permission denied'})
            
        data = request.json
        
        # Server-side validation
        if not all(key in data for key in ('item_code', 'description', 'uom', 'price')):
            return jsonify({'success': False, 'error': 'Missing required data'})
        
        try:
            # Convert and validate numeric fields
            try:
                price = float(data['price'])
                stock = int(data.get('stock', 0))
                restock_level = int(data.get('restock_level', 0))
            except ValueError as e:
                return jsonify({'success': False, 'error': f'Invalid numeric value: {str(e)}'})
            
            # Create new product
            product = Product(
                item_code=data['item_code'],
                description=data['description'],
                tamil_name=data.get('tamil_name', ''),
                uom=data['uom'],
                price=price,
                stock=stock,
                restock_level=restock_level,
                stock_locations=data.get('stock_locations', ''),
                tags=data.get('tags', ''),
                notes=data.get('notes', '')
            )
            
            db.session.add(product)
            db.session.commit()
            return jsonify({'success': True})
            
        except IntegrityError:
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Item code already exists'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    # Get current user for permission checks in template
    current_user = User.query.get(session['user_id'])
    
    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Number of items per page
    
    # Get total count for pagination
    total_count = Product.query.count()
    total_pages = (total_count + per_page - 1) // per_page
    
    # Get paginated products
    products = Product.query.order_by(Product.item_code).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('products.html', 
                         products=products.items,
                         current_user=current_user,
                         pagination=products,
                         total_pages=total_pages,
                         current_page=page)

@app.route('/products/<int:id>', methods=['PUT'])
@login_required
def update_product(id):
    product = Product.query.get_or_404(id)
    data = request.json
    current_user = User.query.get(session['user_id'])
    
    try:
        # Check permissions for each field that is being updated
        if 'item_code' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_code')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit item code'})
            
        if 'description' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_description')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit description'})
            
        if 'tamil_name' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_tamil')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit Tamil name'})
            
        if 'uom' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_uom')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit UOM'})
            
        if 'price' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_price')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit price'})
            
        if 'stock' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_stock')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit stock'})
            
        if 'restock_level' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_restock')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit restock level'})
            
        if 'stock_locations' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_locations')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit locations'})
            
        if 'tags' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_tags')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit tags'})
            
        if 'notes' in data and not (current_user.role == 'admin' or current_user.has_permission('edit_product_notes')):
            return jsonify({'success': False, 'error': 'Permission denied: Cannot edit notes'})
        
        # Update only the fields that are present in the request data and user has permission for
        if 'item_code' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_code')):
            product.item_code = data['item_code']
            
        if 'description' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_description')):
            product.description = data['description']
            
        if 'tamil_name' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_tamil')):
            product.tamil_name = data['tamil_name']
            
        if 'uom' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_uom')):
            product.uom = data['uom']
            
        if 'price' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_price')):
            product.price = float(data['price'])
            
        if 'stock' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_stock')):
            product.stock = int(data['stock'])
            
        if 'restock_level' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_restock')):
            product.restock_level = int(data['restock_level'])
            
        if 'stock_locations' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_locations')):
            product.stock_locations = data['stock_locations']
            
        if 'tags' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_tags')):
            product.tags = data['tags']
            
        if 'notes' in data and (current_user.role == 'admin' or current_user.has_permission('edit_product_notes')):
            product.notes = data['notes']
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/products/<int:id>', methods=['DELETE'])
@login_required
def product(id):
    product = Product.query.get_or_404(id)
    user = User.query.get(session['user_id'])  # Get current user
    
    if request.method == 'DELETE':
        if not user.has_permission('delete_products'):
            return jsonify({'success': False, 'error': 'Permission denied'})
            
        try:
            db.session.delete(product)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

@app.route('/invoices')
@login_required
@permission_required('view_invoices')
def invoices():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = Invoice.query
    if start_date and end_date:
        query = query.filter(
            Invoice.date >= datetime.strptime(start_date, '%Y-%m-%d').date(),
            Invoice.date <= datetime.strptime(end_date, '%Y-%m-%d').date()
        )
    
    invoices = query.order_by(Invoice.date.desc()).all()
    return render_template('invoices.html', invoices=invoices)

@app.route('/invoices/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def invoice(id):
    invoice = Invoice.query.get_or_404(id)
    
    if request.method == 'GET':
        return jsonify({
            'id': invoice.id,
            'order_number': invoice.order_number,
            'date': invoice.date.isoformat(),
            'customer_name': invoice.customer_name,
            'total_amount': invoice.total_amount,
            'total_items': invoice.total_items,
            'items': [{
                'id': item.id,
                'product_id': item.product_id,
                'product_code': item.product.item_code,
                'description': item.product.description,
                'uom': item.product.uom,
                'quantity': item.quantity,
                'price': item.price,
                'amount': item.amount
            } for item in invoice.items]
        })
    
    elif request.method == 'PUT':
        data = request.json
        invoice.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        invoice.customer_name = data['customer_name']
        invoice.total_amount = float(data['total_amount'])
        invoice.total_items = int(data['total_items'])
        
        # Restore stock for existing items
        for item in invoice.items:
            item.product.stock += item.quantity
        
        # Remove existing items
        for item in invoice.items:
            db.session.delete(item)
        
        # Add new items
        for item_data in data['items']:
            product = Product.query.get(item_data['product_id'])
            # Remove stock validation check
            item = InvoiceItem(
                invoice=invoice,
                product_id=item_data['product_id'],
                quantity=item_data['quantity'],
                price=item_data['price'],
                amount=item_data['amount']
            )
            product.stock -= item_data['quantity']
            db.session.add(item)
        
        try:
            db.session.commit()
            # Return the invoice ID so the frontend can handle printing
            return jsonify({
                'success': True,
                'id': invoice.id,
                'redirect': url_for('new_invoice')
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        data = request.json
        restore_stock = data.get('restore_stock', False)
        
        try:
            if restore_stock:
                # Restore stock for all items
                for item in invoice.items:
                    item.product.stock += item.quantity
            
            db.session.delete(invoice)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

@app.route('/invoices/<int:id>/print')
def print_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    return render_template('print_invoice.html', invoice=invoice)

@app.route('/invoices/<int:id>/print-tamil')
def print_invoice_tamil(id):
    invoice = Invoice.query.get_or_404(id)
    return render_template('print_invoice_tamil.html', invoice=invoice)

@app.route('/new_invoice', methods=['GET', 'POST'])
def new_invoice():
    if request.method == 'POST':
        data = request.json
        invoice = Invoice(
            order_number=Invoice.generate_order_number(),
            date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
            customer_id=data.get('customer_id'),
            customer_name=data['customer_name'],
            total_amount=float(data['total_amount']),
            total_items=int(data['total_items'])
        )
        
        try:
            db.session.add(invoice)
            
            for item_data in data['items']:
                product = Product.query.get(item_data['product_id'])
                invoice_item = InvoiceItem(
                    invoice=invoice,
                    product_id=item_data['product_id'],
                    quantity=item_data['quantity'],
                    price=item_data['price'],
                    amount=item_data['amount']
                )
                product.stock -= item_data['quantity']
                db.session.add(invoice_item)
            
            if invoice.customer_id:
                customer = Customer.query.get(invoice.customer_id)
                customer.update_balance()
            
            db.session.commit()
            # Change the response to include redirect URL
            return jsonify({
                'success': True, 
                'id': invoice.id,
                'redirect': url_for('new_invoice')
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    customer_id = request.args.get('customer_id')
    customer = Customer.query.get(customer_id) if customer_id else None
    products = Product.query.all()
    return render_template('new_invoice.html', products=products, customer=customer)

@app.route('/invoices/print_summary')
@login_required
def print_summary():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = Invoice.query
    
    if start_date:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        query = query.filter(Invoice.date >= start_date)
    if end_date:
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        query = query.filter(Invoice.date <= end_date)
    
    invoices = query.order_by(Invoice.date).all()
    total_amount = sum(invoice.total_amount for invoice in invoices)
    
    return render_template('print_summary.html',
                         invoices=invoices,
                         total_amount=total_amount)

@app.route('/products/import', methods=['POST'])
@login_required
@permission_required('import_products')
def import_products():
    try:
        if 'file' not in request.files:
            print("No file in request.files")  # Debug log
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if file.filename == '':
            print("Empty filename")  # Debug log
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not file.filename.endswith(('.xlsx', '.xls')):
            print(f"Invalid file type: {file.filename}")  # Debug log
            return jsonify({'success': False, 'error': 'Invalid file format. Please upload an Excel file.'}), 400
        
        print(f"Processing file: {file.filename}")  # Debug log
        
        # Initialize counters and error list
        total_count = 0
        imported_count = 0
        error_details = []
        products = []
        
        try:
            # Read the Excel file
            wb = openpyxl.load_workbook(file, data_only=True)
            sheet = wb.active
            
            # Validate header row
            header_row = next(sheet.iter_rows(min_row=1, max_row=1))
            if len(header_row) < 6:
                print("Invalid header row")  # Debug log
                return jsonify({'success': False, 'error': 'Invalid file format. Missing required columns.'}), 400
            
            # Process data rows
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2), start=2):
                total_count += 1
                try:
                    # Skip empty rows
                    if not any(cell.value for cell in row):
                        continue
                        
                    # Basic validation
                    if not row[0].value or not row[1].value or not row[3].value:
                        error_details.append(f"Row {row_idx}: Missing required fields (Item Code, Description, or UOM)")
                        continue
                    
                    # Handle price and stock
                    try:
                        price = float(str(row[4].value or '0').replace(',', ''))
                        stock = int(float(str(row[5].value or '0').replace(',', '')))
                    except (ValueError, TypeError) as e:
                        error_details.append(f"Row {row_idx}: Invalid price or stock value")
                        print(f"Error parsing price/stock in row {row_idx}: {str(e)}")  # Debug log
                        continue
                    
                    product = {
                        'item_code': str(row[0].value).strip(),
                        'description': str(row[1].value).strip(),
                        'tamil_name': str(row[2].value).strip() if row[2].value else None,
                        'uom': str(row[3].value).strip(),
                        'price': price,
                        'stock': stock,
                        'restock_level': int(float(str(row[6].value or '0').replace(',', ''))),
                        'stock_locations': str(row[7].value).strip() if len(row) > 7 and row[7].value else None,
                        'tags': str(row[8].value).strip() if len(row) > 8 and row[8].value else None,
                        'notes': str(row[9].value).strip() if len(row) > 9 and row[9].value else None
                    }
                    products.append(product)
                    print(f"Processed row {row_idx}: {product['item_code']}")  # Debug log
                except Exception as e:
                    error_details.append(f"Row {row_idx}: {str(e)}")
                    print(f"Error processing row {row_idx}: {str(e)}")  # Debug log
                    continue
            
            # Import products
            for product_data in products:
                try:
                    # Validate item_code format
                    if not product_data['item_code'] or len(product_data['item_code']) > 20:
                        error_details.append(f"Invalid item code format: {product_data['item_code']}")
                        continue
                    
                    product = Product.query.filter_by(item_code=product_data['item_code']).first()
                    if product:
                        # Update existing product
                        for key, value in product_data.items():
                            setattr(product, key, value)
                    else:
                        # Create new product
                        product = Product(**product_data)
                        db.session.add(product)
                    
                    db.session.commit()
                    imported_count += 1
                    print(f"Imported product: {product_data['item_code']}")  # Debug log
                except Exception as e:
                    db.session.rollback()
                    error_details.append(f"Error with item code {product_data['item_code']}: {str(e)}")
                    print(f"Error importing product {product_data['item_code']}: {str(e)}")  # Debug log
                    continue
            
            response_data = {
                'success': imported_count > 0,
                'message': f"Successfully imported {imported_count} products.",
                'total_count': total_count,
                'imported_count': imported_count,
                'error_count': len(error_details),
                'error_details': error_details
            }
            print(f"Import completed: {response_data}")  # Debug log
            return jsonify(response_data), 200 if imported_count > 0 else 400
            
        except Exception as e:
            print(f"Error reading Excel file: {str(e)}")  # Debug log
            return jsonify({
                'success': False,
                'error': f"Error reading Excel file: {str(e)}",
                'total_count': total_count,
                'imported_count': imported_count,
                'error_count': len(error_details),
                'error_details': error_details
            }), 400
            
    except Exception as e:
        print(f"Unexpected error: {str(e)}")  # Debug log
        return jsonify({
            'success': False,
            'error': f"Import failed: {str(e)}",
            'details': traceback.format_exc()
        }), 500

@app.route('/products/export')
@login_required
@permission_required('export_products')
def export_products():
    products = Product.query.all()
    
    # Create DataFrame with all fields
    df = pd.DataFrame([{
        'Item Code': p.item_code,
        'Description': p.description,
        'Tamil Name': p.tamil_name,
        'UOM': p.uom,
        'Price': p.price,
        'Stock': p.stock,
        'Restock Level': p.restock_level,
        'Stock Locations': p.stock_locations,
        'Tags': p.tags,
        'Notes': p.notes
    } for p in products])

    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book
    
    # Add formats
    header_format = workbook.add_format({
        'bold': True,
        'text_wrap': True,
        'valign': 'top',
        'bg_color': '#D9D9D9',
        'border': 1
    })
    
    # Write DataFrame to Excel
    df.to_excel(writer, sheet_name='Products', index=False)
    
    # Get the worksheet object
    worksheet = writer.sheets['Products']
    
    # Format the header row
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)
        worksheet.set_column(col_num, col_num, 15)  # Set column width
    
    # Set specific column widths
    worksheet.set_column('B:B', 30)  # Description column
    worksheet.set_column('C:C', 20)  # Tamil Name column
    worksheet.set_column('H:H', 25)  # Stock Locations column
    worksheet.set_column('I:I', 20)  # Tags column
    worksheet.set_column('J:J', 30)  # Notes column
    
    writer.close()
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='products.xlsx'
    )


@app.route('/settings/print-templates')
def print_templates():
    invoice_templates = PrintTemplate.query.filter_by(type='invoice').all()
    summary_templates = PrintTemplate.query.filter_by(type='summary').all()
    return render_template('settings/print_templates.html',
                         invoice_templates=invoice_templates,
                         summary_templates=summary_templates)

@app.route('/settings/print-templates/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_print_template():
    if request.method == 'POST':
        data = request.json
        template = PrintTemplate(
            name=data['name'],
            type=data['type'],
            content=data['content'],
            is_default=data.get('is_default', False)
        )
        
        if template.is_default:
            # Remove default flag from other templates of same type
            PrintTemplate.query.filter_by(type=template.type, is_default=True).update({'is_default': False})
        
        try:
            db.session.add(template)
            db.session.commit()
            return jsonify({'success': True, 'id': template.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    return render_template('print_template_form.html', template=None)

@app.route('/settings/print-templates/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def print_template(id):
    template = PrintTemplate.query.get_or_404(id)
    
    if request.method == 'GET':
        return render_template('print_template_form.html', template=template)
    
    elif request.method == 'PUT':
        data = request.json
        template.name = data['name']
        template.content = data['content']
        template.is_default = data.get('is_default', False)
        
        if template.is_default:
            # Remove default flag from other templates of same type
            PrintTemplate.query.filter(
                PrintTemplate.type == template.type,
                PrintTemplate.id != template.id,
                PrintTemplate.is_default == True
            ).update({'is_default': False})
        
        try:
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        if template.is_default:
            return jsonify({'success': False, 'error': 'Cannot delete default template'})
        
        try:
            db.session.delete(template)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

def get_default_template(type):
    template = PrintTemplate.query.filter_by(type=type, is_default=True).first()
    if not template:
        # Create default template if none exists
        if type == 'invoice':
            with open('templates/print_invoice.html', 'r') as f:
                content = f.read()
        else:
            with open('templates/print_summary.html', 'r') as f:
                content = f.read()
        
        template = PrintTemplate(
            name=f'Default {type.title()} Template',
            type=type,
            content=content,
            is_default=True
        )
        db.session.add(template)
        db.session.commit()
    
    return template

@app.route('/settings')
@login_required
@permission_required('manage_settings')
def settings():
    # Get print templates
    invoice_templates = PrintTemplate.query.filter_by(type='invoice').all()
    summary_templates = PrintTemplate.query.filter_by(type='summary').all()
    settings = Settings.query.first()
    current_wallpaper = url_for('static', filename=f'wallpapers/{settings.wallpaper_path}') if settings and settings.wallpaper_path else None
    
    return render_template('settings.html', 
                         invoice_templates=invoice_templates,
                         summary_templates=summary_templates,
                         current_wallpaper=current_wallpaper)

@app.route('/settings/upload-wallpaper', methods=['POST'])
@login_required
@admin_required
def upload_wallpaper():
    if 'wallpaper' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('settings'))
    
    file = request.files['wallpaper']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('settings'))
    
    if file and file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
        # Create wallpapers directory if it doesn't exist
        wallpapers_dir = os.path.join(app.static_folder, 'wallpapers')
        if not os.path.exists(wallpapers_dir):
            os.makedirs(wallpapers_dir)
        
        # Save the file
        filename = f'wallpaper_{datetime.now().strftime("%Y%m%d_%H%M%S")}{os.path.splitext(file.filename)[1]}'
        file.save(os.path.join(wallpapers_dir, filename))
        
        # Update settings
        settings = Settings.query.first()
        if not settings:
            settings = Settings()
            db.session.add(settings)
        
        # Remove old wallpaper if it exists
        if settings.wallpaper_path:
            old_wallpaper_path = os.path.join(wallpapers_dir, settings.wallpaper_path)
            if os.path.exists(old_wallpaper_path):
                os.remove(old_wallpaper_path)
        
        settings.wallpaper_path = filename
        db.session.commit()
        
        flash('Wallpaper updated successfully', 'success')
    else:
        flash('Invalid file type. Please upload an image file.', 'error')
    
    return redirect(url_for('settings'))

@app.route('/settings/remove-wallpaper', methods=['POST'])
@login_required
@admin_required
def remove_wallpaper():
    settings = Settings.query.first()
    if settings and settings.wallpaper_path:
        # Remove the file
        wallpaper_path = os.path.join(app.static_folder, 'wallpapers', settings.wallpaper_path)
        if os.path.exists(wallpaper_path):
            os.remove(wallpaper_path)
        
        # Clear the path in settings
        settings.wallpaper_path = None
        db.session.commit()
        
        flash('Wallpaper removed successfully', 'success')
    
    return redirect(url_for('settings'))

@app.route('/settings/calculator-code', methods=['GET', 'POST'])
@login_required
@admin_required
def calculator_code():
    if request.method == 'POST':
        try:
            data = request.get_json()
            code = data.get('code')
            if not code:
                return jsonify({'error': 'Code is required'}), 400
                
            settings = Settings.query.first()
            if not settings:
                settings = Settings()
                db.session.add(settings)
            
            settings.calculator_code = code
            print(f"Updating calculator code to: {code}")  # Debug log
            
            try:
                db.session.commit()
                print("Database commit successful")  # Debug log
                return jsonify({'success': True, 'code': settings.calculator_code})
            except Exception as e:
                print(f"Database commit failed: {str(e)}")  # Debug log
                db.session.rollback()
                return jsonify({'error': f'Failed to save code: {str(e)}'}), 500
                
        except Exception as e:
            print(f"Error in calculator code update: {str(e)}")  # Debug log
            return jsonify({'error': str(e)}), 500
    else:
        try:
            settings = Settings.query.first()
            code = settings.calculator_code if settings else '9999'
            print(f"Current calculator code: {code}")  # Debug log
            return jsonify({'code': code})
        except Exception as e:
            print(f"Error retrieving calculator code: {str(e)}")  # Debug log
            return jsonify({'error': str(e)}), 500

@app.route('/settings/backup')
@login_required
@admin_required
def backup_data():
    # Get all data from database
    products = Product.query.all()
    invoices = Invoice.query.all()
    invoice_items = InvoiceItem.query.all()
    templates = PrintTemplate.query.all()
    settings = Settings.query.first()
    
    # Create backup data structure
    backup = {
        'products': [{
            'item_code': p.item_code,
            'description': p.description,
            'uom': p.uom,
            'price': p.price,
            'stock': p.stock,
            'restock_level': p.restock_level,
            'tamil_name': p.tamil_name
        } for p in products],
        'invoices': [{
            'order_number': i.order_number,
            'date': i.date.isoformat(),
            'customer_name': i.customer_name,
            'total_amount': i.total_amount,
            'total_items': i.total_items
        } for i in invoices],
        'invoice_items': [{
            'invoice_order_number': ii.invoice.order_number,
            'product_item_code': ii.product.item_code,
            'quantity': ii.quantity,
            'price': ii.price,
            'amount': ii.amount
        } for ii in invoice_items],
        'templates': [{
            'name': t.name,
            'type': t.type,
            'content': t.content,
            'is_default': t.is_default
        } for t in templates],
        'settings': {
            'calculator_code': settings.calculator_code if settings else '9999',
            'wallpaper_path': settings.wallpaper_path if settings and settings.wallpaper_path else None
        }
    }
    
    return jsonify(backup)

@app.route('/settings/restore', methods=['POST'])
@login_required
@admin_required
def restore_data():
    try:
        data = request.get_json()
        
        # Clear existing data
        PrintTemplate.query.delete()
        InvoiceItem.query.delete()
        Invoice.query.delete()
        Product.query.delete()
        Settings.query.delete()
        
        # Restore products
        for product_data in data.get('products', []):
            product = Product(**product_data)
            db.session.add(product)
        
        # Restore invoices
        for invoice_data in data.get('invoices', []):
            date_str = invoice_data.pop('date')
            invoice_data['date'] = datetime.fromisoformat(date_str).date()
            invoice = Invoice(**invoice_data)
            db.session.add(invoice)
            
            # Restore invoice items
        for item_data in data.get('invoice_items', []):
            invoice = Invoice.query.filter_by(order_number=item_data['invoice_order_number']).first()
            product = Product.query.filter_by(item_code=item_data['product_item_code']).first()
            if invoice and product:
                item = InvoiceItem(
                    invoice=invoice,
                    product=product,
                    quantity=item_data['quantity'],
                    price=item_data['price'],
                    amount=item_data['amount']
                )
                db.session.add(item)
        
        # Restore templates
        for template_data in data.get('templates', []):
            template = PrintTemplate(**template_data)
            db.session.add(template)
        
        # Restore settings
        settings_data = data.get('settings', {})
        settings = Settings(
            calculator_code=settings_data.get('calculator_code', '9999'),
            wallpaper_path=settings_data.get('wallpaper_path')
        )
        db.session.add(settings)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/settings/delete-invoices', methods=['POST'])
@login_required
@admin_required
def delete_invoices():
    try:
        _delete_all_invoices()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/settings/delete-products', methods=['POST'])
@login_required
@admin_required
def delete_products():
    try:
        _delete_all_products()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/settings/delete-all', methods=['POST'])
@login_required
@admin_required
def delete_all():
    try:
        _delete_all_products()  # This also deletes invoices
        PrintTemplate.query.delete()
        CustomerTransaction.query.delete()
        CustomerReceivable.query.delete()
        Customer.query.delete()
        settings = Settings.query.first()
        if settings:
            settings.calculator_code = '9999'
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/settings/print-templates/<int:id>', methods=['DELETE'])
@login_required
@admin_required
def delete_print_template(id):
    template = PrintTemplate.query.get_or_404(id)
    if template.is_default:
        return jsonify({'success': False, 'error': 'Cannot delete default template'})
    
    try:
        db.session.delete(template)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/sales_trend')
def sales_trend():
    try:
        # Get sales data for the last 30 days
        end_date = date.today()
        start_date = end_date - timedelta(days=29)
        
        sales_data = db.session.query(
            func.date(Invoice.date).label('date'),
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= start_date,
            Invoice.date <= end_date
        ).group_by(
            func.date(Invoice.date)
        ).order_by(
            func.date(Invoice.date)
        ).all()
        
        # Create a dictionary of dates and sales
        sales_dict = {row.date.strftime('%Y-%m-%d'): float(row.total) for row in sales_data}
        
        # Fill in missing dates with zero
        labels = []
        values = []
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            labels.append(date_str)
            values.append(sales_dict.get(date_str, 0))
            current_date += timedelta(days=1)
        
        return jsonify({
            'labels': labels,
            'values': values
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/top_products')
def top_products():
    try:
        # Get top 5 selling products
        top_products = db.session.query(
            Product.description,
            func.sum(InvoiceItem.quantity).label('total_quantity')
        ).join(
            InvoiceItem, Product.id == InvoiceItem.product_id
        ).group_by(
            Product.id
        ).order_by(
            func.sum(InvoiceItem.quantity).desc()
        ).limit(5).all()
        
        return jsonify({
            'labels': [p.description for p in top_products],
            'values': [float(p.total_quantity) for p in top_products]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/invoices/delete_all', methods=['DELETE'])
def delete_all_invoices():
    data = request.json
    restore_stock = data.get('restore_stock', False)
    
    try:
        if restore_stock:
            # Restore stock for all items before deleting
            invoices = Invoice.query.all()
            for invoice in invoices:
                for item in invoice.items:
                    item.product.stock += item.quantity
        
        # Delete all invoice items and invoices
        _delete_all_invoices()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/products/import-json', methods=['POST'])
def import_products_json():
    try:
        data = request.json
        if not data or 'products' not in data:
            return jsonify({'success': False, 'error': 'No data provided'})

        products = data['products']
        if not products:
            return jsonify({'success': False, 'error': 'No products found in data'})

        # Process the products
        for product_data in products:
            # Validate required fields
            if not all(key in product_data for key in ['item_code', 'description', 'uom', 'price', 'stock']):
                continue

            try:
                # Convert types and validate
                product_data['price'] = float(product_data['price'])
                product_data['stock'] = int(product_data['stock'])
                
                # Find existing product or create new one
                product = Product.query.filter_by(item_code=product_data['item_code']).first()
                if product:
                    # Update existing product
                    product.description = product_data['description']
                    product.uom = product_data['uom']
                    product.price = product_data['price']
                    product.stock = product_data['stock']
                else:
                    # Create new product
                    product = Product(**product_data)
                    db.session.add(product)
                    
            except (ValueError, TypeError) as e:
                continue  # Skip invalid rows
                
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Successfully imported {len(products)} products'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/invoices/<int:invoice_id>/download')
def download_invoice(invoice_id):
    try:
        # Get invoice data
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get invoice details
        cursor.execute('''
            SELECT i.order_number, i.date, i.customer_name, i.total_amount,
                   ii.product_id, ii.quantity, ii.price, ii.amount,
                   p.name as product_name, p.code as product_code
            FROM invoices i
            JOIN invoice_items ii ON i.id = ii.invoice_id
            JOIN products p ON ii.product_id = p.id
            WHERE i.id = ?
        ''', (invoice_id,))
        
        rows = cursor.fetchall()
        if not rows:
            return 'Invoice not found', 404
            
        # Create invoice data structure
        invoice = {
            'order_number': rows[0][0],
            'date': rows[0][1],
            'customer_name': rows[0][2],
            'total_amount': rows[0][3],
            'items': []
        }
        
        for row in rows:
            invoice['items'].append({
                'product_code': row[9],
                'product_name': row[8],
                'quantity': row[5],
                'price': row[6],
                'amount': row[7]
            })
        
        # Create PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        
        # Add title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30
        )
        elements.append(Paragraph(f"Invoice #{invoice['order_number']}", title_style))
        
        # Add invoice details
        elements.append(Paragraph(f"Date: {invoice['date']}", styles['Normal']))
        elements.append(Paragraph(f"Customer: {invoice['customer_name']}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Create table for items
        data = [['S.No', 'Code', 'Product', 'Quantity', 'Price', 'Total']]
        for idx, item in enumerate(invoice['items'], 1):
            data.append([
                str(idx),
                item['product_code'],
                item['product_name'],
                f"{item['quantity']:.2f}",
                f"₹{item['price']:.2f}",
                f"₹{item['amount']:.2f}"
            ])
        
        # Add total row
        data.append(['', '', '', '', 'Total:', f"₹{invoice['total_amount']:.2f}"])
        
        # Create and style the table
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, -1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOX', (0, 0), (-1, -1), 2, colors.black),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),  # Right align numbers
        ]))
        
        elements.append(table)
        doc.build(elements)
        
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=invoice_{invoice_id}.pdf'
        
        return response
        
    except Exception as e:
        print(f"Error generating PDF: {str(e)}")
        return 'Error generating PDF', 500
    finally:
        if conn:
            conn.close()

@app.route('/products/<int:id>/stock', methods=['POST'])
@login_required
@permission_required('manage_stock')
def update_product_stock(id):
    try:
        product = Product.query.get_or_404(id)
        data = request.json
        change = data.get('change', 0)
        
        # Update stock
        product.stock += change
        db.session.commit()
        
        return jsonify({
            'success': True,
            'new_stock': product.stock
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        totp_token = request.form.get('totp_token')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            if user.totp_enabled:
                if not totp_token:
                    flash('2FA token required')
                    return redirect(url_for('login'))
                
                totp = TOTP(user.totp_secret)
                if not totp.verify(totp_token):
                    flash('Invalid 2FA token')
                    return redirect(url_for('login'))
            
            session['user_id'] = user.id
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.before_request
def require_login():
    # List of routes that don't require login
    public_routes = ['login', 'static']
    
    # Check if the requested endpoint is in public routes
    if request.endpoint and request.endpoint not in public_routes:
        if 'logged_in' not in session:
            return redirect(url_for('login'))

@app.route('/users')
@login_required
@admin_required
def users():
    users_list = User.query.all()
    permissions = Permission.query.all()
    return render_template('users.html', users=users_list, permissions=permissions)

@app.route('/users', methods=['POST'])
@login_required
@permission_required('manage_settings')
def add_user():
    data = request.get_json()
    
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    hashed_password = generate_password_hash(data['password'])
    new_user = User(
        username=data['username'],
        password=hashed_password,
        role=data['role'],
        totp_enabled=data.get('totp_enabled', False)
    )
    
    # Add permissions if not admin
    if data['role'] != 'admin' and 'permissions' in data:
        permissions = Permission.query.filter(Permission.id.in_(data['permissions'])).all()
        new_user.permissions = permissions
    
    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/users/<int:id>', methods=['PUT'])
@login_required
@permission_required('manage_settings')
def update_user(id):
    user = User.query.get_or_404(id)
    data = request.get_json()
    
    if data['username'] != user.username and User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    try:
        user.username = data['username']
        user.role = data['role']
        if data.get('password'):
            user.password = generate_password_hash(data['password'])
        
        # Update permissions if not admin
        if data['role'] != 'admin':
            permissions = Permission.query.filter(Permission.id.in_(data.get('permissions', []))).all()
            user.permissions = permissions
        else:
            user.permissions = []  # Clear permissions for admin as they have all permissions
        
        # Handle 2FA changes
        user.totp_enabled = data.get('totp_enabled', False)
        if user.totp_enabled and 'totp_secret' in data:
            user.totp_secret = data['totp_secret']
        elif not user.totp_enabled:
            user.totp_secret = None
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/users/<int:id>', methods=['DELETE'])
@login_required
@permission_required('manage_settings')
def delete_user(id):
    if id == session.get('user_id'):
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    user = User.query.get_or_404(id)
    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/users/<int:id>/permissions')
@login_required
@permission_required('manage_settings')
def get_user_permissions(id):
    user = User.query.get_or_404(id)
    return jsonify({
        'permissions': [p.id for p in user.permissions]
    })

# Update the permission check in routes
def check_permission(permission_name):
    if 'user_id' not in session:
        return False
    user = User.query.get(session['user_id'])
    return user and user.has_permission(permission_name)

# Add permission check to template context
@app.context_processor
def utility_processor():
    return {
        'check_permission': check_permission
    }

@app.route('/calculator')
def calculator():
    settings = Settings.query.first()
    calculator_code = settings.calculator_code if settings else '9999'
    print(f"Loading calculator page with code: {calculator_code}")  # Debug log
    return render_template('calculator.html', calculator_code=calculator_code)

@app.route('/manifest.json')
def manifest():
    response = send_from_directory('static', 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    return response

@app.route('/sw.js')
def service_worker():
    response = send_from_directory('static', 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/static/icons/<path:filename>')
def serve_icon(filename):
    response = send_from_directory('static/icons', filename)
    if filename.endswith('.png'):
        response.headers['Content-Type'] = 'image/png'
    return response

@app.route('/api/slow_moving_products')
def slow_moving_products():
    try:
        thirty_days_ago = datetime.now() - timedelta(days=30)
        products = Product.query.all()
        slow_moving = []
        
        for product in products:
            last_sale = db.session.query(Invoice.date).join(InvoiceItem).filter(
                InvoiceItem.product_id == product.id
            ).order_by(Invoice.date.desc()).first()
            
            if last_sale:
                days_since_sale = (datetime.now().date() - last_sale[0]).days
            else:
                days_since_sale = 30  # Default for products with no sales
                
            if days_since_sale >= 30:
                slow_moving.append({
                    'name': product.description,
                    'days': days_since_sale
                })
        
        # Sort by days and get top 10
        slow_moving.sort(key=lambda x: x['days'], reverse=True)
        slow_moving = slow_moving[:10]
        
        return jsonify({
            'labels': [item['name'] for item in slow_moving],
            'values': [item['days'] for item in slow_moving]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stock_sales_ratio')
def stock_sales_ratio():
    try:
        # Calculate daily stock-to-sales ratio for the last 30 days
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=29)
        dates = []
        ratios = []
        
        current_date = start_date
        while current_date <= end_date:
            # Get total stock for the day
            total_stock = db.session.query(func.sum(Product.stock)).scalar() or 0
            
            # Get total sales for the day
            daily_sales = db.session.query(func.sum(InvoiceItem.quantity)).join(Invoice).filter(
                func.date(Invoice.date) == current_date
            ).scalar() or 1  # Use 1 to avoid division by zero
            
            ratio = total_stock / daily_sales
            dates.append(current_date.strftime('%Y-%m-%d'))
            ratios.append(round(ratio, 2))
            
            current_date += timedelta(days=1)
        
        return jsonify({
            'labels': dates,
            'values': ratios
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/inventory_aging')
def inventory_aging():
    try:
        products = Product.query.all()
        aging_buckets = {
            '0-30 days': 0,
            '31-60 days': 0,
            '61-90 days': 0,
            '90+ days': 0
        }
        
        for product in products:
            last_sale = db.session.query(Invoice.date).join(InvoiceItem).filter(
                InvoiceItem.product_id == product.id
            ).order_by(Invoice.date.desc()).first()
            
            if last_sale:
                days_since_sale = (datetime.now().date() - last_sale[0]).days
            else:
                days_since_sale = 90  # Default for products with no sales
            
            if days_since_sale <= 30:
                aging_buckets['0-30 days'] += 1
            elif days_since_sale <= 60:
                aging_buckets['31-60 days'] += 1
            elif days_since_sale <= 90:
                aging_buckets['61-90 days'] += 1
            else:
                aging_buckets['90+ days'] += 1
        
        return jsonify({
            'labels': list(aging_buckets.keys()),
            'values': list(aging_buckets.values())
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales_forecast')
def sales_forecast():
    try:
        # Get historical daily sales for the last 90 days
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=89)
        
        daily_sales = db.session.query(
            func.date(Invoice.date).label('date'),
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= start_date,
            Invoice.date <= end_date
        ).group_by(
            func.date(Invoice.date)
        ).order_by(
            func.date(Invoice.date)
        ).all()
        
        # Create a simple moving average forecast
        sales_data = {row.date.strftime('%Y-%m-%d'): float(row.total) for row in daily_sales}
        dates = []
        actual_values = []
        forecast_values = []
        
        # Calculate moving average
        window_size = 7
        moving_avg = []
        
        # Fill historical data
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            dates.append(date_str)
            actual_values.append(sales_data.get(date_str, 0))
            
            # Calculate moving average for the last window_size days
            if len(actual_values) >= window_size:
                avg = sum(actual_values[-window_size:]) / window_size
                moving_avg.append(avg)
            else:
                moving_avg.append(None)
            
            current_date += timedelta(days=1)
        
        # Generate forecast for next 30 days
        last_avg = moving_avg[-1] if moving_avg else 0
        for i in range(30):
            forecast_date = end_date + timedelta(days=i+1)
            dates.append(forecast_date.strftime('%Y-%m-%d'))
            actual_values.append(None)
            forecast_values.append(last_avg)
        
        return jsonify({
            'labels': dates[-30:],  # Show only last 30 days
            'actual_values': actual_values[-30:],
            'forecast_values': forecast_values
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales_performance')
@login_required
def sales_performance():
    try:
        today = datetime.now().date()
        
        # Calculate daily sales
        daily_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            func.date(Invoice.date) == today
        ).scalar() or 0
        
        # Calculate weekly sales (last 7 days)
        week_start = today - timedelta(days=6)
        weekly_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= week_start,
            Invoice.date <= today
        ).scalar() or 0
        
        # Calculate monthly sales
        month_start = today.replace(day=1)
        monthly_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= month_start,
            Invoice.date <= today
        ).scalar() or 0
        
        # Calculate yearly sales
        year_start = today.replace(month=1, day=1)
        yearly_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= year_start,
            Invoice.date <= today
        ).scalar() or 0
        
        return jsonify({
            'daily': round(daily_sales, 2),
            'weekly': round(weekly_sales, 2),
            'monthly': round(monthly_sales, 2),
            'yearly': round(yearly_sales, 2)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales_growth')
@login_required
def sales_growth():
    try:
        today = datetime.now().date()
        
        # Day over Day (DoD) Growth
        yesterday = today - timedelta(days=1)
        today_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            func.date(Invoice.date) == today
        ).scalar() or 0
        
        yesterday_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            func.date(Invoice.date) == yesterday
        ).scalar() or 0
        
        dod_growth = ((today_sales - yesterday_sales) / yesterday_sales * 100) if yesterday_sales > 0 else 0
        
        # Month over Month (MoM) Growth
        current_month = today.replace(day=1)
        last_month = (current_month - timedelta(days=1)).replace(day=1)
        
        current_month_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= current_month,
            Invoice.date <= today
        ).scalar() or 0
        
        last_month_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= last_month,
            Invoice.date < current_month
        ).scalar() or 0
        
        mom_growth = ((current_month_sales - last_month_sales) / last_month_sales * 100) if last_month_sales > 0 else 0
        
        # Year over Year (YoY) Growth
        current_year = today.replace(month=1, day=1)
        last_year = current_year.replace(year=current_year.year-1)
        
        current_year_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= current_year,
            Invoice.date <= today
        ).scalar() or 0
        
        last_year_sales = db.session.query(
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= last_year,
            Invoice.date < current_year
        ).scalar() or 0
        
        yoy_growth = ((current_year_sales - last_year_sales) / last_year_sales * 100) if last_year_sales > 0 else 0
        
        return jsonify({
            'dod_growth': round(dod_growth, 2),
            'mom_growth': round(mom_growth, 2),
            'yoy_growth': round(yoy_growth, 2)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales_trend_by_period')
@login_required
def sales_trend_by_period():
    try:
        period = request.args.get('period', 'daily')  # daily, weekly, monthly, yearly
        end_date = datetime.now().date()
        
        if period == 'daily':
            start_date = end_date - timedelta(days=29)  # Last 30 days
            date_format = '%Y-%m-%d'
            date_trunc = func.date(Invoice.date)
        elif period == 'weekly':
            start_date = end_date - timedelta(weeks=11)  # Last 12 weeks
            date_format = '%Y-W%W'
            date_trunc = func.date_trunc('week', Invoice.date)
        elif period == 'monthly':
            start_date = end_date - timedelta(days=365)  # Last 12 months
            date_format = '%Y-%m'
            date_trunc = func.date_trunc('month', Invoice.date)
        else:  # yearly
            start_date = end_date.replace(year=end_date.year-4)  # Last 5 years
            date_format = '%Y'
            date_trunc = func.date_trunc('year', Invoice.date)
        
        sales_data = db.session.query(
            date_trunc.label('date'),
            func.sum(Invoice.total_amount).label('total')
        ).filter(
            Invoice.date >= start_date,
            Invoice.date <= end_date
        ).group_by(
            date_trunc
        ).order_by(
            date_trunc
        ).all()
        
        return jsonify({
            'labels': [row.date.strftime(date_format) for row in sales_data],
            'values': [float(row.total) for row in sales_data]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/users/generate-2fa', methods=['POST'])
@login_required
@admin_required
def generate_2fa():
    data = request.get_json()
    username = data.get('username')
    if not username:
        return jsonify({'success': False, 'error': 'Username is required'})
    
    # Generate new TOTP secret
    totp_secret = random_base32()
    totp = TOTP(totp_secret)
    
    # Generate TOTP URI for QR code
    totp_uri = f'otpauth://totp/Inventory:{username}?secret={totp_secret}&issuer=Inventory'
    
    return jsonify({
        'success': True,
        'totp_secret': totp_secret,
        'totp_uri': totp_uri
    })

@app.route('/users/<int:id>/generate-2fa', methods=['POST'])
@login_required
@admin_required
def generate_user_2fa(id):
    user = User.query.get_or_404(id)
    data = request.get_json()
    username = data.get('username', user.username)
    
    # Generate new TOTP secret
    totp_secret = random_base32()
    totp = TOTP(totp_secret)
    
    # Generate TOTP URI for QR code
    totp_uri = f'otpauth://totp/Inventory:{username}?secret={totp_secret}&issuer=Inventory'
    
    return jsonify({
        'success': True,
        'totp_secret': totp_secret,
        'totp_uri': totp_uri
    })

@app.route('/invoices/list')
def list_invoices():
    invoices = Invoice.query.order_by(Invoice.date.desc()).all()
    return jsonify({
        'invoices': [
            {
                'id': invoice.id,
                'order_number': invoice.order_number,
                'date': invoice.date.isoformat(),
                'customer_name': invoice.customer_name,
                'total_amount': invoice.total_amount
            } for invoice in invoices
        ]
    })

@app.route('/reports')
@login_required
@permission_required('view_reports')
def reports():
    # Get products that are at or below their restock level
    low_stock_products = Product.query.filter(Product.stock <= Product.restock_level).all()
    
    # Calculate total inventory cost
    total_inventory_cost = sum(product.stock * product.price for product in Product.query.all())
    
    # Calculate stock-out count
    stockout_count = Product.query.filter(Product.stock == 0).count()
    
    # Calculate average stock-to-sales ratio
    products = Product.query.all()
    total_ratio = 0
    products_with_sales = 0
    for product in products:
        total_sales = db.session.query(func.sum(InvoiceItem.quantity)).filter(
            InvoiceItem.product_id == product.id
        ).scalar() or 0
        if total_sales > 0:
            total_ratio += product.stock / total_sales
            products_with_sales += 1
    avg_stock_sales_ratio = total_ratio / products_with_sales if products_with_sales > 0 else 0
    
    # Get slow-moving products count (no sales in last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    slow_moving_count = 0
    for product in products:
        recent_sales = db.session.query(InvoiceItem).join(Invoice).filter(
            InvoiceItem.product_id == product.id,
            Invoice.date >= thirty_days_ago
        ).count()
        if recent_sales == 0:
            slow_moving_count += 1
    
    # Calculate stock-out frequency
    stockout_frequency = []
    for product in products:
        if product.stock == 0:
            # You would need to track stock-out history in a separate table
            # This is a simplified version
            stockout_frequency.append({
                'product_name': product.description,
                'stockout_count': 1,
                'last_stockout': datetime.now().strftime('%Y-%m-%d'),
                'avg_duration': 0,
                'risk_level': 'High',
                'risk_level_color': 'danger'
            })
    
    stats = {
        'total_products': Product.query.count(),
        'total_invoices': Invoice.query.count(),
        'total_sales': db.session.query(db.func.sum(Invoice.total_amount)).scalar() or 0,
        'recent_invoices': Invoice.query.order_by(Invoice.date.desc()).limit(5).all(),
        'low_stock_products': low_stock_products,
        'total_inventory_cost': total_inventory_cost,
        'stockout_count': stockout_count,
        'avg_stock_sales_ratio': avg_stock_sales_ratio,
        'slow_moving_count': slow_moving_count,
        'stockout_frequency': stockout_frequency
    }
    return render_template('reports.html', stats=stats)

@app.route('/customers')
@login_required
@permission_required('view_customers')
def customers():
    customers = Customer.query.all()
    return render_template('customers.html', customers=customers)

@app.route('/customers', methods=['POST'])
@login_required
def add_customer():
    data = request.json
    
    # Server-side validation
    if not data.get('name'):
        return jsonify({'success': False, 'error': 'Name is required'})
    
    customer = Customer(
        name=data['name'],
        phone=data.get('phone'),
        email=data.get('email'),
        address=data.get('address')
    )
    
    try:
        db.session.add(customer)
        db.session.commit()
        return jsonify({'success': True, 'id': customer.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/customers/<int:id>')
@login_required
def customer_detail(id):
    customer = Customer.query.get_or_404(id)
    transactions = CustomerTransaction.query.filter_by(customer_id=id).order_by(CustomerTransaction.date.desc()).all()
    return render_template('customer_detail.html', customer=customer, transactions=transactions)

@app.route('/customers/<int:id>', methods=['PUT', 'DELETE'])
@login_required
def update_customer(id):
    customer = Customer.query.get_or_404(id)
    
    if request.method == 'PUT':
        data = request.json
        
        # Server-side validation
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Name is required'})
        
        try:
            customer.name = data['name']
            customer.phone = data.get('phone')
            customer.email = data.get('email')
            customer.address = data.get('address')
            
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        try:
            # Check if customer has any invoices
            if customer.invoices:
                return jsonify({'success': False, 'error': 'Cannot delete customer with existing invoices'})
            
            # Delete all transactions and receivables
            CustomerTransaction.query.filter_by(customer_id=id).delete()
            CustomerReceivable.query.filter_by(customer_id=id).delete()
            
            # Delete the customer
            db.session.delete(customer)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

@app.route('/customers/payment', methods=['POST'])
@login_required
def add_customer_payment():
    data = request.json
    
    # Server-side validation
    if not all(key in data for key in ('customer_id', 'amount', 'payment_method')):
        return jsonify({'success': False, 'error': 'Missing required fields'})
    
    try:
        amount = float(data['amount'])
        customer_id = int(data['customer_id'])
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid amount or customer ID'})
    
    customer = Customer.query.get_or_404(customer_id)
    
    transaction = CustomerTransaction(
        customer_id=customer_id,
        amount=amount,
        transaction_type='payment',
        payment_method=data['payment_method'],
        reference_number=data.get('reference_number'),
        notes=data.get('notes')
    )
    
    try:
        db.session.add(transaction)
        customer.update_balance()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/customers/<int:id>/link-invoice', methods=['POST'])
@login_required
def link_invoice_to_customer(id):
    try:
        data = request.json
        invoice_id = data.get('invoice_id')
        additional_amount = float(data.get('additional_amount', 0))
        notes = data.get('notes', '')
        
        # Get the invoice and customer
        invoice = Invoice.query.get_or_404(invoice_id)
        customer = Customer.query.get_or_404(id)
        
        # Link the invoice to the customer
        invoice.customer_id = id
        invoice.customer_name = customer.name
        
        # Create a receivable record
        receivable = CustomerReceivable(
            customer_id=id,
            amount=invoice.total_amount,
            notes=notes,
            invoice_id=invoice_id,
            additional_amount=additional_amount
        )
        
        db.session.add(receivable)
        
        # Update customer balance
        customer.update_balance()
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/customers/<int:id>/receivable', methods=['POST'])
@login_required
def add_customer_receivable(id):
    try:
        data = request.json
        amount = float(data.get('amount'))
        notes = data.get('notes')
        
        if not amount or not notes:
            return jsonify({'success': False, 'error': 'Amount and notes are required'})
        
        customer = Customer.query.get_or_404(id)
        
        receivable = CustomerReceivable(
            customer_id=id,
            amount=amount,
            notes=notes
        )
        
        db.session.add(receivable)
        customer.update_balance()
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/customers/transaction/<int:id>', methods=['PUT', 'DELETE'])
@login_required
def manage_transaction(id):
    transaction = CustomerTransaction.query.get_or_404(id)
    
    if request.method == 'PUT':
        data = request.json
        try:
            transaction.amount = float(data['amount'])
            transaction.payment_method = data['payment_method']
            transaction.reference_number = data.get('reference_number')
            transaction.notes = data.get('notes')
            
            # Update customer balance
            transaction.customer.update_balance()
            
            # Update invoice payment status if this transaction affects any invoices
            for invoice in transaction.customer.invoices:
                _update_invoice_status(invoice)
            
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        try:
            # Update customer balance before deleting
            customer = transaction.customer
            db.session.delete(transaction)
            
            # Update customer balance
            customer.update_balance()
            
            # Update invoice payment status for all customer invoices
            for invoice in customer.invoices:
                _update_invoice_status(invoice)
            
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

def _update_invoice_status(invoice):
    """Helper function to update invoice payment status based on payments and receivables"""
    if not invoice.customer:
        return
        
    # Get all customer payments
    total_payments = sum(
        transaction.amount 
        for transaction in invoice.customer.transactions 
        if transaction.transaction_type == 'payment'
    )
    
    # Get all receivables
    total_receivables = sum(
        receivable.amount + receivable.additional_amount 
        for receivable in invoice.customer.receivables
    )
    
    # Calculate total amount due
    total_due = total_receivables
    
    if total_payments >= total_due:
        invoice.payment_status = 'paid'
    elif total_payments > 0:
        invoice.payment_status = 'partial'
    else:
        invoice.payment_status = 'pending'

@app.route('/customers/receivable/<int:id>', methods=['PUT', 'DELETE'])
@login_required
def manage_receivable(id):
    receivable = CustomerReceivable.query.get_or_404(id)
    
    if request.method == 'PUT':
        data = request.json
        try:
            receivable.amount = float(data['amount'])
            receivable.additional_amount = float(data.get('additional_amount', 0))
            receivable.notes = data['notes']
            
            # Update customer balance
            receivable.customer.update_balance()
            
            # Update invoice status
            if receivable.invoice:
                _update_invoice_status(receivable.invoice)
            
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        try:
            # Store reference to customer and invoice before deleting
            customer = receivable.customer
            invoice = receivable.invoice
            
            # If this receivable is linked to an invoice, unlink it
            if invoice:
                invoice.customer_id = None
                invoice.customer_name = None
                invoice.payment_status = 'pending'
            
            # Delete the receivable
            db.session.delete(receivable)
            
            # Update customer balance
            customer.update_balance()
            
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

# Models
class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    products = db.relationship('Product', secondary='supplier_products', backref='suppliers')

# Association table for supplier-product relationship
supplier_products = db.Table('supplier_products',
    db.Column('supplier_id', db.Integer, db.ForeignKey('supplier.id'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True)
)

# Add supplier routes
@app.route('/suppliers')
@login_required
def suppliers():
    suppliers = Supplier.query.all()
    return render_template('suppliers.html', suppliers=suppliers)

@app.route('/suppliers', methods=['POST'])
@login_required
def add_supplier():
    data = request.json
    
    # Server-side validation
    if not data.get('name'):
        return jsonify({'success': False, 'error': 'Name is required'})
    
    supplier = Supplier(
        name=data['name'],
        phone=data.get('phone'),
        email=data.get('email'),
        address=data.get('address')
    )
    
    try:
        db.session.add(supplier)
        db.session.commit()
        return jsonify({'success': True, 'id': supplier.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/suppliers/<int:id>')
@login_required
def supplier_detail(id):
    supplier = Supplier.query.get_or_404(id)
    products = Product.query.all()  # Get all products for linking
    
    # Get sort parameter from request
    sort_by = request.args.get('sort', '')
    
    # Define stock level thresholds
    LOW_STOCK = 10
    MEDIUM_STOCK = 30
    
    if sort_by == 'low_stock':
        supplier.products.sort(key=lambda x: x.stock)
        products.sort(key=lambda x: x.stock)
    elif sort_by == 'medium_stock':
        supplier.products.sort(key=lambda x: abs(x.stock - MEDIUM_STOCK))
        products.sort(key=lambda x: abs(x.stock - MEDIUM_STOCK))
    elif sort_by == 'high_stock':
        supplier.products.sort(key=lambda x: -x.stock)
        products.sort(key=lambda x: -x.stock)
    
    return render_template('supplier_detail.html', 
                         supplier=supplier, 
                         products=products,
                         low_stock=LOW_STOCK,
                         medium_stock=MEDIUM_STOCK)

@app.route('/suppliers/<int:id>', methods=['PUT'])
@login_required
def update_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    data = request.json
    
    # Server-side validation
    if not data.get('name'):
        return jsonify({'success': False, 'error': 'Name is required'})
    
    try:
        supplier.name = data['name']
        supplier.phone = data.get('phone')
        supplier.email = data.get('email')
        supplier.address = data.get('address')
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/suppliers/<int:id>/products', methods=['POST'])
@login_required
def link_supplier_products(id):
    supplier = Supplier.query.get_or_404(id)
    data = request.json
    
    try:
        # Clear existing products
        supplier.products = []
        
        # Add selected products
        for product_id in data.get('product_ids', []):
            product = Product.query.get(product_id)
            if product:
                supplier.products.append(product)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/suppliers/<int:id>', methods=['DELETE'])
@login_required
def delete_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    try:
        db.session.delete(supplier)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/suppliers/<int:id>/products/import', methods=['POST'])
@login_required
def import_supplier_products(id):
    supplier = Supplier.query.get_or_404(id)
    data = request.json
    
    if not data or 'product_codes' not in data:
        return jsonify({'success': False, 'error': 'No product codes provided'})
    
    try:
        # Get all products with matching codes
        products = Product.query.filter(Product.item_code.in_(data['product_codes'])).all()
        
        # Add products to supplier
        for product in products:
            if product not in supplier.products:
                supplier.products.append(product)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully linked {len(products)} products to supplier'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/suppliers/<int:id>/products/export')
@login_required
def export_supplier_products(id):
    supplier = Supplier.query.get_or_404(id)
    
    # Create DataFrame with supplier's products
    df = pd.DataFrame([{
        'Item Code': p.item_code,
        'Description': p.description,
        'Tamil Name': p.tamil_name,
        'UOM': p.uom,
        'Price': p.price,
        'Stock': p.stock,
        'Restock Level': p.restock_level,
        'Stock Locations': p.stock_locations,
        'Tags': p.tags,
        'Notes': p.notes
    } for p in supplier.products])

    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    workbook = writer.book
    
    # Add formats
    header_format = workbook.add_format({
        'bold': True,
        'text_wrap': True,
        'valign': 'top',
        'bg_color': '#D9D9D9',
        'border': 1
    })
    
    # Write DataFrame to Excel
    df.to_excel(writer, sheet_name='Products', index=False)
    
    # Get the worksheet object
    worksheet = writer.sheets['Products']
    
    # Format the header row
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)
        worksheet.set_column(col_num, col_num, 15)  # Set column width
    
    # Set specific column widths
    worksheet.set_column('B:B', 30)  # Description column
    worksheet.set_column('C:C', 20)  # Tamil Name column
    worksheet.set_column('H:H', 25)  # Stock Locations column
    worksheet.set_column('I:I', 20)  # Tags column
    worksheet.set_column('J:J', 30)  # Notes column
    
    writer.close()
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{supplier.name}_products.xlsx'
    )

@app.route('/save_invoice', methods=['POST'])
def save_invoice():
    # ... existing invoice saving code ...
    
    # Change the redirect from /invoices to /new_invoice
    return redirect(url_for('new_invoice'))

# Add this function for database connection
def get_db_connection():
    import psycopg2
    from psycopg2.extras import DictCursor
    return psycopg2.connect(
        os.getenv('DATABASE_URL'),
        cursor_factory=DictCursor
    )

if __name__ == '__main__':
    init_db()  # Initialize database with sample data
    app.run(host='0.0.0.0', port=5000, debug=True)