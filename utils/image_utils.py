from PIL import Image, ImageFile
import io
import os

ImageFile.LOAD_TRUNCATED_IMAGES = True


def procesar_imagen_pieza(
    upload_file,
    output_path: str,
    max_size: int = 768,
    quality: int = 85
):
    # Leer bytes
    data = upload_file.file.read()

    # Abrir con Pillow
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")

    # Redimensionar manteniendo proporción
    img.thumbnail((max_size, max_size))

    # Crear carpetas
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Guardar optimizada
    img.save(
        output_path,
        format="JPEG",
        quality=quality,
        optimize=True
    )

    return {
        "width": img.width,
        "height": img.height,
        "format": "JPEG"
    }
