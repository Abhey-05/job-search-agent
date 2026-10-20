"""Production WSGI entrypoint. Run with: gunicorn wsgi:app

Local development should use `python -m app dashboard` instead (Flask's
dev server, with auto-chosen host/port) -- this file is specifically for
the gunicorn start command Render/Railway run in production.
"""
from app.dashboard.server import create_app

app = create_app()
