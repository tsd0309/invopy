$env:PYTHON_VERSION = "3.11.0"
$env:DATABASE_URL = "postgresql://neondb_owner:npg_SKJP7uqa6tlb@ep-shiny-fire-a997p03r-pooler.gwc.azure.neon.tech/neondb?sslmode=require"
$env:SQLALCHEMY_DATABASE_URI = "postgresql://neondb_owner:npg_SKJP7uqa6tlb@ep-shiny-fire-a997p03r-pooler.gwc.azure.neon.tech/neondb?sslmode=require"
$env:PORT = "8000"

Write-Host "Starting Flask application..."
.\venv\Scripts\activate
flask db upgrade
gunicorn -c gunicorn_config.py app:app 