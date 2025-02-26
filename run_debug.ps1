$env:PYTHON_VERSION = "3.11.0"
$env:DATABASE_URL = "postgresql://neondb_owner:npg_SKJP7uqa6tlb@ep-shiny-fire-a997p03r-pooler.gwc.azure.neon.tech/neondb?sslmode=require"
$env:SQLALCHEMY_DATABASE_URI = "postgresql://neondb_owner:npg_SKJP7uqa6tlb@ep-shiny-fire-a997p03r-pooler.gwc.azure.neon.tech/neondb?sslmode=require"
$env:FLASK_ENV = "development"
$env:FLASK_DEBUG = "1"

Write-Host "Starting Flask application in debug mode..."
.\venv\Scripts\activate
flask db upgrade
flask run --host=0.0.0.0 --port=8000 