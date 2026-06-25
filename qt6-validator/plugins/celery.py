from __future__ import absolute_import

import logging
import os

from celery import Celery

logger = logging.getLogger("plugins")

app = Celery("plugins")

app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "amqp://rabbitmq:5672"),
    result_backend=os.environ.get("CELERY_RESULT_BACKEND", "rpc://"),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
)

app.autodiscover_tasks(["plugins.tasks"])
