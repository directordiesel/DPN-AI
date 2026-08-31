FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng libsndfile1 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/dpn-ai
COPY requirements.txt requirements-voice.txt ./
RUN python -m pip install --no-cache-dir -r requirements-voice.txt
COPY . .
RUN mkdir -p data workspace/generated workspace/uploads plugins skills

EXPOSE 8787
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]