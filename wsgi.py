import sys
# Add your project directory to the Python path (adjust if needed)
sys.path.insert(0, '/Users/vishalveera.reddy/Desktop/TechDocGen')  # Replace with the absolute path to your project folder

from main import app as application  # Import the 'app' instance from app.py and rename it to 'application' for Gunicorn

# Optional: Add any production-specific config here, like disabling debug mode
application.debug = False
# wsgi.py
from main import app as application
