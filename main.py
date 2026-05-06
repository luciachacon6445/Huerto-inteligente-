from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
import redis
import psycopg2
import hashlib
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DatosPeticion(BaseModel):
    pregunta: str
    imagen_base64: str

# --- CONFIGURACIÓN INTELIGENTE DE CONEXIONES ---
# Leemos las URLs del archivo .env o usamos unas por defecto
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

# DETECTOR MÁGICO: Si NO existe el archivo "/.dockerenv", significa que estamos en Windows local.
# Entonces, cambiamos los nombres de los contenedores por "localhost" para que no explote.
if not os.path.exists("/.dockerenv"):
    POSTGRES_URL = POSTGRES_URL.replace("@db:", "@localhost:")
    REDIS_URL = REDIS_URL.replace("redis://redis:", "redis://localhost:")

# 1. Conectamos a Redis (Memoria a corto plazo)
conexion_redis = redis.from_url(REDIS_URL, decode_responses=True)

# 2. Conectamos a PostgreSQL (Memoria a largo plazo)
def obtener_conexion_db():
    return psycopg2.connect(POSTGRES_URL)

@app.post("/preguntar/")
def hacer_pregunta(datos: DatosPeticion):
    
    # --- REDIS: BUSCAMOS SI YA EXISTE LA RESPUESTA ---
    id_unico = hashlib.md5(f"{datos.pregunta}{datos.imagen_base64[:50]}".encode()).hexdigest()
    
    try:
        respuesta_guardada = conexion_redis.get(id_unico)
        if respuesta_guardada:
            print("¡Respuesta recuperada desde Redis ultrarrápido!")
            return {"respuesta_ia": respuesta_guardada}
    except Exception as e:
        print(f"Aviso: No se pudo conectar a Redis, continuando sin caché. Error: {e}")

    # --- SI NO EXISTE, LLAMAMOS A LA IA DE NVIDIA ---
    url_nvidia = "https://integrate.api.nvidia.com/v1/chat/completions"
    api_key = os.getenv("NVIDIA_API_KEY")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }

    payload = {
        "model": "meta/llama-4-maverick-17b-128e-instruct",
        "messages": [
            {"role": "system", "content": "Eres un botánico experto, breve y muy amable."},
            {"role": "user", "content": [
                {"type": "text", "text": datos.pregunta},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{datos.imagen_base64}"}}
            ]}
        ],
        "max_tokens": 512,
        "temperature": 0.7,
        "stream": False 
    }

    try:
        respuesta = requests.post(url_nvidia, headers=headers, json=payload)
        respuesta.raise_for_status() 
        mensaje_ia = respuesta.json()["choices"][0]["message"]["content"]
        
        # --- REDIS: GUARDAMOS LA NUEVA RESPUESTA ---
        try:
            conexion_redis.setex(id_unico, 3600, mensaje_ia)
        except:
            pass # Si Redis falla, ignoramos y seguimos
        
        # --- POSTGRESQL: GUARDAMOS EN EL HISTORIAL ---
        # Aseguramos que la imagen nunca viaje como nula
        texto_imagen = "imagen_adjunta" if datos.imagen_base64 else "sin_imagen"

        conexion_db = obtener_conexion_db()
        cursor = conexion_db.cursor()
        
        consulta_sql = """
            INSERT INTO diagnosticos (url_imagen, pregunta_usuario, respuesta_ia) 
            VALUES (%s, %s, %s);
        """
        cursor.execute(consulta_sql, (texto_imagen, datos.pregunta, mensaje_ia))
        conexion_db.commit() 
        
        cursor.close()
        conexion_db.close()
        # ---------------------------------------------

        return {"respuesta_ia": mensaje_ia}
        
    except Exception as e:
        return {"error": f"Hubo un problema: {str(e)}"}