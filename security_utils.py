import magic
from fastapi import HTTPException

# Mime types permitidos
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif"
}

def validar_archivo_real(file_content: bytes):
    """
    Usa python-magic para detectar el tipo real del archivo
    basado en sus bytes, no en la extensión.
    """
    try:
        # Detectar MIME type real desde el buffer (requiere python-magic)
        mime_real = magic.from_buffer(file_content, mime=True)
        
        if mime_real not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400, 
                detail=f"Tipo de archivo no permitido: {mime_real}. Solo se aceptan imágenes."
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(400, "El archivo está corrupto o no se puede leer.")