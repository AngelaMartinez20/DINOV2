# app.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# --- IMPORTS DE SEGURIDAD (RATE LIMIT) ---
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from limiter_config import limiter  # <--- Importamos la configuración compartida

# --- TUS RUTAS ---
from routes import piezas, maquinas

app = FastAPI(title="Catálogo Inteligente de Piezas")

# 1. Configurar Rate Limiter en la App Global
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 2. Middleware CORS (Permisivo para desarrollo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Routers
# Nota: Asegúrate de que en routes/piezas.py estés usando el limiter
app.include_router(piezas.router, prefix="/piezas", tags=["Piezas"])
app.include_router(maquinas.router, prefix="/maquinas", tags=["Maquinas"])

# 4. Archivos Estáticos
app.mount("/static", StaticFiles(directory="storage"), name="static")