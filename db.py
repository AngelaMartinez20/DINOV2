import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


load_dotenv()

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


DB_URLS = {
    "planta 1": os.getenv("DATABASE_URL_PLANTA1"),
    "planta 2": os.getenv("DATABASE_URL_PLANTA2")
}

# ---------- CONFIGURACIÓN DE SQLALCHEMY ----------

# 1. Crear los Engines (Motores)
engines = {}

try:
    for planta, url in DB_URLS.items():
        engines[planta] = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True
        )
    logger.info("Engines de SQLAlchemy inicializados: Planta 1 y Planta 2")

except Exception as e:
    logger.error(f"Error fatal inicializando engines: {e}")

# 2. Crear las Fábricas de Sesiones
SessionFactories = {
    name: sessionmaker(autocommit=False, autoflush=False, bind=engine)
    for name, engine in engines.items()
}

# 3. Clase Base para Modelos (ESTA ES LA QUE TE FALTABA)
class Base(DeclarativeBase):
    pass

# ---------- UTILIDADES ----------

def get_session_factory(planta_nombre: str):
    """
    Retorna la fábrica de sesiones correspondiente a la planta.
    """
    key = planta_nombre.strip().lower()
    
    # Mapeo de alias
    if key in ("planta1", "p1", "norte", "1"): key = "planta 1"
    if key in ("planta2", "p2", "sur", "2"): key = "planta 2"

    factory = SessionFactories.get(key)
    
    if not factory:
        raise ValueError(f"No existe configuración de base de datos para: {planta_nombre}")
    
    return factory