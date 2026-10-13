# Imagen de un encargo implementado (decisión 244). La pone el hub, no el agente:
# lo que corre en el servidor lo decide la casa. Sólo FastAPI, uvicorn y la
# librería estándar; la base SQLite vive en /datos, que es un volumen.
FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30"
WORKDIR /app
COPY . /app
ENV DATOS=/datos
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
