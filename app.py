import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import cloudinary_config

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from limiter_config import limiter  


from routes import piezas, maquinas

app = FastAPI(title="Catálogo Inteligente de Piezas")
@app.get("/")
def root():
    return {"status": "ok"}
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(piezas.router, prefix="/piezas", tags=["Piezas"])
app.include_router(maquinas.router, prefix="/maquinas", tags=["Maquinas"])

