from pydantic import BaseModel
from typing import Optional

class MaquinaBase(BaseModel):
    nombre: str
    imagen_path: Optional[str] = None
    imagen: Optional[str] = None


class MaquinaCreate(MaquinaBase):
    pass


class MaquinaUpdate(BaseModel):
    nombre: Optional[str]
    imagen_path: Optional[str]
    imagen: Optional[str]


class MaquinaOut(MaquinaBase):
    id: int
    planta_id: int
