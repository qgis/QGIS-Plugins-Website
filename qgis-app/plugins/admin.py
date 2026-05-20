from django.contrib import admin
from django.utils.html import format_html
from plugins.models import (  # , PluginCrashReport
    Plugin,
    PluginEmailConfirmation,
    PluginVersion,
    PluginVersionDownload,
    PluginVersionSecurityScan,
)


class PluginAdmin(admin.ModelAdmin):
    list_filter = ("featured",)
    list_display = (
        "name",
        "featured",
        "created_by",
        "created_on",
        "downloads",
        "stable",
        "experimental",
    )
    search_fields = ("name",)


class PluginVersionAdmin(admin.ModelAdmin):
    list_filter = ("experimental", "approved", "plugin")
    list_display = (
        "plugin",
        "approved",
        "version",
        "experimental",
        "created_on",
        "downloads",
    )


class PluginVersionDownloadAdmin(admin.ModelAdmin):
    list_display = ("plugin_version", "download_date", "download_count")
    raw_id_fields = ("plugin_version",)


class PluginVersionSecurityScanAdmin(admin.ModelAdmin):
    list_display = (
        "plugin_version",
        "scanned_on",
        "overall_status",
        "pass_rate",
        "total_checks",
        "passed_checks",
        "critical_count",
        "warning_count",
    )
    list_filter = ("scanned_on",)
    search_fields = ("plugin_version__plugin__name", "plugin_version__version")
    readonly_fields = (
        "plugin_version",
        "scanned_on",
        "total_checks",
        "passed_checks",
        "warning_count",
        "critical_count",
        "info_count",
        "files_scanned",
        "total_issues",
        "scan_report",
    )
    raw_id_fields = ()

    def overall_status(self, obj):
        status = obj.overall_status
        colors = {
            "passed": "green",
            "info": "blue",
            "warning": "orange",
            "critical": "red",
        }
        return f'<span style="color: {colors.get(status, "black")}; font-weight: bold;">{status.upper()}</span>'

    overall_status.allow_tags = True
    overall_status.short_description = "Status"

    def pass_rate(self, obj):
        rate = obj.pass_rate
        color = "green" if rate >= 80 else "orange" if rate >= 60 else "red"
        return f'<span style="color: {color}; font-weight: bold;">{rate}%</span>'

    pass_rate.allow_tags = True
    pass_rate.short_description = "Pass Rate"


# class PluginCrashReportAdmin(admin.ModelAdmin):
# pass


class PluginEmailConfirmationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "plugin_list",
        "sent_at",
        "confirmed_at",
        "expires_at",
        "confirmation_status",
    )
    list_filter = ("confirmed_at",)
    search_fields = ("email", "plugins__name", "plugins__package_name")
    readonly_fields = (
        "email",
        "plugin_list",
        "key",
        "sent_at",
        "confirmed_at",
        "expires_at",
    )
    actions = ["resend_confirmation_email"]

    @admin.display(description="Plugins")
    def plugin_list(self, obj):
        names = ", ".join(obj.plugins.values_list("name", flat=True))
        return names or "—"

    @admin.display(description="Status")
    def confirmation_status(self, obj):
        if obj.is_confirmed:
            return format_html(
                '<span style="color:green;font-weight:bold;">&#10003; Confirmed</span>'
            )
        if obj.is_expired:
            return format_html(
                '<span style="color:orange;font-weight:bold;">&#8987; Expired</span>'
            )
        return format_html('<span style="color:gray;">&#8987; Pending</span>')


admin.site.register(Plugin, PluginAdmin)
admin.site.register(PluginVersion, PluginVersionAdmin)
admin.site.register(PluginVersionDownload, PluginVersionDownloadAdmin)
admin.site.register(PluginVersionSecurityScan, PluginVersionSecurityScanAdmin)
admin.site.register(PluginEmailConfirmation, PluginEmailConfirmationAdmin)
# admin.site.register(PluginCrashReport, PluginCrashReportAdmin)
