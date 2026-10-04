import sys
import os

# Vercel: เขียนได้เฉพาะ /tmp — ให้ PyThaiNLP เก็บข้อมูลที่นั่นแทน ~/pythainlp-data
os.environ.setdefault("PYTHAINLP_DATA", "/tmp/pythainlp-data")

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import app
