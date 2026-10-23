FROM python:3.12-slim
WORKDIR /app
COPY server.py /app/
COPY frontend/ /app/frontend/
RUN mkdir -p /app/data /app/media
ENV PORT=8000 PYTHONUNBUFFERED=1 LZ_DATA_DIR=/app/data LZ_MEDIA_DIR=/app/media
EXPOSE 8000
CMD ["python", "server.py"]
