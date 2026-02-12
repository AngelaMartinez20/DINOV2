# utils/storage.py
import os
from fastapi import UploadFile

BASE_PATH = "storage"

def save_image(path: str, file: UploadFile):
    full_path = os.path.join(BASE_PATH, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "wb") as f:
        for chunk in file.file:
            f.write(chunk)
