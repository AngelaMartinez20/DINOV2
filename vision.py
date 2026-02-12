import io
import os
import torch
import numpy as np
import torchvision.transforms as T
import magic
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()


# =============================
# 1. CONFIGURACIÓN DE HARDWARE
# =============================

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# OPTIMIZACIÓN CRÍTICA:
# Usamos float16 (Half Precision) si hay GPU.
# Esto reduce el consumo de memoria del modelo GIANT a la mitad
# y acelera la inferencia sin perder precisión en la búsqueda.
dtype = torch.float16 if device.type == "cuda" else torch.float32

print(f"[*] Cargando DINOv2 GIANT en {device} usando {dtype}...")

# =============================
# 2. CARGA DEL MODELO
# =============================

# Cargar modelo y convertir inmediatamente a la precisión deseada
model = torch.hub.load("facebookresearch/dinov2", "dinov2_vitg14", pretrained=True)
model.to(device)
model.to(dtype) 
model.eval()

# =============================
# 3. TRANSFORMACIONES
# =============================

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
    print("[*] Calentando modelo DINOv2 con entrada dummy...")
    try:
        dummy_input = torch.randn(1, 3, 448, 448).to(device).to(dtype)
        with torch.no_grad():
            model.forward_features(dummy_input)
        print("[✓] Modelo listo y caliente.")
    except Exception as e:
        print(f"[!] Error durante warmup: {e}")

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

    # Iterar por escalas (No podemos mezclar escalas en un mismo tensor batch)
    for scale in SCALES:
        transform = get_transform(scale)
        tensors = [transform(v) for v in vistas]
        batch = torch.stack(tensors).to(device).to(dtype)

        # Inferencia
        out = model.forward_features(batch)

        # Extracción de características
        # shape de out: [Batch_Size, Tokens, Dim]
        cls_token = out["x_norm_clstoken"]
        patch_tokens = out["x_norm_patchtokens"].mean(dim=1)

        # Combinación (Global + Local)
        combined = (cls_token + patch_tokens) / 2
        
        # Desacoplar de la gráfica computacional y mover a CPU
        embeddings_parciales.append(combined.float().cpu())

    # Stack final: Juntamos resultados de todas las escalas y vistas
    # Shape resultante antes de mean: [N_Scales * N_Vistas, 1536]
    all_embs = torch.cat(embeddings_parciales, dim=0)
    
    # Promedio final de todas las variaciones
    final_emb = all_embs.mean(dim=0)
    
    # Normalización L2 (Euclidiana)
    final_emb = final_emb / final_emb.norm(p=2)

    if device.type == "cuda":
        torch.cuda.empty_cache()

    return final_emb.numpy()

# =============================
# 5. UTILIDADES DE ARCHIVO
# =============================

def optimizar_imagen_para_storage(img_pil: Image.Image, size=(800, 800)) -> bytes:
    """
    Reduce y comprime la imagen para guardarla en disco/DB.
    No afecta al embedding (que ya se calculó con la original).
    """
    img_copy = img_pil.copy()
    img_copy.thumbnail(size, Image.LANCZOS) # Lanczos es mejor para reducción visual
    
    buffer = io.BytesIO()
    # Guardar sin metadatos EXIF para ahorrar espacio y evitar rotaciones raras
    img_copy.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()

def procesar_imagen_y_embedding(image_bytes: bytes, roi: tuple | None = None):
    """
    PIPELINE PRINCIPAL:
    1. Lee Bytes -> PIL
    2. Calcula Embedding (usando PIL original máxima calidad)
    3. Optimiza Imagen (para guardar en disco)
    
    Retorna: (bytes_optimizados, embedding_numpy)
    """
    # 1. Cargar PIL una sola vez
    img_pil = Image.open(io.BytesIO(image_bytes))
    img_pil.load() # Forzar lectura en memoria
    
    if img_pil.mode != "RGB":
        img_pil = img_pil.convert("RGB")

    usar_roi = False
    if roi:
        try:
            x_pct, y_pct, w_pct, h_pct = roi
            W, H = img_pil.size

            # ROI viene normalizado (0–1) desde el frontend
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

    # 3. Cálculo de Embeddings Híbrido
    emb_global = extraer_embedding_pil(img_pil)

    if usar_roi:
        print(f"✅ ¡ROI DETECTADO! Aplicando fusión 60/40 en zona: {roi}")  # <--- AGREGA ESTO
        # 
        # Estrategia: "Enfoque guiado". 
        # El ROI define QUÉ es, el Global define DÓNDE está.
        emb_roi = extraer_embedding_pil(img_para_embedding)
        
        # Mezcla ponderada: 60% ROI, 40% Global
        emb = (0.6 * emb_roi) + (0.4 * emb_global)
        
        # Re-normalizar después de la suma vectorial es CRÍTICO
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
    else:
        print("ℹ️ Búsqueda estándar (Imagen completa)") # <--- AGREGA ESTO
        # Si no hay ROI, usamos solo el global
        emb = emb_global

    # 4. Generar imagen para guardar (Siempre guardamos la imagen COMPLETA)
    img_optimizada_bytes = optimizar_imagen_para_storage(img_pil)

    return img_optimizada_bytes, emb

def promedio_embeddings(embeddings: list):
    if not embeddings: return None
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