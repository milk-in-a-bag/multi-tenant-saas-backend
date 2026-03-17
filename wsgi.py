# Vercel entrypoint — delegates to the actual WSGI app
from config.wsgi import application

app = application
