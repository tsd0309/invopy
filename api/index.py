from app import app

# Vercel serverless function handler
def handler(request, context):
    return app 