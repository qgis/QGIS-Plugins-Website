import json
import os
import shutil
import subprocess
import tempfile
import zipfile

from celery.utils.log import get_task_logger
from plugins.celery import app

logger = get_task_logger(__name__)

PYPROJECT_CONTENT = """[tool.pyright]
reportDeprecated = true
extraPaths = ["/usr/share/qgis/python"]
"""


@app.task(name="plugins.tasks.run_check_deprecated.run_check_deprecated")
def run_check_deprecated(plugin_version_pk: int, package_path: str):
    logger.info(
        f"=== run_check_deprecated started pk={plugin_version_pk}, path={package_path} ==="
    )

    if not os.path.exists(package_path):
        logger.error(f"Zip not found: {package_path}")
        app.send_task(
            "plugins.tasks.save_deprecated_result.save_deprecated_result",
            args=[plugin_version_pk, False, "[]"],
        )
        return

    tmp_dir = tempfile.mkdtemp()
    logs = "[]"
    passed = False

    try:
        with zipfile.ZipFile(package_path, "r") as zip_ref:
            zip_ref.extractall(tmp_dir)
        logger.info(f"Zip extracted to {tmp_dir}")

        subdirs = [
            d for d in os.listdir(tmp_dir) if os.path.isdir(os.path.join(tmp_dir, d))
        ]
        if not subdirs:
            raise Exception("No subdirectory found in zip")

        # Write pyproject.toml at tmp_dir root
        pyproject_path = os.path.join(tmp_dir, "pyproject.toml")
        with open(pyproject_path, "w") as f:
            f.write(PYPROJECT_CONTENT)
        logger.info(f"pyproject.toml written to {pyproject_path}")

        logger.info(
            f"About to run pyright in {tmp_dir}, contents: {os.listdir(tmp_dir)}"
        )

        # Run pyright with JSON output
        result = subprocess.run(
            ["pyright", ".", "--outputjson"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=tmp_dir,
            timeout=120,
            bufsize=-1,
        )
        logger.info(
            f"Return code: {result.returncode}, stdout size: {len(result.stdout)}"
        )
        raw = result.stdout.decode("utf-8", errors="ignore")
        # logger.info(f"Full stdout length: {len(raw)}, first 200: {repr(raw[:200])}")
        # logger.info(f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:200]}")
        logger.info(
            f"Return code: {result.returncode}, stdout size: {len(result.stdout)}, stderr: {result.stderr.decode('utf-8', errors='ignore')[:300]}"
        )
        output = json.loads(raw)

        deprecated_items = [
            {
                "file": d["file"],
                "line": d["range"]["start"]["line"] + 1,  # pyright is 0-indexed
                "message": d["message"],
            }
            for d in output.get("generalDiagnostics", [])
            if d.get("rule") == "reportDeprecated"
        ]
        logs = json.dumps(deprecated_items)
        passed = True
        logger.info(
            f"Pyright ran successfully, deprecated items: {len(deprecated_items)}"
        )

    except Exception:
        logs = "[]"
        passed = False
        logger.exception(f"Error during deprecated check for pk={plugin_version_pk}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(f"Sending result to main worker for pk={plugin_version_pk}")
    app.send_task(
        "plugins.tasks.save_deprecated_result.save_deprecated_result",
        args=[plugin_version_pk, passed, logs],
    )
