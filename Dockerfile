# Usar una versión ligera de Python
FROM python:3.10-slim

# Crear una carpeta dentro del contenedor
WORKDIR /app

# Copiar la lista de compras y descargar todo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de tu código (main.py, etc.)
COPY . .

EXPOSE 8000

# El comando para encender FastAPI abierto al mundo (0.0.0.0)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]