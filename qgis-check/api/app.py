from flask import Flask, request, Response
import os
import subprocess
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)

log_file = "qt6_checker.log"
logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(levelname)s - %(message)s')

SCRIPT_PATH = os.environ.get("SCRIPT_PATH", "/usr/local/bin/pyqt5_to_pyqt6.py")

@app.route('/check-qt6', methods=['POST'])
def check_qt6():
    try:
        plugin_path = request.form.get('plugin_path')
        logging.info(f"Received plugin_path: {plugin_path}")

        if not plugin_path:
            logging.warning("No plugin_path provided")
            return Response("No folder path provided", status=400)

        if not os.path.isdir(plugin_path):
            logging.warning(f"Invalid plugin_path: {plugin_path}")
            return Response("Invalid folder path", status=400)

        command = [SCRIPT_PATH, plugin_path, "--dry_run"]
        logging.info(f"Executing command: {' '.join(command)}")

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            logging.error(f"Script {SCRIPT_PATH} exited with error: {result.returncode}")
        else:
            logging.info(f"Script {SCRIPT_PATH} executed successfully on {plugin_path}")

        log_qt6 = clean_log(result.stderr)
        print(log_qt6)
        return log_qt6

    except subprocess.TimeoutExpired:
        logging.exception("Script execution timed out")
        return Response("Script execution timed out", status=504)

    except Exception as e:
        logging.exception("Unexpected error occurred")
        return Response(f"Unexpected server error: {str(e)}", status=500)

def clean_log(log: str) -> str:
    log = log.replace("/home/web/shared/", "")
    log = log.replace("=== dry_run mode | Start Logs ===\n", "")
    return log


if __name__ == '__main__':
    logging.info("Starting Flask server on QGIS-Qt6")
    app.run(host="0.0.0.0", port=5000)
