import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    # This function is now deprecated and will be replaced by SQLAlchemy's engine.
    # We will keep it for now to avoid breaking the app during the refactoring.
    pass