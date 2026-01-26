FROM python:3.13-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos necesarios
COPY requirements.txt .

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código
COPY . .

# Expone el puerto de Flask
EXPOSE 5001

# Comando por defecto para ejecutar la app
CMD ["python", "app.py"]