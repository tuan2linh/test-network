
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
COPY tracker.py .
COPY utils/ ./utils/

RUN pip install -r requirements.txt

EXPOSE $PORT

CMD ["python", "tracker.py"]