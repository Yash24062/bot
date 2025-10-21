import os

def ensure_dir(path: str) -> str:
    """Ensure the directory for the given file path exists and return the same path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path
