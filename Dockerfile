FROM python:3.11-slim

# Usar la carpeta /app dentro del contenedor (estándar)
WORKDIR /app

# Copiar TODO lo que está en la carpeta "api" del PC
COPY . .

# Instalar librerías
RUN pip install --no-cache-dir -r requirements.txt

# Exponer puerto
EXPOSE 8000

# Ejecutar: busca app.py → módulo "app"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]