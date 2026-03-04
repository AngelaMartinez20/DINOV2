import io
import os
import logging
import torch
import numpy as np
import torchvision.transforms as T
import magic
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()

EMBEDDING_DIM = 1536


# CONFIGURACIÓN 

logger = logging.getLogger("vision")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
dtype = torch.float16 if device.type == "cuda" else torch.float32

print(f"[*] Cargando DINOv2 GIANT en {device} usando {dtype}...")


# CARGA DEL MODELO

model = None

def get_model():
    global model
    if model is None:
        print("Cargando modelo DINOv2...")
        model = torch.hub.load("facebookresearch/dinov2", "dinov2_vitg14")
        model.eval()
    return model


# 3. TRANSFORMACIONES


SCALES = [448, 560]

def get_transform(size: int):
    """
    Usa BICUBIC para el modelo (estándar en ViT/DINO y más rápido).
    """
    return T.Compose([
        T.Resize((size, size), interpolation=T.InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        ),
    ])


# =============================
# 4. LÓGICA DE VISIÓN
# =============================
def validar_imagen_bytes(image_bytes: bytes) -> bool:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # verifica que sea una imagen real
        return True
    except Exception:
        return False

def center_crop_pil(img: Image.Image, ratio: float = 0.75) -> Image.Image:
    """Realiza un recorte central en la imagen PIL"""
    w, h = img.size
    nw, nh = int(w * ratio), int(h * ratio)
    left = (w - nw) // 2
    top = (h - nh) // 2
    return img.crop((left, top, left + nw, top + nh))

def warmup_model():
    """Ejecuta una inferencia dummy para inicializar buffers del CPU/GPU"""
    logger.info("Calentando modelo DINOv2...")
    try:
        dummy_input = torch.randn(1, 3, 448, 448).to(device).to(dtype)
        with torch.no_grad():
            model.forward_features(dummy_input)
        logger.info("Modelo listo y caliente.")
    except Exception as e:
        logger.exception("Warmup falló")
@torch.no_grad()
def extraer_embedding_pil(img_pil: Image.Image) -> np.ndarray:
    
    img_pil = ImageOps.exif_transpose(img_pil)

    if img_pil.mode != "RGB":
        img_pil = img_pil.convert("RGB")

    # Generar Vistas: Contexto (Global) + Detalle (Zoom Central)
    vistas = [img_pil]
    if min(img_pil.size) > 100:
        vistas.append(center_crop_pil(img_pil, ratio=0.75))

    embeddings_parciales = []

    for scale in SCALES:
        transform = get_transform(scale)
        tensors = [transform(v) for v in vistas]
        batch = torch.stack(tensors).to(device).to(dtype)

        
        out = model.forward_features(batch)

        
        cls_token = out["x_norm_clstoken"]
        patch_tokens = out["x_norm_patchtokens"].mean(dim=1)

        combined = (cls_token + patch_tokens) / 2
        embeddings_parciales.append(combined.float().cpu())


    all_embs = torch.cat(embeddings_parciales, dim=0)
    final_emb = all_embs.mean(dim=0)
    final_emb = final_emb / final_emb.norm(p=2)

    if device.type == "cuda":
        torch.cuda.empty_cache()

    return final_emb.numpy()

# =============================
# 5. UTILIDADES DE ARCHIVO
# =============================

def optimizar_imagen_para_storage(img_pil: Image.Image, size=(800, 800)) -> bytes:
    
    img_copy = img_pil.copy()
    img_copy.thumbnail(size, Image.LANCZOS) # Lanczos es mejor para reducción visual
    
    buffer = io.BytesIO()
    img_copy.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()

def procesar_imagen_y_embedding(image_bytes: bytes, roi: tuple | None = None):
    model = get_model()


    img_pil = Image.open(io.BytesIO(image_bytes))
    img_pil.load() # Forzar lectura en memoria
    
    if img_pil.mode != "RGB":
        img_pil = img_pil.convert("RGB")

    usar_roi = False
    if roi:
        try:
            x_pct, y_pct, w_pct, h_pct = roi
            W, H = img_pil.size

            
            x = int(x_pct * W)
            y = int(y_pct * H)
            w = int(w_pct * W)
            h = int(h_pct * H)

            # 🔒 CLAMP 
            x = max(0, min(x, W - 1))
            y = max(0, min(y, H - 1))
            w = min(w, W - x)
            h = min(h, H - y)

            if w > 10 and h > 10: # Mínimo 10px para evitar ruido
                img_para_embedding = img_pil.crop((x, y, x + w, y + h))
                usar_roi = True
        except Exception as e:
            print(f"[Vision Warning] Error aplicando ROI: {e}")
            img_para_embedding = img_pil
    try:
    # 3. Cálculo de Embeddings Híbrido
        emb_global = extraer_embedding_pil(img_pil)

        if usar_roi:
            logger.info(f"ROI detectado {roi}")
            emb_roi = extraer_embedding_pil(img_para_embedding)
            emb = (0.6 * emb_roi) + (0.4 * emb_global)
        
        # Re-normalizar después de la suma vectorial es CRÍTICO
            norm = np.linalg.norm(emb)
            if norm > 0:
             emb = emb / norm
        else:

            emb = emb_global

    except Exception as e:
        logger.exception("Error durante inferencia DINOv2")
        raise
    
    if not np.isfinite(emb).all():
        raise ValueError("Embedding contiene NaN o Inf")

    img_optimizada_bytes = optimizar_imagen_para_storage(img_pil)

    if device.type == "cuda":
        torch.cuda.empty_cache()

    return img_optimizada_bytes, emb

def promedio_embeddings(embeddings: list):

    if not embeddings: return None

    for e in embeddings:
        if len(e) != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding inválido en promedio: {len(e)}"
            )
        if not np.isfinite(e).all():
            raise ValueError("Embedding con NaN/Inf en promedio")
        
    t = torch.tensor(np.array(embeddings))
    t = t / t.norm(dim=1, keepdim=True)
    mean = t.mean(dim=0)
    mean = mean / mean.norm()
    return mean.numpy()

def process_image_path(path: str):
    """Utilidad para scripts o pruebas locales"""
    with open(path, "rb") as f:
        _, emb = procesar_imagen_y_embedding(f.read())
    return emb

def warmup_model():
    logger.info("Calentando modelo DINOv2...")
    try:
        dummy = torch.randn(1, 3, 448, 448).to(device).to(dtype)
        with torch.no_grad():
            model.forward_features(dummy)
        logger.info("Modelo listo y caliente.")
    except Exception:
        logger.exception("Warmup falló")


try:
    warmup_model()
except Exception:
    logger.exception("Error inicializando warmup")