"""
Celery task to permanently delete plugins that have been
marked for deletion for more than 30 days.
"""

import datetime

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.utils import timezone
from plugins.models import Plugin

logger = get_task_logger(__name__)


@shared_task
def delete_marked_plugins(days=30):
    """
    Permanently delete plugins marked for deletion more than specified days ago.

    Args:
        days: Number of days to wait before permanent deletion (default: 30)

    Returns:
        dict: Statistics about the deletion operation
    """
    logger.info(f"Starting delete_marked_plugins task (days={days})")

    cutoff_date = timezone.now() - datetime.timedelta(days=days)

    # Find plugins to delete
    plugins_to_delete = Plugin.objects.filter(
        is_deleted=True, deleted_on__lte=cutoff_date
    )

    plugin_count = plugins_to_delete.count()

    deleted_plugins = []

    if plugin_count > 0:
        logger.info(f"Found {plugin_count} plugins to delete")

        # Delete plugins
        for plugin in plugins_to_delete:
            plugin_name = plugin.name
            try:
                plugin.delete()
                deleted_plugins.append(plugin_name)
                logger.info(f"Deleted plugin: {plugin_name}")
            except Exception as e:
                logger.error(f"Error deleting plugin {plugin_name}: {str(e)}")

        logger.info(f"Successfully deleted {len(deleted_plugins)} plugins")
    else:
        logger.info("No plugins to delete")

    return {
        "plugins_deleted": len(deleted_plugins),
        "plugin_names": deleted_plugins,
    }
