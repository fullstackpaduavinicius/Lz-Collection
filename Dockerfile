


FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/server.py
COPY frontend/ /app/frontend/

RUN mkdir -p /app/data /app/media

ENV PYTHONUNBUFFERED=1
ENV PORT=10000

EXPOSE 10000

CMD ["python", "server.py"]