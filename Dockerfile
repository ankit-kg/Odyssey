FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY odyssey_scraper /app/odyssey_scraper
COPY README.md /app/README.md
COPY supabase /app/supabase

CMD ["python", "-m", "odyssey_scraper", "--run-type", "scheduled"]


