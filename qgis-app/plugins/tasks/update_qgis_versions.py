from celery import shared_task
from constance import config
from plugins.utils import get_qgis_versions


@shared_task
def update_qgis_versions():
    """
    This background task fetches the QGIS versions from the GitHub QGIS releases
    and then updates the current QGIS version in the database.
    """
    qgis_versions = get_qgis_versions()
    stored_qgis_versions = config.QGIS_VERSIONS.split(',')
    for qgis_version in qgis_versions:
        if qgis_version not in stored_qgis_versions:
            stored_qgis_versions.append(qgis_version)
    stored_qgis_versions = list(filter(None, stored_qgis_versions))
    stored_qgis_versions = [tuple(map(int, v.split('.'))) for v in stored_qgis_versions]
    stored_qgis_versions.sort(reverse=True)
    stored_qgis_versions = ['.'.join(map(str, v)) for v in stored_qgis_versions]

    config.QGIS_VERSIONS = ','.join(stored_qgis_versions)
