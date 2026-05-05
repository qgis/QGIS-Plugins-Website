from django.contrib import admin
from django.utils.html import format_html
from plugins.models import (  # , PluginCrashReport
    Plugin,
    PluginVersion,
    PluginVersionDownload,
    PluginVersionSecurityScan,
    SecurityRule,
    PluginVersionSecurityRuleSkip,
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


class SecurityRuleAdmin(admin.ModelAdmin):
    list_display = (
        "check_code",
        "check_name",
        "check_category",
        "severity_display",
        "enabled_display",
        "can_be_skipped_display",
    )
    list_filter = ("check_category", "severity", "enabled", "can_be_skipped")
    search_fields = ("check_code", "check_name", "check_description")
    ordering = ("check_category", "check_code")
    readonly_fields = ("created_on", "updated_on")
    
    fieldsets = (
        ("Rule Identification", {
            "fields": ("check_code", "check_name", "check_category")
        }),
        ("Configuration", {
            "fields": ("severity", "enabled", "can_be_skipped", "check_description")
        }),
        ("Metadata", {
            "fields": ("created_on", "updated_on"),
            "classes": ("collapse",)
        }),
    )

    actions = ["enable_rules", "disable_rules", "make_skippable", "make_non_skippable"]

    def severity_display(self, obj):
        colors = {"info": "blue", "warning": "orange", "critical": "red"}
        color = colors.get(obj.severity, "black")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.severity.upper()
        )
    severity_display.short_description = "Severity"

    def enabled_display(self, obj):
        if obj.enabled:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Enabled</span>'
            )
        return format_html(
            '<span style="color: gray;">✗ Disabled</span>'
        )
    enabled_display.short_description = "Status"

    def can_be_skipped_display(self, obj):
        if obj.can_be_skipped:
            return format_html(
                '<span style="color: blue;">✓ Skippable</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">✗ Required</span>'
        )
    can_be_skipped_display.short_description = "Skippable"

    def enable_rules(self, request, queryset):
        updated = queryset.update(enabled=True)
        self.message_user(request, f"{updated} rules enabled successfully.")
    enable_rules.short_description = "Enable selected rules"

    def disable_rules(self, request, queryset):
        updated = queryset.update(enabled=False)
        self.message_user(request, f"{updated} rules disabled successfully.")
    disable_rules.short_description = "Disable selected rules"

    def make_skippable(self, request, queryset):
        updated = queryset.update(can_be_skipped=True)
        self.message_user(request, f"{updated} rules marked as skippable.")
    make_skippable.short_description = "Mark as skippable"

    def make_non_skippable(self, request, queryset):
        updated = queryset.update(can_be_skipped=False)
        self.message_user(request, f"{updated} rules marked as non-skippable (required).")
    make_non_skippable.short_description = "Mark as non-skippable (required)"


class PluginVersionSecurityRuleSkipAdmin(admin.ModelAdmin):
    list_display = (
        "plugin_version",
        "security_rule",
        "skipped_by",
        "skipped_on",
    )
    list_filter = ("security_rule__check_category", "skipped_on")
    search_fields = (
        "plugin_version__plugin__name",
        "plugin_version__version",
        "security_rule__check_code",
        "security_rule__check_name",
    )
    readonly_fields = ("plugin_version", "security_rule", "skipped_by", "skipped_on")
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
        "enabled_rules_count",
        "skipped_rules_count",
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
        "enabled_rules_count",
        "skipped_rules",
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
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(status, "black"),
            status.upper()
        )

    overall_status.allow_tags = True
    overall_status.short_description = "Status"

    def pass_rate(self, obj):
        rate = obj.pass_rate
        color = "green" if rate >= 80 else "orange" if rate >= 60 else "red"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}%</span>',
            color,
            rate
        )

    pass_rate.allow_tags = True
    pass_rate.short_description = "Pass Rate"

    def skipped_rules_count(self, obj):
        count = len(obj.skipped_rules) if obj.skipped_rules else 0
        if count > 0:
            return format_html(
                '<span style="color: orange; font-weight: bold;">{}</span>',
                count
            )
        return count

    skipped_rules_count.short_description = "Skipped Rules"


# class PluginCrashReportAdmin(admin.ModelAdmin):
# pass


admin.site.register(Plugin, PluginAdmin)
admin.site.register(PluginVersion, PluginVersionAdmin)
admin.site.register(PluginVersionDownload, PluginVersionDownloadAdmin)
admin.site.register(SecurityRule, SecurityRuleAdmin)
admin.site.register(PluginVersionSecurityRuleSkip, PluginVersionSecurityRuleSkipAdmin)
admin.site.register(PluginVersionSecurityScan, PluginVersionSecurityScanAdmin)
# admin.site.register(PluginCrashReport, PluginCrashReportAdmin)
