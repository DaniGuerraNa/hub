# El chat web de encargos, en el servidor (decisión 246). Sólo FastAPI, uvicorn,
# bcrypt y python-multipart; la base y los medios viven en /datos (volumen).
FROM python:3.12-slim
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "bcrypt>=4" "python-multipart>=0.0.9"
WORKDIR /app
COPY . /app
ENV DATOS=/datos
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
