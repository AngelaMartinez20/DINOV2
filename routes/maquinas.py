import os
import logging
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

# Importaciones propias
from deps import get_db_from_header
import models

router = APIRouter(tags=["Maquinas"])
logger = logging.getLogger("maquinas")


# -----------------------------
# Agregar máquina
# -----------------------------
@router.post("/")
async def agregar_maquina(
    clave: str = Form(...),
    nombre: str = Form(...),
    descripcion: str = Form(None),
    ubicacion: str = Form(None),
    uso_en: str = Form(None),
    proveedores: str = Form(None),
    imagen: UploadFile | None = File(None),
    db: Session = Depends(get_db_from_header) # <--- Inyección de Session
):
    clave = clave.strip()
    if len(clave) < 2:
        raise HTTPException(400, "La clave es demasiado corta")

    logger.info(f"Agregando máquina con clave: {clave}")

    # 1. Verificar si existe (Usando ORM)
    # db.get busca por Primary Key automáticamente
    if db.get(models.Maquina, clave):
        raise HTTPException(400, f"La clave '{clave}' ya está en uso")

    # 2. Crear el objeto
    nueva_maquina = models.Maquina(
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        ubicacion=ubicacion,
        uso_en=uso_en,
        proveedores=proveedores,
        tiene_foto=bool(imagen)
    )

    # 3. Guardar imagen si existe
    if imagen and imagen.filename:
        os.makedirs("storage/maquinas", exist_ok=True)
        filename = f"maquinas/{clave}.jpg"
        full_path = f"storage/{filename}"

        content = await imagen.read()
        await imagen.close()

        with open(full_path, "wb") as f:
            f.write(content)
        
        # Asignamos la ruta al objeto
        nueva_maquina.imagen = filename

    # 4. Guardar en DB
    db.add(nueva_maquina)
    db.commit()      # Confirmamos la transacción
    db.refresh(nueva_maquina) # Recargamos para tener los datos frescos

    return {
        "ok": True,
        "data": {
            "clave": nueva_maquina.clave,
            "nombre": nueva_maquina.nombre,
            "tiene_foto": nueva_maquina.tiene_foto,
            "imagen": f"/static/{nueva_maquina.imagen}" if nueva_maquina.imagen else None
        }
    }


# -----------------------------
# Listar máquinas
# -----------------------------
@router.get("/")
def listar_maquinas(db: Session = Depends(get_db_from_header)):
    # SELECT * FROM maquinas ORDER BY clave
    stmt = select(models.Maquina).order_by(models.Maquina.clave)
    maquinas = db.execute(stmt).scalars().all()

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
                "foto": "SÍ" if m.tiene_foto else "NO",
                "imagen": f"/static/{m.imagen}" if m.imagen else None
            }
            for m in maquinas
        ]
    }

# -----------------------------
# Editar máquina
# -----------------------------
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
    # 1. Buscar la máquina
    maquina = db.get(models.Maquina, maquina_id)
    if not maquina:
        raise HTTPException(404, "Máquina no encontrada")

    # 2. Actualizar campos
    maquina.nombre = nombre
    maquina.descripcion = descripcion
    maquina.ubicacion = ubicacion
    maquina.uso_en = uso_en
    maquina.proveedores = proveedores

    # 3. Actualizar imagen si se envía una nueva
    if imagen and imagen.filename:
        os.makedirs("storage/maquinas", exist_ok=True)
        filename = f"maquinas/{maquina_id}.jpg"
        full_path = f"storage/{filename}"

        content = await imagen.read()
        await imagen.close()

        with open(full_path, "wb") as f:
            f.write(content)

        maquina.imagen = filename
        maquina.tiene_foto = True

    # 4. Guardar cambios
    db.commit() # SQLAlchemy detecta qué campos cambiaron y hace el UPDATE solo

    return {"ok": True, "msg": "Máquina actualizada correctamente"}


# -----------------------------
# Eliminar máquina
# -----------------------------
@router.delete("/{maquina_id}")
def eliminar_maquina(
    maquina_id: str,
    db: Session = Depends(get_db_from_header)
):
    # 1. Buscar la máquina
    maquina = db.get(models.Maquina, maquina_id)
    if not maquina:
        raise HTTPException(404, "Máquina no encontrada")

    # 2. Verificar piezas asociadas (Usando ORM)
    # Contamos cuántas piezas tienen este maquina_id
    stmt = select(models.Pieza).where(models.Pieza.maquina_id == maquina_id).limit(1)
    if db.execute(stmt).first():
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar la máquina porque tiene piezas asociadas"
        )

    # 3. Eliminar
    db.delete(maquina)
    db.commit()

    return {"ok": True, "msg": "Máquina eliminada"}