from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from plugins.models import PluginVersion

logger = get_task_logger(__name__)


@shared_task(name="plugins.tasks.save_qt6_result.save_qt6_result")
def save_qt6_result(plugin_version_pk: int, passed: bool, logs: str):
    logger.info(f"=== save_qt6_result reçu pk={plugin_version_pk}, passed={passed} ===")

    try:
        plugin_version = PluginVersion.objects.get(pk=plugin_version_pk)
        logger.info(f"PluginVersion not found : {plugin_version}")
    except PluginVersion.DoesNotExist:
        logger.error(f"PluginVersion pk={plugin_version_pk} not found")
        return

    try:
        plugin = plugin_version.plugin
        has_issues = any(
            " - " in line or (": " in line and not line.startswith("==="))
            for line in logs.splitlines()
            if line.strip() and not line.startswith("===")
        )
        plugin_version.qt6_passed = passed
        plugin_version.qt6_logs = logs
        plugin_version.qt6_checked_on = timezone.now()
        plugin_version.qt6_compatible = passed and not has_issues
        plugin_version.save()
        logger.info(
            f"===Logs Qt6 successfully save done on Plugin pk={plugin.pk} ({plugin.name}) ==="
        )
    except Exception as e:
        logger.error(f"Error during save Qt6 logs on {plugin.name} : {e}")
