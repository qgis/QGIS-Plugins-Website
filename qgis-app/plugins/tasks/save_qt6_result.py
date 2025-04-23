from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from plugins.models import PluginVersion
import re

logger = get_task_logger(__name__)


@shared_task(name="plugins.tasks.save_qt6_result.save_qt6_result")
def save_qt6_result(plugin_version_pk: int, passed: bool, logs: str):
    logger.debug(f"=== save_qt6_result received pk={plugin_version_pk}, passed={passed} ===")

    try:
        plugin_version = PluginVersion.objects.get(pk=plugin_version_pk)
        logger.debug(f"PluginVersion found: {plugin_version}")
    except PluginVersion.DoesNotExist:
        logger.error(f"PluginVersion pk={plugin_version_pk} not found")
        return

    try:
        has_issues = bool(re.search(r"^/[^:]+:\d+:\d+\s+-\s+.+$", logs, re.MULTILINE))

        if not passed:
            status = PluginVersion.Qt6Status.NOT_COMPATIBLE
        elif has_issues:
            status = PluginVersion.Qt6Status.NOT_COMPATIBLE
        else:
            status = PluginVersion.Qt6Status.COMPATIBLE

        plugin_version.qt6_status = status
        plugin_version.qt6_logs = logs
        plugin_version.qt6_checked_on = timezone.now()
        plugin_version.save()
        logger.info(f"=== Save OK for PluginVersion pk={plugin_version.pk}, status={status} ===")
    except Exception as e:
        logger.error(f"Error saving PluginVersion: {e}")