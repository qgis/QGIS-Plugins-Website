from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from plugins.models import PluginVersion

logger = get_task_logger(__name__)


@shared_task(name="plugins.tasks.save_deprecated_result.save_deprecated_result")
def save_deprecated_result(plugin_version_pk: int, passed: bool, logs: str):
    logger.debug(
        f"=== save_deprecated_result received pk={plugin_version_pk}, passed={passed} ==="
    )

    try:
        plugin_version = PluginVersion.objects.get(pk=plugin_version_pk)
        logger.debug(f"PluginVersion found: {plugin_version}")
    except PluginVersion.DoesNotExist:
        logger.error(f"PluginVersion pk={plugin_version_pk} not found")
        return

    try:
        if not passed:
            status = PluginVersion.DeprecatedStatus.NOT_RUN
        elif logs and logs != "[]":
            status = PluginVersion.DeprecatedStatus.HAS_DEPRECATED
        else:
            status = PluginVersion.DeprecatedStatus.NO_DEPRECATED

        plugin_version.deprecated_status = status
        plugin_version.deprecated_logs = logs
        plugin_version.deprecated_checked_on = timezone.now()
        plugin_version.save(
            update_fields=[
                "deprecated_status",
                "deprecated_logs",
                "deprecated_checked_on",
            ]
        )
        logger.info(
            f"=== Save OK for PluginVersion pk={plugin_version.pk}, status={status} ==="
        )
    except Exception as e:
        logger.error(f"Error saving PluginVersion: {e}")
