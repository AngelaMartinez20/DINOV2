import os
import logging
import io
import re
import asyncio
import hashlib
import cloudinary.uploader
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import Header

from fastapi import (
    APIRouter, UploadFile, File, Form,
    Depends, HTTPException, Request, BackgroundTasks
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from slowapi import Limiter
from slowapi.util import get_remote_address
# Asumiendo que configuras el limiter en limiter_config.py
from limiter_config import limiter 

from PIL import Image
from pillow_heif import register_heif_opener
register_heif_opener()

# Módulos propios
from deps import get_db_from_header
from db import get_session_factory
import models
import vision

router = APIRouter(tags=["Piezas"])
logger = logging.getLogger("piezas")

# ==========================================
# CONFIGURACIÓN Y CONSTANTES
# ==========================================

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_IMAGE_MB = 5
MAX_BYTES = MAX_IMAGE_MB * 1024 * 1024
EXPECTED_EMBEDDING_DIM = 1536 # Ajusta esto según el tamaño de tu vector
CLOUDINARY_TIMEOUT = 100000.0 
# ==========================================
# UTILIDADES E INFRAESTRUCTURA
# ==========================================

async def subir_cloudinary(img_bytes: bytes, nombre: str) -> str:
    try:
        result = await asyncio.wait_for(
            run_in_threadpool(
                cloudinary.uploader.upload,
                img_bytes,
                folder="piezas",
                public_id=nombre
            ),
            timeout=CLOUDINARY_TIMEOUT
        )
        return result["secure_url"]
    except asyncio.TimeoutError:
        logger.error(f"Timeout subiendo imagen {nombre} a Cloudinary")
        raise HTTPException(504, "El servicio de imágenes tardó demasiado en responder")

async def borrar_imagen_cloudinary(public_id: str):
    try:
        await asyncio.wait_for(
            run_in_threadpool(cloudinary.uploader.destroy, f"piezas/{public_id}"),
            timeout=500.0
        )
    except Exception as e:
        logger.warning(f"Error borrando imagen antigua {public_id}: {e}")

def limpiar_texto(txt: Optional[str], max_len: int = 255) -> Optional[str]:
    if not txt:
        return None
    txt = txt.strip()
    return txt[:max_len] if txt else None

def obtener_public_id(url: str) -> str:
    return url.split("/")[-1].split(".")[0]

def parsear_roi_seguro(x, y, w, h) -> Optional[tuple]:
    try:
        x, y, w, h = [float(v) if v is not None else None for v in (x, y, w, h)]
        if all(v is not None for v in (x, y, w, h)):
            if 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1:
                return (x, y, w, h)
    except (ValueError, TypeError):
        pass
    return None

def registrar_log_busqueda_bg(planta: str, m_id: Optional[str], uso: Optional[str], clave_top1: str, dist_top1: float, img_path: str):
    """Crea una sesión nueva para la planta correcta en segundo plano."""
    try:
        # Obtenemos la factoría para la planta que hizo la petición
        session_factory = get_session_factory(planta)
        db = session_factory()
    except Exception as e:
        logger.error(f"Error obteniendo BD para background task: {e}")
        return

    try:
        nuevo_log = models.LogBusqueda(
            maquina_id_filtro=m_id,
            uso_en_filtro=uso,
            resultado_top_1_clave=clave_top1,
            distancia_top_1=dist_top1,
            imagen_busqueda_path=img_path
        )
        db.add(nuevo_log)
        db.commit()
    except Exception as e:
        logger.error(f"[LOG ERROR] Background DB: {e}")
    finally:
        db.close() # Siempre devolvemos la conexión al pool

def guardar_log_imagen_fisica(img_bytes: bytes, abs_path: str):
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(img_bytes)
    except Exception as e:
        logger.error(f"Error I/O guardando imagen de log: {e}")

def format_piezas(results):
    return [
        {
            "clave": p.clave,
            "nombre": p.nombre,
            "maquina": m_nombre,
            "imagen": p.imagen if p.imagen else None,
            "distancia": round(float(dist), 4),
            "nivel": ("Alta" if dist < 0.35 else "Media" if dist < 0.55 else "Baja"),
            "detalles": {
                "ubicacion": p.ubicacion,
                "uso_en": p.uso_en,
                "proveedores": p.proveedores,
                "tiene_foto": p.tiene_foto,
                "imagenes_extra": [p.imagen_2, p.imagen_3]
            }
        }
        for p, m_nombre, dist in results
    ]

# ==========================================
# LÓGICA CORE: IMÁGENES E IA
# ==========================================

async def procesar_imagen_segura(archivo: UploadFile) -> bytes:
    if archivo.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"Tipo de archivo no permitido: {archivo.content_type}")

    raw_bytes = await archivo.read(MAX_BYTES + 1)
    await archivo.close()
    
    if len(raw_bytes) > MAX_BYTES:
        raise HTTPException(400, f"Imagen excede el límite de {MAX_IMAGE_MB}MB")

    if not vision.validar_imagen_bytes(raw_bytes):
        raise HTTPException(400, "La imagen no es válida o está corrupta")
        
    return raw_bytes

async def procesar_y_subir_campo(campo: str, archivo: UploadFile, clave: str, ts: int) -> Optional[Dict[str, Any]]:
    if not archivo or not archivo.filename:
        return None

    raw_bytes = await procesar_imagen_segura(archivo)
    img_hash = hashlib.sha256(raw_bytes).hexdigest()

    # Sin límite de tiempo para debugear cuánto tarda realmente
    try:
        img_opt, emb_vector = await run_in_threadpool(vision.procesar_imagen_y_embedding, raw_bytes)
    except Exception as e:
        logger.error(f"Error procesando la imagen con IA: {e}")
        raise HTTPException(500, "Error interno ejecutando el modelo de IA")

    if len(emb_vector) != EXPECTED_EMBEDDING_DIM:
        logger.error(f"Dimensión de vector errónea: {len(emb_vector)} vs {EXPECTED_EMBEDDING_DIM}")
        raise HTTPException(500, "Error crítico de IA: Vector generado con dimensiones incorrectas")

    nombre_img = f"{clave}_{campo}_{ts}"
    nueva_ruta = await subir_cloudinary(img_opt, nombre_img)
    
    return {
        "campo": campo,
        "ruta": nueva_ruta,
        "embedding": emb_vector.tolist(),
        "hash": img_hash
    }

async def _nucleo_busqueda(
    db: Session, 
    imagen: UploadFile, 
    background_tasks: BackgroundTasks,
    planta: str, # <--- AÑADE ESTO AQUÍ
    filtro_stmt = None, 
    limite: int = 5,
    meta_log: dict | None = None,
    roi: tuple | None = None
):
    limite = max(1, min(limite, 20))
    raw_bytes = await procesar_imagen_segura(imagen)
    
    try:
        img_optimizada, embedding = await asyncio.wait_for(
            run_in_threadpool(vision.procesar_imagen_y_embedding, raw_bytes, roi),
            timeout=90.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, "El análisis IA tardó demasiado")
    except Exception as e:
        logger.exception("Fallo procesando imagen de búsqueda")
        raise HTTPException(500, "Error interno procesando la imagen")

    if len(embedding) != EXPECTED_EMBEDDING_DIM:
        raise HTTPException(500, "Vector de búsqueda con dimensiones incorrectas")

    dist_attr = func.least(
        func.coalesce(models.Pieza.embedding.l2_distance(embedding), 999),
        func.coalesce(models.Pieza.embedding_img2.l2_distance(embedding), 999),
        func.coalesce(models.Pieza.embedding_img3.l2_distance(embedding), 999)
    ).label("dist")
    
    stmt = select(models.Pieza, models.Maquina.nombre, dist_attr).join(
        models.Maquina, models.Pieza.maquina_id == models.Maquina.clave
    )

    if filtro_stmt is not None:
        stmt = stmt.where(filtro_stmt)

    stmt = stmt.order_by("dist").limit(limite)
    results = db.execute(stmt).all()

    if results:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logs/search_{ts}.jpg"
        abs_path = os.path.join("storage", filename)
        
        background_tasks.add_task(guardar_log_imagen_fisica, img_optimizada, abs_path)

        safe_meta = meta_log or {}
        background_tasks.add_task(
            registrar_log_busqueda_bg,
            planta,
            safe_meta.get("maquina_id"), 
            safe_meta.get("uso"),
            results[0][0].clave, 
            results[0][2], 
            filename
        )

    return format_piezas(results)

# ==========================================
# ENDPOINTS
# ==========================================

@router.post("/agregar")
@limiter.limit("20/minute")
async def agregar_pieza(
    request: Request,
    clave: str = Form(...),
    nombre: str = Form(...),
    maquina_id: str = Form(...),
    ubicacion: str = Form(None),
    uso_en: str = Form(None),
    proveedores: str = Form(None),
    imagen: UploadFile = File(...),
    imagen_2: UploadFile | None = File(None),
    imagen_3: UploadFile | None = File(None),
    db: Session = Depends(get_db_from_header)
):
    nombre_limpio = limpiar_texto(nombre)
    ubicacion_limpia = limpiar_texto(ubicacion)
    uso_en_limpio = limpiar_texto(uso_en)
    proveedores_limpios = limpiar_texto(proveedores)

    if db.query(models.Pieza).filter(models.Pieza.clave == clave).first():
        raise HTTPException(400, f"La pieza {clave} ya existe en esta planta")

    ts = int(datetime.now().timestamp() * 1000)
    
    resultados = []
    if imagen:
        resultados.append(await procesar_y_subir_campo("imagen", imagen, clave, ts))
    if imagen_2:
        resultados.append(await procesar_y_subir_campo("imagen_2", imagen_2, clave, ts))
    if imagen_3:
        resultados.append(await procesar_y_subir_campo("imagen_3", imagen_3, clave, ts))
    

    datos_img = {
        "imagen": None, "emb_imagen": None,
        "imagen_2": None, "emb_imagen_2": None,
        "imagen_3": None, "emb_imagen_3": None
    }

    for res in resultados:
        if res:
            campo = res["campo"]
            datos_img[campo] = res["ruta"]
            datos_img[f"emb_{campo}"] = res["embedding"]

    try:
        nueva_pieza = models.Pieza(
            clave=clave,
            nombre=nombre_limpio,
            maquina_id=maquina_id,
            ubicacion=ubicacion_limpia,
            uso_en=uso_en_limpio,
            proveedores=proveedores_limpios,
            tiene_foto=any([datos_img["imagen"], datos_img["imagen_2"], datos_img["imagen_3"]]),
            imagen=datos_img["imagen"],
            embedding=datos_img["emb_imagen"],
            imagen_2=datos_img["imagen_2"],
            embedding_img2=datos_img["emb_imagen_2"],
            imagen_3=datos_img["imagen_3"],
            embedding_img3=datos_img["emb_imagen_3"]
        )

        db.add(nueva_pieza)
        db.commit()
        return {"ok": True, "clave": clave, "msg": "Pieza guardada exitosamente"}

    except Exception as e:
        db.rollback()
        logger.error(f"[ERROR] Realizando rollback por error en DB: {e}")
        raise HTTPException(500, detail="Error guardando en la base de datos")

@router.post("/buscar/global")
@limiter.limit("30/minute")
async def buscar_global(
    request: Request,
    background_tasks: BackgroundTasks,
    x_planta: str = Header(...),
    imagen: UploadFile = File(...),
    limite: int = Form(5),
    x: str = Form(None), y: str = Form(None), 
    w: str = Form(None), h: str = Form(None),
    db: Session = Depends(get_db_from_header)
):
    roi = parsear_roi_seguro(x, y, w, h)
    res = await _nucleo_busqueda(
        db, imagen, background_tasks, x_planta, limite=limite, 
        meta_log={"maquina_id": None, "uso": None}, roi=roi
    )
    return {"ok": True, "data": res}

@router.post("/buscar/maquina")
@limiter.limit("30/minute")
async def buscar_maquina(
    request: Request,
    background_tasks: BackgroundTasks,
    x_planta: str = Header(...),
    maquina_id: str = Form(...),
    imagen: UploadFile = File(...),
    limite: int = Form(5),
    x: str = Form(None), y: str = Form(None), 
    w: str = Form(None), h: str = Form(None),
    db: Session = Depends(get_db_from_header)
):
    roi = parsear_roi_seguro(x, y, w, h)
    filtro = (models.Pieza.maquina_id == maquina_id)
    res = await _nucleo_busqueda(
        db, imagen, background_tasks, x_planta, filtro_stmt=filtro, limite=limite, 
        meta_log={"maquina_id": maquina_id}, roi=roi
    )
    return {"ok": True, "data": res}

@router.get("/maquina/{maquina_id}")
@limiter.limit("60/minute")
def listar_piezas_maquina(
    request: Request,
    maquina_id: str, 
    db: Session = Depends(get_db_from_header)
):
    stmt = (
        select(models.Pieza)
        .where(models.Pieza.maquina_id == maquina_id)
        .order_by(models.Pieza.nombre)
    )

    piezas = db.execute(stmt).scalars().all()

    data = [{
        "clave": p.clave,
        "nombre": p.nombre,
        "maquina_id": p.maquina_id,
        "ubicacion": p.ubicacion,
        "uso_en": p.uso_en,
        "proveedores": p.proveedores,
        "tiene_foto": p.tiene_foto,
        "imagen": p.imagen,
        "imagen_2": p.imagen_2,
        "imagen_3": p.imagen_3,
    } for p in piezas]

    return {"ok": True, "data": data}

@router.get("/pieza/{clave}")
@limiter.limit("60/minute")
def obtener_pieza(
    request: Request,
    clave: str, 
    db: Session = Depends(get_db_from_header)
):
    pieza = db.get(models.Pieza, clave)
    if not pieza:
        raise HTTPException(404, "Pieza no encontrada")
    return pieza

@router.delete("/eliminar/{clave}")
@limiter.limit("10/minute")
async def eliminar_pieza(
    request: Request,
    clave: str,
    confirmar_clave: str = Form(...),
    db: Session = Depends(get_db_from_header)
):
    if clave != confirmar_clave:
        raise HTTPException(400, "La clave de confirmación no coincide")
    
    pieza = db.get(models.Pieza, clave)
    if not pieza:
        raise HTTPException(404, "Pieza no encontrada")

    rutas = [pieza.imagen, pieza.imagen_2, pieza.imagen_3]

    try:
        db.delete(pieza)
        db.commit()

        for ruta_vieja in rutas:
            if not ruta_vieja:
                continue
            try:
                public_id = obtener_public_id(ruta_vieja)
                await borrar_imagen_cloudinary(public_id)
            except Exception as e:
                logger.warning(f"No se pudo borrar imagen antigua {ruta_vieja}: {e}")

        return {"ok": True, "msg": "Eliminada correctamente"}

    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error eliminando pieza: {str(e)}")

@router.put("/piezas/{clave}")
@limiter.limit("20/minute")
async def actualizar_pieza(
    clave: str,
    request: Request,
    background_tasks: BackgroundTasks,
    nombre: str = Form(...),
    maquina_id: str = Form(...),
    ubicacion: Optional[str] = Form(None),
    uso_en: Optional[str] = Form(None),
    proveedores: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    imagen_2: Optional[UploadFile] = File(None),
    imagen_3: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db_from_header)
):
    pieza = db.query(models.Pieza).filter(models.Pieza.clave == clave).first()
    if not pieza:
        raise HTTPException(404, "Pieza no encontrada")

    pieza.nombre = limpiar_texto(nombre)
    pieza.maquina_id = maquina_id
    pieza.ubicacion = limpiar_texto(ubicacion)
    pieza.uso_en = limpiar_texto(uso_en)
    pieza.proveedores = limpiar_texto(proveedores)

    ts = int(datetime.now().timestamp() * 1000)
    rutas_a_borrar = []

    tareas = [
        procesar_y_subir_campo("imagen", imagen, clave, ts),
        procesar_y_subir_campo("imagen_2", imagen_2, clave, ts),
        procesar_y_subir_campo("imagen_3", imagen_3, clave, ts)
    ]
    resultados = await asyncio.gather(*tareas)

    try:
        for res in resultados:
            if res:
                campo = res["campo"]
                ruta_vieja = getattr(pieza, campo)
                if ruta_vieja:
                    rutas_a_borrar.append(ruta_vieja)

                setattr(pieza, campo, res["ruta"])
                
                if campo == "imagen":
                    pieza.embedding = res["embedding"]
                elif campo == "imagen_2":
                    pieza.embedding_img2 = res["embedding"]
                elif campo == "imagen_3":
                    pieza.embedding_img3 = res["embedding"]

        pieza.tiene_foto = bool(pieza.imagen or pieza.imagen_2 or pieza.imagen_3)
        db.commit()
        db.refresh(pieza)

        for ruta_vieja in rutas_a_borrar:
            public_id = obtener_public_id(ruta_vieja)
            background_tasks.add_task(borrar_imagen_cloudinary, public_id)

        return {"ok": True, "msg": "Pieza actualizada correctamente", "clave": clave}

    except Exception as e:
        db.rollback()
        logger.error(f"Error actualizando pieza {clave}: {e}")
        raise HTTPException(500, "Error interno actualizando la pieza")