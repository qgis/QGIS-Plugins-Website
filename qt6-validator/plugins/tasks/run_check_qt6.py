import os
import shutil
import subprocess
import tempfile
import zipfile

from celery.utils.log import get_task_logger
from plugins.celery import app

app.config_from_object("plugins.celery")

logger = get_task_logger(__name__)


@app.task(name="plugins.tasks.run_check_qt6.run_qgis_script")
def run_qgis_script(plugin_version_pk: int, package_path: str):
    logger.debug(
        f"=== run_qgis_script started pk={plugin_version_pk}, path={package_path} ==="
    )

    if not os.path.exists(package_path):
        logger.error(f"Zip file not found : {package_path}")
        app.send_task(
            "plugins.tasks.save_qt6_result.save_qt6_result",
            args=[plugin_version_pk, False, f"Package not found : {package_path}"],
        )
        return

    tmp_dir = tempfile.mkdtemp()
    logs = ""
    passed = False

    try:
        with zipfile.ZipFile(package_path, "r") as zip_ref:
            zip_ref.extractall(tmp_dir)
        logger.debug(f"Zip extract in {tmp_dir}")

        command = ["/usr/local/bin/pyqt5_to_pyqt6.py", tmp_dir, "--dry_run"]
        logger.debug(f"Command : {' '.join(command)}")

        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logs = result.stdout.decode() + result.stderr.decode()
        passed = result.returncode == 0

        logger.debug(f"Return code : {result.returncode}")
        logger.debug(f"Logs :\n{logs}")
        logger.debug(f"Résultat : {'PASSED' if passed else 'FAILED'}")

    except Exception as e:
        logs = str(e)
        passed = False
        logger.exception(f"Error during the check : {e}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Returns the result to the main Django worker
    logger.debug(f"Send the result to the main worker for pk={plugin_version_pk}")
    app.send_task(
        "plugins.tasks.save_qt6_result.save_qt6_result",
        args=[plugin_version_pk, passed, logs],
    )
