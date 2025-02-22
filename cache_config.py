from flask_caching import Cache
import os
from dotenv import load_dotenv

load_dotenv()

# Configure cache to use simple caching for serverless environment
cache_config = {
    'CACHE_TYPE': 'simple',
    'CACHE_DEFAULT_TIMEOUT': 300
}

cache = Cache(config=cache_config)

# Cache key generators
def make_cache_key_for_product(product_id):
    return f'product_{product_id}'

def make_cache_key_for_products():
    return 'all_products'

def make_cache_key_for_user(user_id):
    return f'user_{user_id}'

def make_cache_key_for_invoice(invoice_id):
    return f'invoice_{invoice_id}'

def make_cache_key_for_customer(customer_id):
    return f'customer_{customer_id}'

# Cache invalidation functions
def invalidate_product_cache(product_id=None):
    if product_id:
        cache.delete(make_cache_key_for_product(product_id))
    cache.delete(make_cache_key_for_products())

def invalidate_user_cache(user_id):
    cache.delete(make_cache_key_for_user(user_id))

def invalidate_invoice_cache(invoice_id):
    cache.delete(make_cache_key_for_invoice(invoice_id))

def invalidate_customer_cache(customer_id):
    cache.delete(make_cache_key_for_customer(customer_id)) 