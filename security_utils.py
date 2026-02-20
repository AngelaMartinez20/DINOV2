import magic
import logging
from fastapi import HTTPException


logger = logging.getLogger(__name__)

# Mime types permitidos
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/jpg",
    "image/webp",
    "image/heic",
    "image/heif"
}

def validar_archivo_real(file_content: bytes):
    try:
        mime_real = magic.from_buffer(file_content, mime=True)
        logger.debug(f"MIME detectado: {mime_real}")


        # Aceptar cualquier tipo image/*
        if not mime_real.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de archivo no permitido: {mime_real}. Solo se aceptan imágenes."
            )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="El archivo está corrupto o no se puede leer."
        )
