from celery import shared_task
from celery.utils.log import get_task_logger
from haystack.management.commands import update_index

logger = get_task_logger(__name__)


@shared_task
def rebuild_search_index():
    """
    Celery task to rebuild the search index.
    """
    update_index.Command().handle()
