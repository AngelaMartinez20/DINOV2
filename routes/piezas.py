import os
import logging
import io
import re
import aiofiles
from schemas.piezas import PiezaUpdate
from datetime import datetime
from typing import Optional, List



from fastapi import (
    APIRouter, UploadFile, File, Form,
    Depends, HTTPException, Request
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from limiter_config import limiter 

from PIL import Image
from pillow_heif import register_heif_opener
register_heif_opener()

# Módulos propios
from deps import get_db_from_header
import models
import vision
from security_utils import validar_archivo_real

from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter(tags=["Piezas"])
logger = logging.getLogger("piezas")

# ==========================================
# CONFIGURACIÓN DE SEGURIDAD
# ==========================================

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif"
}

MAX_IMAGE_MB = 5
MAX_BYTES = MAX_IMAGE_MB * 1024 * 1024

# ==========================================
# UTILIDADES INTERNAS
# ==========================================
def nombre_seguro(nombre: str) -> str:
    """
    Permite solo letras, números, guiones y guiones bajos.
    Elimina cualquier otro carácter peligroso.
    """
    return re.sub(r'[^a-zA-Z0-9_-]', '', nombre)

def validar_imagen_real(img_bytes: bytes):
    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            img.verify()
    except Exception:
        raise HTTPException(400, "El archivo no es una imagen válida")
    
async def guardar_imagen(clave: str, campo: str, ts: int, img_bytes: bytes) -> str:
    # Sanitizar entradas
    clave_segura = nombre_seguro(clave)
    campo_seguro = nombre_seguro(campo)

    if not clave_segura:
        raise ValueError("Clave inválida")

    # Construir nombre seguro
    filename = f"{clave_segura}_{campo_seguro}_{ts}.jpg"

    # Definir carpeta segura fija
    carpeta = os.path.join("storage", "piezas")
    
    # Crear carpeta si no existe
    await run_in_threadpool(lambda: os.makedirs(carpeta, exist_ok=True))
    # Ruta final segura
    abs_path = os.path.join(carpeta, filename)

    if os.path.commonpath([abs_path, carpeta]) != carpeta:
        raise ValueError("Intento de path traversal detectado")
    
    async with aiofiles.open(abs_path, "wb") as f:
        await f.write(img_bytes)

    return os.path.join("piezas", filename)


def format_piezas(results):
    """
    Convierte resultados de SQLAlchemy (Pieza, NombreMaquina, Distancia) a JSON.
    """
    return [
        {
            "clave": p.clave,
            "nombre": p.nombre,
            "maquina": m_nombre,
            "imagen": f"/static/{p.imagen}" if p.imagen else None,
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

def registrar_log_busqueda(   db: Session,
    m_id: Optional[str],
    uso: Optional[str],
    clave_top1,
    dist_top1,
    img_path
):
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
        db.rollback()
        logger.error(f"[LOG ERROR] No se pudo guardar log: {e}")

async def _nucleo_busqueda(
    db: Session, 
    imagen: UploadFile, 
    filtro_stmt = None, 
    limite: int = 5,
    meta_log: dict | None = None,
    roi: tuple | None = None
):
    """Lógica centralizada con soporte para pgvector y ROI"""
    limite = max(1, min(limite, 20))

    # 1. Leer y validar imagen
    raw_bytes = await imagen.read()
    await imagen.close()
    
    if len(raw_bytes) > MAX_BYTES:
        raise HTTPException(400, "Imagen demasiado grande")
    
    validar_imagen_real(raw_bytes)

    if not vision.validar_imagen_bytes(raw_bytes):
        raise HTTPException(
        400,
        "La imagen no es válida o está corrupta (HEIC/iPhone)"
    )
    
    # 2. Procesar ROI
    roi_valido = None
    if roi and len(roi) == 4 and all(v is not None for v in roi):
        x, y, w, h = roi
        if w > 0 and h > 0 and w <= 1.0 and h <= 1.0:
            roi_valido = (float(x), float(y), float(w), float(h))

# 3. IA: Generar Embedding
    try:
        img_optimizada, embedding = await run_in_threadpool(
            vision.procesar_imagen_y_embedding,
            raw_bytes,
            roi_valido
        )
    except Exception as e:
        logger.exception(
            f"[IA ERROR] Fallo procesando imagen. Tamaño: {len(raw_bytes)} bytes"
        )
        # 👇 AHORA SÍ, SOLO LANZA ERROR SI FALLA EL TRY
        raise HTTPException(500, "Error interno procesando la imagen")

    # El código continúa aquí si todo salió bien
    dist_attr = models.Pieza.embedding.l2_distance(embedding).label("dist")
    
    stmt = (
        select(models.Pieza, models.Maquina.nombre, dist_attr)
        .join(models.Maquina, models.Pieza.maquina_id == models.Maquina.clave)
    )

    if filtro_stmt is not None:
        stmt = stmt.where(filtro_stmt)

    stmt = stmt.order_by("dist").limit(limite)
    results = db.execute(stmt).all()

    # 5. Logging físico y DB
    if results:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logs/search_{ts}.jpg"
        abs_path = os.path.join("storage", filename)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        with open(abs_path, "wb") as f:
            f.write(img_optimizada)

        registrar_log_busqueda(
            db, meta_log.get("maquina_id"), meta_log.get("uso"),
            results[0][0].clave, results[0][2], filename
        )

    return format_piezas(results)

# ==========================================
# ENDPOINTS
# ==========================================

@router.post("/agregar")
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
    
    # Validar duplicados en la DB seleccionada
    if db.query(models.Pieza).filter(models.Pieza.clave == clave).first():
        raise HTTPException(400, f"La pieza {clave} ya existe en esta planta")

    archivos_procesar = [("imagen", imagen), ("imagen_2", imagen_2), ("imagen_3", imagen_3)]
    embeddings_list = []
    rutas_creadas = [] # Para rollback de archivos
    rutas_db_map = {}

    ts = int(datetime.now().timestamp() * 1000)

    try:
        for campo, archivo in archivos_procesar:
            if not archivo or not hasattr(archivo, "filename") or not archivo.filename:
                continue

            content = await archivo.read()

            # 1️⃣ Validar tipo MIME real (anti spoof)
            validar_archivo_real(content)


            # 2️⃣ Validar que realmente sea imagen
            if not vision.validar_imagen_bytes(content):
                raise HTTPException(
                    status_code=400,
                    detail=f"Imagen {campo} corrupta o formato no soportado"
                )

            # 3️⃣ Procesar embedding en threadpool (CPU heavy)
            img_opt, emb_vector = await run_in_threadpool(
                vision.procesar_imagen_y_embedding,
                content
            )         

            
            filename = f"piezas/{clave}_{campo}_{ts}.jpg"
            abs_path = os.path.join("storage", filename)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            with open(abs_path, "wb") as f:
                f.write(img_opt)

            rutas_creadas.append(abs_path)
            rutas_db_map[campo] = filename
            embeddings_list.append(emb_vector)

        if not embeddings_list:
            raise HTTPException(400, "Debe subir al menos una imagen")

        emb_final = vision.promedio_embeddings(embeddings_list)

        nueva_pieza = models.Pieza(
            clave=clave,
            nombre=nombre.strip(),
            maquina_id=maquina_id,
            embedding=emb_final.tolist(),
            ubicacion=ubicacion,
            uso_en=uso_en,
            proveedores=proveedores,
            tiene_foto=True,
            imagen=rutas_db_map.get("imagen"),
            imagen_2=rutas_db_map.get("imagen_2"),
            imagen_3=rutas_db_map.get("imagen_3")
        )

        db.add(nueva_pieza)
        db.commit()

        return {"ok": True, "clave": clave, "msg": "Pieza guardada exitosamente"}

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Realizando rollback físico por error: {e}")
        for path in rutas_creadas:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
                    
        # Relanzar para que el cliente reciba el error HTTP
        raise HTTPException(500, detail=f"Error procesando la solicitud: {str(e)}")
    
@router.post("/buscar/global")
async def buscar_global(
    imagen: UploadFile = File(...),
    limite: int = Form(5),
    x: float = Form(None), y: float = Form(None), 
    w: float = Form(None), h: float = Form(None),
    db: Session = Depends(get_db_from_header)
):
    res = await _nucleo_busqueda(db, imagen, limite=limite, meta_log={"maquina_id": None, "uso": None}, roi=(x,y,w,h))
    return {"ok": True, "data": res}

@router.post("/buscar/maquina")
async def buscar_maquina(
    maquina_id: str = Form(...),
    imagen: UploadFile = File(...),
    limite: int = Form(5),
    x: float = Form(None), y: float = Form(None), 
    w: float = Form(None), h: float = Form(None),
    db: Session = Depends(get_db_from_header)
):
    filtro = (models.Pieza.maquina_id == maquina_id)
    res = await _nucleo_busqueda(db, imagen, filtro_stmt=filtro, limite=limite, meta_log={"maquina_id": maquina_id}, roi=(x,y,w,h))
    return {"ok": True, "data": res}

@router.get("/maquina/{maquina_id}")
def listar_piezas_maquina(maquina_id: str, db: Session = Depends(get_db_from_header)):
    stmt = (
        select(models.Pieza)
        .where(models.Pieza.maquina_id == maquina_id)
        .order_by(models.Pieza.nombre)
    )

    piezas = db.execute(stmt).scalars().all()

    data = []
    for p in piezas:
        data.append({
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
        })

    return {"ok": True, "data": data}

@router.get("/pieza/{clave}")
def obtener_pieza(clave: str, db: Session = Depends(get_db_from_header)):
    pieza = db.get(models.Pieza, clave)
    if not pieza:
        raise HTTPException(404, "Pieza no encontrada")
    return pieza

@router.delete("/eliminar/{clave}")
def eliminar_pieza(
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
        # 1️⃣ Borrar registro primero
        db.delete(pieza)
        db.commit()

        # 2️⃣ Luego borrar archivos físicos
        for ruta in rutas:
            if ruta:
                abs_path = os.path.join("storage", ruta)
                if os.path.exists(abs_path):
                    os.remove(abs_path)

        return {"ok": True, "msg": "Eliminada correctamente"}

    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error eliminando pieza: {str(e)}")

from fastapi import UploadFile, File, Form
from datetime import datetime

@router.put("/piezas/{clave}")
async def actualizar_pieza(
    clave: str,
    nombre: str = Form(...),
    maquina_id: str = Form(...),
    ubicacion: Optional[str] = Form(None),
    uso_en: Optional[str] = Form(None),
    proveedores: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    imagen_2: Optional[UploadFile] = File(None),
    imagen_3: Optional[UploadFile] = File(None),
    request: Request = None,
    db: Session = Depends(get_db_from_header)
):
    # 1. Buscar pieza
    pieza = db.query(models.Pieza).filter(models.Pieza.clave == clave).first()
    if not pieza:
        raise HTTPException(404, "Pieza no encontrada")

    # 2. Actualizar datos texto
    pieza.nombre = nombre.strip()
    pieza.maquina_id = maquina_id
    pieza.ubicacion = ubicacion
    pieza.uso_en = uso_en
    pieza.proveedores = proveedores
    
    # Auditoría simple
    usuario = request.headers.get("X-User", "sistema")
    # pieza.updated_by = usuario  # Descomentar si tienes este campo en el modelo

    ts = int(datetime.now().timestamp() * 1000)
    
    # Mapeo de campos a archivos recibidos
    inputs_archivos = {
        "imagen": imagen, 
        "imagen_2": imagen_2, 
        "imagen_3": imagen_3
    }

    # Diccionario para guardar los embeddings actuales y nuevos
    # Empezamos cargando los embeddings o calculandolos de lo que ya existe
    # (Para simplificar, recalcularemos todo lo que esté activo para asegurar consistencia)
    
    rutas_finales = {
        "imagen": pieza.imagen,
        "imagen_2": pieza.imagen_2,
        "imagen_3": pieza.imagen_3
    }
    
    embeddings_para_promedio = []
    rutas_a_borrar = [] # Para limpieza de archivos viejos

    try:
        for campo, file_obj in inputs_archivos.items():
            
            # A) Si el usuario subió un archivo nuevo para este campo
            if file_obj and file_obj.filename:
                content = await file_obj.read()
                
                # Validaciones
                validar_archivo_real(content)
                if not vision.validar_imagen_bytes(content):
                    raise HTTPException(400, f"Archivo {campo} corrupto")

                # Procesar IA una sola vez (Obtenemos bytes optimizados Y vector)
                img_opt, emb_vector = await run_in_threadpool(
                    vision.procesar_imagen_y_embedding, 
                    content
                )
                
                # Detectar si había imagen vieja para borrarla luego
                ruta_vieja = getattr(pieza, campo)
                if ruta_vieja:
                    rutas_a_borrar.append(ruta_vieja)

                # Guardar nueva imagen (CON AWAIT)
                nueva_ruta = await guardar_imagen(clave, campo, ts, img_opt)
                
                # Actualizar estado temporal
                rutas_finales[campo] = nueva_ruta
                embeddings_para_promedio.append(emb_vector)
                
            # B) Si NO subió archivo, pero ya existe uno en DB, lo leemos para el embedding
            elif rutas_finales[campo]:
                abs_path = os.path.join("storage", rutas_finales[campo])
                if os.path.exists(abs_path):
                    # Usamos aiofiles para lectura no bloqueante
                    async with aiofiles.open(abs_path, "rb") as f:
                        old_content = await f.read()
                    
                    # Recalculamos embedding de la imagen existente
                    # (Esto es necesario si cambiaste el modelo de IA recientemente, 
                    # si no, podrías cachear el embedding en DB para evitar esto)
                    _, emb_vector = await run_in_threadpool(
                        vision.procesar_imagen_y_embedding, 
                        old_content
                    )
                    embeddings_para_promedio.append(emb_vector)

        # 3. Actualizar rutas en el objeto DB
        pieza.imagen = rutas_finales["imagen"]
        pieza.imagen_2 = rutas_finales["imagen_2"]
        pieza.imagen_3 = rutas_finales["imagen_3"]
        
        if any(rutas_finales.values()):
            pieza.tiene_foto = True
        
        # 4. Calcular y guardar Embedding Promedio
        if embeddings_para_promedio:
            emb_final = vision.promedio_embeddings(embeddings_para_promedio)
            pieza.embedding = emb_final.tolist()
        else:
            # Si borró todas las fotos (caso raro pero posible)
            pieza.embedding = None 
            pieza.tiene_foto = False

        db.commit()
        db.refresh(pieza)

        # 5. Limpieza (Garbage Collection) - Borrar archivos viejos reemplazados
        # Hacemos esto DESPUÉS del commit para asegurar que no borramos si falla la DB
        for ruta_vieja in rutas_a_borrar:
            try:
                abs_path_viejo = os.path.join("storage", ruta_vieja)
                if os.path.exists(abs_path_viejo):
                    os.remove(abs_path_viejo)
            except Exception as e:
                logger.warning(f"No se pudo borrar imagen antigua {ruta_vieja}: {e}")

        return {
            "ok": True, 
            "msg": "Pieza actualizada", 
            "clave": clave
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error actualizando pieza {clave}: {e}")
        raise HTTPException(500, f"Error interno: {str(e)}")