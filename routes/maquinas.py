import os
import logging
import shutil
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

# Importaciones propias
from deps import get_db_from_header
import models
from security_utils import validar_archivo_real # Asegúrate de que esté en este path

router = APIRouter(tags=["Maquinas"])
logger = logging.getLogger("maquinas")

# Constantes de configuración
STORAGE_BASE = "storage"
MAQUINAS_DIR = "maquinas"

# ==========================================
# UTILIDADES INTERNAS
# ==========================================
def borrar_archivo_fisico(ruta_relativa: str):
    if ruta_relativa:
        abs_path = os.path.join(STORAGE_BASE, ruta_relativa)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except Exception as e:
                logger.error(f"Error al borrar archivo {abs_path}: {e}")

async def procesar_imagen_maquina(clave: str, imagen: UploadFile) -> str:
    """Valida, guarda y retorna la ruta de la imagen."""
    content = await imagen.read()
    
    # 1. Seguridad: Validar que sea una imagen real (mismo método que en Piezas)
    validar_archivo_real(content)
    
    # 2. Preparar directorios
    folder_path = os.path.join(STORAGE_BASE, MAQUINAS_DIR)
    os.makedirs(folder_path, exist_ok=True)
    
    # 3. Guardar archivo (Usamos .jpg por estándar, puedes mejorar esto con PIL)
    filename = f"{MAQUINAS_DIR}/{clave}.jpg"
    full_path = os.path.join(STORAGE_BASE, filename)
    
    with open(full_path, "wb") as f:
        f.write(content)
    
    return filename

# ==========================================
# ENDPOINTS
# ==========================================

@router.post("/")
async def agregar_maquina(
    clave: str = Form(...),
    nombre: str = Form(...),
    descripcion: str = Form(None),
    ubicacion: str = Form(None),
    uso_en: str = Form(None),
    proveedores: str = Form(None),
    imagen: UploadFile | None = File(None),
    db: Session = Depends(get_db_from_header)
):
    clave = clave.strip()
    if len(clave) < 2:
        raise HTTPException(400, "La clave es demasiado corta")

    if db.get(models.Maquina, clave):
        raise HTTPException(400, f"La clave '{clave}' ya está en uso")

    nueva_maquina = models.Maquina(
        clave=clave,
        nombre=nombre.strip(),
        descripcion=descripcion,
        ubicacion=ubicacion,
        uso_en=uso_en,
        proveedores=proveedores,
        tiene_foto=False
    )

    try:
        if imagen and imagen.filename:
            nueva_maquina.imagen = await procesar_imagen_maquina(clave, imagen)
            nueva_maquina.tiene_foto = True

        db.add(nueva_maquina)
        db.commit()
        db.refresh(nueva_maquina)
        
        return {"ok": True, "data": nueva_maquina}
    
    except Exception as e:
        db.rollback()
        # Si falló la DB, borramos la imagen que se alcanzó a subir
        if nueva_maquina.imagen:
            borrar_archivo_fisico(nueva_maquina.imagen)
        raise HTTPException(500, f"Error al guardar: {str(e)}")


@router.get("/")
def listar_maquinas(db: Session = Depends(get_db_from_header)):
    stmt = select(models.Maquina).order_by(models.Maquina.clave)
    maquinas = db.execute(stmt).scalars().all()

    # Formateamos para que el frontend reciba datos consistentes
    return {
        "ok": True,
        "data": [
            {
                "clave": m.clave,
                "nombre": m.nombre,
                "descripcion": m.descripcion,
                "ubicacion": m.ubicacion,
                "uso_en": m.uso_en,
                "proveedores": m.proveedores,
                "tiene_foto": m.tiene_foto, # Booleano puro
                "imagen": f"/static/{m.imagen}" if m.imagen else None
            }
            for m in maquinas
        ]
    }


@router.put("/{maquina_id}")
async def editar_maquina(
    maquina_id: str,
    nombre: str = Form(...),
    descripcion: str = Form(None),
    ubicacion: str = Form(None),
    uso_en: str = Form(None),
    proveedores: str = Form(None),
    imagen: UploadFile | None = File(None),
    db: Session = Depends(get_db_from_header)
):
    maquina = db.get(models.Maquina, maquina_id)
    if not maquina:
        raise HTTPException(404, "Máquina no encontrada")

    maquina.nombre = nombre.strip()
    maquina.descripcion = descripcion
    maquina.ubicacion = ubicacion
    maquina.uso_en = uso_en
    maquina.proveedores = proveedores

    try:
        if imagen and imagen.filename:
            # Reemplazar imagen física
            maquina.imagen = await procesar_imagen_maquina(maquina_id, imagen)
            maquina.tiene_foto = True

        db.commit()
        return {"ok": True, "msg": "Actualizada correctamente"}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error al actualizar: {str(e)}")


@router.delete("/{maquina_id}")
def eliminar_maquina(
    maquina_id: str,
    db: Session = Depends(get_db_from_header)
):
    maquina = db.get(models.Maquina, maquina_id)
    if not maquina:
        raise HTTPException(404, "Máquina no encontrada")

    # 1. Evitar dejar piezas "huérfanas"
    stmt = select(models.Pieza).where(models.Pieza.maquina_id == maquina_id).limit(1)
    if db.execute(stmt).first():
        raise HTTPException(409, "No se puede eliminar: tiene piezas asociadas")

    ruta_imagen = maquina.imagen

    try:
        # 2. Borrar de la DB
        db.delete(maquina)
        db.commit()

        # 3. Borrar archivo físico si la transacción fue exitosa
        borrar_archivo_fisico(ruta_imagen)

        return {"ok": True, "msg": "Máquina y archivos eliminados"}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error al eliminar: {str(e)}")