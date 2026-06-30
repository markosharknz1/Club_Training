import os, sys

def base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = base_dir()
DB_PATH  = os.path.join(BASE_DIR, 'badminton.db')
