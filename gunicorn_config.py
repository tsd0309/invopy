import multiprocessing
import os

# Gunicorn configuration for production
port = int(os.getenv('PORT', 10000))
bind = f"0.0.0.0:{port}"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"
worker_connections = 1000
timeout = 30
keepalive = 2

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Production settings
preload_app = True
max_requests = 1000
max_requests_jitter = 50 