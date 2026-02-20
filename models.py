from datetime import datetime
from typing import List, Optional
from db import Base
from sqlalchemy import Column, Integer, String
from sqlalchemy import String, DateTime, func, Float, ForeignKey, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

# 1. Clase Base indispensable para SQLAlchemy 2.0+
class Bas2e(DeclarativeBase):
    pass

# 2. Modelo de Máquinas
class Maquina(Base):
    __tablename__ = "maquinas"

    clave: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ubicacion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    uso_en: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proveedores: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tiene_foto: Mapped[bool] = mapped_column(Boolean, default=False)
    imagen: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relación: Una máquina tiene muchas piezas
    piezas: Mapped[List["Pieza"]] = relationship("Pieza", back_populates="maquina", cascade="all, delete-orphan")


# 3. Modelo de Piezas (Con integración de pgvector)
class Pieza(Base):
    __tablename__ = "piezas"

    clave: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, index=True)
    maquina_id: Mapped[str] = mapped_column(ForeignKey("maquinas.clave"), nullable=False)
    embedding: Mapped[Vector] = mapped_column(Vector(1536)) 
    ubicacion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    uso_en: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proveedores: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tiene_foto: Mapped[bool] = mapped_column(Boolean, default=False)
    
    imagen: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    imagen_2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    imagen_3: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # 🔒 Auditoría
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    
    maquina: Mapped["Maquina"] = relationship("Maquina", back_populates="piezas")


# 4. Modelo de Logs para auditoría de búsquedas visuales
class LogBusqueda(Base):
    __tablename__ = "logs_busqueda"
    
    clave: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    maquina_id_filtro: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    uso_en_filtro: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resultado_top_1_clave: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    distancia_top_1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    imagen_busqueda_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class HistorialCambios(Base):
    __tablename__ = "historial_cambios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entidad: Mapped[str] = mapped_column(String)  # "pieza" o "maquina"
    entidad_id: Mapped[str] = mapped_column(String)

    campo_modificado: Mapped[str] = mapped_column(String)
    valor_anterior: Mapped[Optional[str]] = mapped_column(Text)
    valor_nuevo: Mapped[Optional[str]] = mapped_column(Text)

    modificado_por: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
