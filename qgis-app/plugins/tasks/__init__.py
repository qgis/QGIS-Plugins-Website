from plugins.tasks.delete_marked_plugins import delete_marked_plugins
from plugins.tasks.generate_plugins_xml import generate_plugins_xml
from plugins.tasks.get_sustaining_members import get_sustaining_members
from plugins.tasks.rebuild_search_index import rebuild_search_index
from plugins.tasks.run_security_scan import run_security_scan_task
from plugins.tasks.send_email_communication import send_email_communication
from plugins.tasks.trigger_annual_reverification import (
    send_anniversary_reverifications,
)
from plugins.tasks.trigger_email_confirmation import (
    check_and_send_confirmation,
    send_pending_email_confirmations,
)
from plugins.tasks.update_qgis_versions import update_qgis_versions
