FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

RUN groupadd --system --gid 10001 family \
    && useradd --system --uid 10001 --gid family --home-dir /app family

COPY --chown=family:family app/ /app/

RUN mkdir -p /app/private_media /app/staticfiles \
    && DJANGO_SECRET_KEY=build-only-secret-key-not-used-at-runtime-00000000000000000000 \
       DJANGO_DEBUG=False \
       DJANGO_ALLOWED_HOSTS=localhost \
       POSTGRES_DB=build \
       POSTGRES_USER=build \
       POSTGRES_PASSWORD=build \
       python manage.py collectstatic --noinput \
    && chown -R family:family /app/private_media /app/staticfiles

USER family

EXPOSE 8000

CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi:application"]
