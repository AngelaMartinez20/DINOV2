from typing import Generator
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session
from db import get_session_factory
import logging


logger = logging.getLogger("deps")

def get_db_from_header(x_planta: str = Header(...)) -> Generator[Session, None, None]:
    
    if not x_planta:
        raise HTTPException(
            status_code=400,
            detail="Header x-planta es requerido"
        )

    try:
        session_factory = get_session_factory(x_planta)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error de configuración de base de datos")

    db = session_factory()

    try:
        yield db
    except Exception:
        logger.exception("Error en endpoint, haciendo rollback")
        db.rollback()
        raise
    finally:
        db.close()
