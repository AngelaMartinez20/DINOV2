from pydantic import BaseModel
from typing import Optional


class PiezaUpdate(BaseModel):
    nombre: str
    maquina_id: str
    ubicacion: Optional[str] = None
    uso_en: Optional[str] = None
    proveedores: Optional[str] = None
