import os
import secrets
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# Configuración de Base de Datos SQLite
DATABASE_URL = "sqlite:///./smartbuilding360.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELOS DE LA BASE DE DATOS ---

class UsuarioDB(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    rol = Column(String, default="residente") # residente, conserje, admin
    dpto = Column(String, nullable=False)

class ReciboDB(Base):
    __tablename__ = "recibos"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    mes_periodo = Column(String, nullable=False)
    cuota_ordinaria = Column(Float, default=0.0)
    cuota_extraordinaria = Column(Float, default=0.0)
    fondo_reserva = Column(Float, default=0.0)
    mora = Column(Float, default=0.0)
    monto_total = Column(Float, nullable=False)
    estado = Column(String, default="pendiente") # pendiente, pagado
    fecha_vencimiento = Column(String, nullable=False)
    fecha_pago = Column(DateTime, nullable=True)
    codigo_transaccion = Column(String, nullable=True)

class VisitaDB(Base):
    __tablename__ = "visitas"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nombre_visitante = Column(String, nullable=False)
    dni_visitante = Column(String, nullable=False)
    fecha_visita = Column(String, nullable=False)
    codigo_qr = Column(String, unique=True, index=True)
    estado = Column(String, default="preautorizado") # preautorizado, ingresado, completado
    frecuente = Column(Boolean, default=False)
    fecha_ingreso = Column(DateTime, nullable=True)

class ReservaDB(Base):
    __tablename__ = "reservas"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    area_comun = Column(String, nullable=False)
    fecha_reserva = Column(String, nullable=False)
    horas = Column(Integer, nullable=False)
    costo_alquiler = Column(Float, nullable=False)
    garantia = Column(Float, default=200.0)
    total_pagado = Column(Float, nullable=False)
    estado = Column(String, default="confirmada")
    codigo_transaccion = Column(String, nullable=False)

Base.metadata.create_all(bind=engine)

# --- ESQUEMAS DE PYDANTIC ---

class LoginSchema(BaseModel):
    email: str
    password: str

class SignUpSchema(BaseModel):
    nombre: str
    email: str
    password: str
    dpto: str

class PagoRecibosSchema(BaseModel):
    recibo_ids: List[int]
    metodo_pago: str # Tarjeta, Yape, Plin

class VisitaSchema(BaseModel):
    nombre_visitante: str
    dni_visitante: str
    fecha_visita: str
    frecuente: bool = False

class ReservaSchema(BaseModel):
    area_comun: str
    fecha_reserva: str
    horas: int
    metodo_pago: str

# --- APLICACIÓN Y DEPENDENCIAS ---

app = FastAPI(title="SmartBuilding360 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Almacenamiento en memoria de sesiones de usuario activos
SESSIONS = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_usuario_actual(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in SESSIONS:
        raise HTTPException(status_code=401, detail="Usuario no autenticado. Por favor inicie sesión.")
    user_id = SESSIONS[session_token]
    user = db.query(UsuarioDB).filter(UsuarioDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Sesión inválida.")
    return user

# Poblar datos iniciales si la base de datos está vacía
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    if not db.query(UsuarioDB).first():
        demo_user = UsuarioDB(
            nombre="Juan Pérez",
            email="vecino@smart360.com",
            password="123",
            dpto="Dpto 402",
            rol="residente"
        )
        db.add(demo_user)
        db.commit()
        db.refresh(demo_user)

        # Generar recibos demo
        db.add(ReciboDB(
            usuario_id=demo_user.id, mes_periodo="Octubre 2026", cuota_ordinaria=250.0,
            cuota_extraordinaria=30.0, fondo_reserva=20.0, mora=0.0, monto_total=300.0,
            fecha_vencimiento="2026-10-15"
        ))
        db.add(ReciboDB(
            usuario_id=demo_user.id, mes_periodo="Noviembre 2026", cuota_ordinaria=250.0,
            cuota_extraordinaria=0.0, fondo_reserva=20.0, mora=0.0, monto_total=270.0,
            fecha_vencimiento="2026-11-15"
        ))
        db.commit()
    db.close()

# --- RUTAS DE AUTENTICACIÓN ---

@app.post("/api/login")
def login(data: LoginSchema, response: Response, db: Session = Depends(get_db)):
    user = db.query(UsuarioDB).filter(UsuarioDB.email == data.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="El usuario no existe.")
    if user.password != data.password:
        raise HTTPException(status_code=400, detail="Contraseña incorrecta.")
    
    token = secrets.token_hex(16)
    SESSIONS[token] = user.id
    response.set_cookie(key="session_token", value=token, httponly=True)
    return {"message": "Login exitoso", "nombre": user.nombre, "email": user.email, "dpto": user.dpto}

@app.post("/api/signup")
def signup(data: SignUpSchema, response: Response, db: Session = Depends(get_db)):
    existente = db.query(UsuarioDB).filter(UsuarioDB.email == data.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="El correo electrónico ya está registrado.")
    
    nuevo_usuario = UsuarioDB(
        nombre=data.nombre, email=data.email, password=data.password, dpto=data.dpto
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    token = secrets.token_hex(16)
    SESSIONS[token] = nuevo_usuario.id
    response.set_cookie(key="session_token", value=token, httponly=True)
    return {"message": "Registro exitoso", "nombre": nuevo_usuario.nombre, "email": nuevo_usuario.email, "dpto": nuevo_usuario.dpto}

@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token in SESSIONS:
        del SESSIONS[token]
    response.delete_cookie("session_token")
    return {"message": "Sesión cerrada"}

@app.get("/api/me")
def me(user: UsuarioDB = Depends(get_usuario_actual)):
    return {"nombre": user.nombre, "email": user.email, "dpto": user.dpto, "rol": user.rol}

# --- RUTAS DE RECIBOS Y PAGOS ---

@app.get("/api/recibos")
def obtener_recibos(user: UsuarioDB = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    recibos = db.query(ReciboDB).filter(ReciboDB.usuario_id == user.id).all()
    return recibos

@app.post("/api/recibos/pagar")
def pagar_recibos(payload: PagoRecibosSchema, user: UsuarioDB = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    recibos = db.query(ReciboDB).filter(ReciboDB.id.in_(payload.recibo_ids), ReciboDB.usuario_id == user.id).all()
    if not recibos:
        raise HTTPException(status_code=400, detail="No se encontraron recibos válidos para pagar.")
    
    codigo_tx = f"TX-SB360-{secrets.token_hex(4).upper()}"
    monto_total = 0.0

    for r in recibos:
        r.estado = "pagado"
        r.fecha_pago = datetime.now()
        r.codigo_transaccion = codigo_tx
        monto_total += r.monto_total

    db.commit()
    return {
        "status": "exitoso",
        "mensaje": "Pago procesado y saldo actualizado en tiempo real.",
        "codigo_transaccion": codigo_tx,
        "monto_total": monto_total,
        "metodo_pago": payload.metodo_pago
    }

# --- RUTAS DE VISITAS (CÓDIGOS QR Y CONSERJERÍA) ---

@app.get("/api/visitas")
def listar_visitas(user: UsuarioDB = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    return db.query(VisitaDB).filter(VisitaDB.usuario_id == user.id).all()

@app.post("/api/visitas")
def crear_visita(payload: VisitaSchema, user: UsuarioDB = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    codigo_qr = f"QR-{user.dpto}-{secrets.token_hex(3).upper()}"
    nueva = VisitaDB(
        usuario_id=user.id,
        nombre_visitante=payload.nombre_visitante,
        dni_visitante=payload.dni_visitante,
        fecha_visita=payload.fecha_visita,
        codigo_qr=codigo_qr,
        frecuente=payload.frecuente
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva

@app.post("/api/visitas/escanear/{codigo_qr}")
def escanear_qr(codigo_qr: str, db: Session = Depends(get_db)):
    visita = db.query(VisitaDB).filter(VisitaDB.codigo_qr == codigo_qr).first()
    if not visita:
        raise HTTPException(status_code=404, detail="Código QR inválido o no registrado.")
    
    visita.estado = "ingresado"
    visita.fecha_ingreso = datetime.now()
    db.commit()
    return {"mensaje": "Acceso Autorizado", "visitante": visita.nombre_visitante, "dni": visita.dni_visitante}

# --- RUTAS DE ALQUILER DE ÁREAS COMUNES ---

@app.post("/api/reservas")
def crear_reserva(payload: ReservaSchema, user: UsuarioDB = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    # Cálculo automático: S/ 100 por hora + S/ 200 de garantía
    costo_alquiler = payload.horas * 100.0
    garantia = 200.0
    monto_total = costo_alquiler + garantia
    codigo_tx = f"RES-{secrets.token_hex(4).upper()}"

    nueva = ReservaDB(
        usuario_id=user.id,
        area_comun=payload.area_comun,
        fecha_reserva=payload.fecha_reserva,
        horas=payload.horas,
        costo_alquiler=costo_alquiler,
        garantia=garantia,
        total_pagado=monto_total,
        codigo_transaccion=codigo_tx
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return {
        "status": "confirmada",
        "reserva": nueva,
        "mensaje": "Reserva aprobada e instantáneamente confirmada. Se envió comprobante a su correo."
    }

@app.get("/api/reservas")
def listar_reservas(user: UsuarioDB = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    return db.query(ReservaDB).filter(ReservaDB.usuario_id == user.id).all()
