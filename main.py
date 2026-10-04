"""Vercel entrypoint for the "app" service (FastAPI).

Serves /api/* and /reports/*. The React UI is the separate "web" service, so
the API does not serve static files here.
"""

from hala.server import create_app

app = create_app(serve_static=False)
