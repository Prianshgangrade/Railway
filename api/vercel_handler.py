from index import app

# This exposes your Flask app to Vercel
# DO NOT run app.run() — Vercel will handle requests
def handler(request, context):
    return app(request.environ, lambda status, headers: None)
