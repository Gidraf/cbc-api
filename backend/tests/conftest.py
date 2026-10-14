import os

from cryptography.fernet import Fernet

# app.state refuses to import without a master key; tests get a throwaway one.
os.environ.setdefault("CBC_MASTER_KEY", Fernet.generate_key().decode())
