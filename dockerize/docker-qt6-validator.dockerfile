FROM ghcr.io/qgis/pyqgis4-checker:main-ubuntu

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /celery_task

USER root
RUN apt-get update && apt-get install -y python3-pip && pip3 install celery --break-system-packages

CMD ["celery", "-A", "plugins", "worker", "-Q", "qt6", "--loglevel=DEBUG"]
