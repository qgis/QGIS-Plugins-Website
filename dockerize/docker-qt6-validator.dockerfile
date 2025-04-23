FROM ghcr.io/qgis/pyqgis4-checker:main-ubuntu

WORKDIR /celery_task

USER root
RUN apt-get update && apt-get install -y celery 

CMD ["celery", "-A", "plugins", "worker", "-Q", "qt6", "--loglevel=DEBUG"]
