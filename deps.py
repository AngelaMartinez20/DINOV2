from typing import Generator
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session
from db import get_session_factory
import logging


logger = logging.getLogger("deps")

def get_db_from_header(x_planta: str = Header(...)) -> Generator[Session, None, None]:
    """
    Dependencia actualizada para SQLAlchemy.
    
    1. Recibe el header x-planta.
    2. Pide a db.py la fábrica de sesiones correcta (Norte/Sur).
    3. Crea una sesión y la entrega al endpoint.
    4. Cierra la sesión automáticamente al terminar.
    """
    
    if not x_planta:
        raise HTTPException(
            status_code=400,
            detail="Header x-planta es requerido (Ej: Planta 1)"
        )

    # 1. Intentamos obtener la fábrica correspondiente
    try:
        # get_session_factory en db.py ya normaliza el nombre (p1 -> planta 1, etc.)
        session_factory = get_session_factory(x_planta)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error de configuración de base de datos")

    # 2. Creamos la sesión
    db = session_factory()

    # 3. Entregamos la sesión (Yield)
    try:
        yield db
    except Exception:
        logger.exception("Error en endpoint, haciendo rollback")
        db.rollback()
        raise
    finally:
        # IMPORTANTE: Esto devuelve la conexión al pool de SQLAlchemy
        db.close()