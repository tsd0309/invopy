import multiprocessing
import os

# Gunicorn configuration
bind = "0.0.0.0:" + os.getenv("PORT", "8000")
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"  # Using gevent for async support
worker_connections = 1000
timeout = 30
keepalive = 2

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# SSL (if needed)
# keyfile = "path/to/keyfile"
# certfile = "path/to/certfile"

# Process naming
proc_name = "inventory_app"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL paths
# ssl_version = "TLS"
# cert_reqs = "CERT_REQUIRED"
# ca_certs = "path/to/ca_certs"

# Max requests and timeout config
max_requests = 1000
max_requests_jitter = 50
graceful_timeout = 30
keep_alive = 5

# Server hooks
def on_starting(server):
    """Called just before the master process is initialized."""
    pass

def on_reload(server):
    """Called before code is reloaded."""
    pass

def when_ready(server):
    """Called just after the server is started."""
    pass

def on_exit(server):
    """Called just before the server exits."""
    pass 