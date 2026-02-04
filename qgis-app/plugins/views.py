# Create your views here.
import copy
import datetime
import logging
import os
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.sites.models import Site
from django.core.exceptions import FieldDoesNotExist
from django.core.mail import EmailMessage, send_mail
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.db.models.expressions import RawSQL
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.encoding import DjangoUnicodeDecodeError
from django.utils.html import mark_safe
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.generic.detail import DetailView

# from sortable_listview import SortableListView
from django.views.generic.list import ListView
from plugins.decorators import has_valid_token
from plugins.forms import *
from plugins.models import (
    Plugin,
    PluginOutstandingToken,
    PluginVersion,
    PluginVersionDownload,
    PluginVersionFeedback,
    PluginVersionFeedbackAttachment,
    PluginVersionSecurityScan,
    vjust,
)
from plugins.security_utils import get_scan_badge_info, run_security_scan
from plugins.utils import parse_remote_addr
from plugins.validator import PLUGIN_REQUIRED_METADATA
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken, api_settings

try:
    from urllib import unquote, urlencode

    from urlparse import parse_qs, urlparse
except ImportError:
    from urllib.parse import parse_qs, unquote, urlencode, urlparse

# Decorator
staff_required = user_passes_test(lambda u: u.is_staff)
from plugins.tasks.generate_plugins_xml import generate_plugins_xml

# Plugin Notification Recipients Group Name
NOTIFICATION_RECIPIENTS_GROUP_NAME = settings.NOTIFICATION_RECIPIENTS_GROUP_NAME


def send_mail_wrapper(subject, message, mail_from, recipients, fail_silently=True):
    if settings.DEBUG:
        logging.debug("Mail not sent (DEBUG=True)")
    else:
        send_mail(subject, message, mail_from, recipients, fail_silently)


def send_mail_with_attachments(
    subject, message, mail_from, recipients, attachments=None, fail_silently=True
):
    """
    Send email with optional file attachments
    """
    if settings.DEBUG:
        logging.debug("Mail with attachments not sent (DEBUG=True)")
    else:
        email = EmailMessage(
            subject=subject, body=message, from_email=mail_from, to=recipients
        )

        if attachments:
            for attachment in attachments:
                try:
                    with attachment.image.open("rb") as f:
                        email.attach(
                            attachment.image.name.split("/")[-1],  # filename
                            f.read(),  # file content
                            "image/jpeg",  # MIME type - could be made dynamic
                        )
                except Exception as e:
                    logging.warning(
                        f"Failed to attach image {attachment.image.name}: {e}"
                    )

        email.send(fail_silently=fail_silently)


def plugin_notify(plugin):
    """
    Sends a message to staff that are in
    the notification recipients group on new plugins
    """
    recipients = [
        u.email
        for u in User.objects.filter(
            groups__name=NOTIFICATION_RECIPIENTS_GROUP_NAME,
            is_staff=True,
            email__isnull=False,
        ).exclude(email="")
    ]

    if recipients:
        domain = Site.objects.get_current().domain
        mail_from = settings.DEFAULT_FROM_EMAIL

        send_mail_wrapper(
            _("A new plugin has been created by %s.") % plugin.created_by,
            _(
                "\r\nPlugin name is: %s\r\nPlugin description is: %s\r\nLink: http://%s%s\r\n"
            )
            % (plugin.name, plugin.description, domain, plugin.get_absolute_url()),
            mail_from,
            recipients,
            fail_silently=True,
        )
        logging.debug(
            "Sending email notification for %s plugin, recipients:  %s"
            % (plugin, recipients)
        )
    else:
        logging.warning("No recipients found for %s plugin notification" % plugin)


def version_notify(plugin_version):
    """
    Sends a message to staff that are in
    the notification recipients group on new plugin versions
    """
    plugin = plugin_version.plugin

    recipients = [
        u.email
        for u in User.objects.filter(
            groups__name=NOTIFICATION_RECIPIENTS_GROUP_NAME,
            is_staff=True,
            email__isnull=False,
        ).exclude(email="")
    ]

    if recipients:
        domain = Site.objects.get_current().domain
        mail_from = settings.DEFAULT_FROM_EMAIL

        send_mail_wrapper(
            _("A new plugin version has been uploaded by %s.") % plugin.created_by,
            _(
                "\r\nPlugin name is: %s\r\nPlugin description is: %s\r\nLink: http://%s%s\r\n"
            )
            % (
                plugin.name,
                plugin.description,
                domain,
                plugin_version.get_absolute_url(),
            ),
            mail_from,
            recipients,
            fail_silently=True,
        )
        logging.debug(
            "Sending email notification for %s plugin version, recipients:  %s"
            % (plugin_version, recipients)
        )
    else:
        logging.warning(
            "No recipients found for %s plugin version notification" % plugin_version
        )


def plugin_approve_notify(plugin, msg, user):
    """
    Sends a message when a plugin is approved or unapproved.
    """
    if settings.DEBUG:
        return
    recipients = [u.email for u in plugin.editors if u.email]
    if settings.QGIS_DEV_MAILING_LIST_ADDRESS:
        recipients.append(settings.QGIS_DEV_MAILING_LIST_ADDRESS)
    if plugin.approved:
        approval_state = "approval"
    else:
        approval_state = "unapproval"

    if len(recipients):
        domain = Site.objects.get_current().domain
        mail_from = settings.DEFAULT_FROM_EMAIL
        logging.debug(
            "Sending email %s notification for %s plugin, recipients:  %s"
            % (approval_state, plugin, recipients)
        )
        send_mail_wrapper(
            _("Plugin %s %s notification.") % (plugin, approval_state),
            _("\r\nPlugin %s %s by %s.\r\n%s\r\nLink: http://%s%s\r\n")
            % (
                plugin.name,
                approval_state,
                user,
                msg,
                domain,
                plugin.get_absolute_url(),
            ),
            mail_from,
            recipients,
            fail_silently=True,
        )
    else:
        logging.warning(
            "No recipients found for %s plugin %s notification"
            % (plugin, approval_state)
        )


def version_feedback_notify(version, user):
    """
    Sends a message when a version is receiving feedback.
    """
    if settings.DEBUG:
        return
    plugin = version.plugin
    recipients = [u.email for u in plugin.editors if u.email]
    if recipients:
        domain = Site.objects.get_current().domain
        mail_from = settings.DEFAULT_FROM_EMAIL
        logging.debug(
            "Sending email feedback notification for %s plugin version %s, recipients:  %s"
            % (plugin, version.version, recipients)
        )

        # Get latest feedback attachments for this version
        recent_attachments = PluginVersionFeedbackAttachment.objects.filter(
            feedback__version=version, feedback__reviewer=user
        ).order_by("-created_on")[
            :5
        ]  # Limit to 5 most recent attachments

        message = _(
            "\r\nPlugin %s reviewed by %s and received a feedback.\r\nLink: http://%s%sfeedback/\r\n"
        ) % (
            plugin.name,
            user,
            domain,
            version.get_absolute_url(),
        )

        if recent_attachments:
            message += (
                _("\r\nThis feedback includes %d image attachment(s).\r\n")
                % recent_attachments.count()
            )

        send_mail_with_attachments(
            _("Plugin %s feedback notification.") % (plugin,),
            message,
            mail_from,
            recipients,
            attachments=recent_attachments,
            fail_silently=True,
        )
    else:
        logging.warning(
            "No recipients found for %s plugin feedback notification" % (plugin,)
        )


def version_feedback_resolved_notify(version, user, all_tasks):
    """
    Sends a message when a version feedback is resolved.
    """
    plugin = version.plugin

    reviewers_emails = all_tasks.values_list("reviewer__email", flat=True)
    reviewers_emails = list(set(reviewers_emails))

    if reviewers_emails:
        domain = Site.objects.get_current().domain
        mail_from = settings.DEFAULT_FROM_EMAIL

        logging.debug(
            "Sending email feedback resolved notification for %s plugin version %s, recipients:  %s"
            % (plugin, version.version, reviewers_emails)
        )
        send_mail_wrapper(
            _("Plugin %s feedback resolved notification.") % (plugin,),
            _(
                "\r\nPlugin %s feedback resolved by %s.\r\nLink: http://%s%sfeedback/\r\n. The plugin is now ready for review again."
            )
            % (
                plugin.name,
                user,
                domain,
                version.get_absolute_url(),
            ),
            mail_from,
            reviewers_emails,
            fail_silently=True,
        )
    else:
        logging.warning(
            "No recipients found for %s plugin feedback resolved notification"
            % (plugin,)
        )


def user_trust_notify(user):
    """
    Sends a message when an author is trusted or untrusted.
    """
    if settings.DEBUG:
        return
    if user.is_staff:
        logging.debug("Skipping trust notification for staff user %s" % user)
    else:
        if user.email:
            recipients = [user.email]
            mail_from = settings.DEFAULT_FROM_EMAIL

            if user.has_perm("plugins.can_approve"):
                subject = _("User trust notification.")
                message = _(
                    "\r\nYou can now approve your own plugins and the plugins you can edit.\r\n"
                )
            else:
                subject = _("User untrust notification.")
                message = _("\r\nYou cannot approve any plugin.\r\n")

            logging.debug("Sending email trust change notification to %s" % recipients)
            send_mail_wrapper(
                subject, message, mail_from, recipients, fail_silently=True
            )
        else:
            logging.warning(
                "No email found for %s user trust change notification" % user
            )


## Access control ##


def check_plugin_access(user, plugin):
    """
    Returns true if the user can modify the plugin:

        * is_staff
        * is owner

    """
    return user.is_staff or user in plugin.editors


def check_plugin_token_access(user, plugin):
    """
    Returns true if the user can access all the plugin's token:

        * is_staff
        * is maintainer

    """
    return user.is_staff or user.pk == plugin.created_by.pk


def check_plugin_version_approval_rights(user, plugin):
    """
    Returns true if the user can approve the plugin version:

        * is_staff
        * is owner and is trusted

    """
    return user.is_staff or (
        user in plugin.editors and user.has_perm("plugins.can_approve")
    )


@login_required
def plugin_create(request):
    """
    The form will automatically set published flag according to user permissions.
    There is a more "automatic" alternative for creating new Plugins in a single step
    through package upload
    """
    if request.method == "POST":
        form = PluginForm(request.POST, request.FILES)
        form.fields["owners"].queryset = User.objects.exclude(
            pk=request.user.pk
        ).order_by("username")
        if form.is_valid():
            plugin = form.save(commit=False)
            plugin.created_by = request.user
            plugin.save()
            plugin_notify(plugin)
            msg = _("The Plugin has been successfully created.")
            messages.success(request, msg, fail_silently=True)
            return HttpResponseRedirect(plugin.get_absolute_url())
    else:
        form = PluginForm()
        form.fields["owners"].queryset = User.objects.exclude(
            pk=request.user.pk
        ).order_by("username")

    return render(
        request,
        "plugins/plugin_form.html",
        {"form": form, "form_title": _("New plugin")},
    )


@staff_required
@require_POST
def plugin_set_featured(request, package_name):
    """
    Set as featured
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    plugin.featured = True
    plugin.save()
    msg = _("The plugin %s is now a marked as featured." % plugin)
    messages.success(request, msg, fail_silently=True)
    return HttpResponseRedirect(plugin.get_absolute_url())


@staff_required
@require_POST
def plugin_unset_featured(request, package_name):
    """
    Sets as not featured
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    plugin.featured = False
    plugin.save()
    msg = _("The plugin %s is not marked as featured anymore." % plugin)
    messages.success(request, msg, fail_silently=True)
    return HttpResponseRedirect(plugin.get_absolute_url())


@login_required
def plugin_upload(request):
    """
    This is the "single step" way to create new plugins:
    uploads a package and creates a new Plugin with a new PluginVersion
    can also update an existing plugin
    """
    if request.method == "POST":
        form = PackageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                plugin_data = {
                    "name": form.cleaned_data["name"],
                    "package_name": form.cleaned_data["package_name"],
                    "description": form.cleaned_data["description"],
                    "created_by": request.user,
                    "author": form.cleaned_data["author"],
                    "email": form.cleaned_data["email"],
                    "created_by": request.user,
                    "icon": form.cleaned_data["icon_file"],
                }

                # Gets existing plugin
                try:
                    plugin = Plugin.objects.get(
                        package_name=plugin_data["package_name"]
                    )
                    if not check_plugin_access(request.user, plugin):
                        return render(
                            request, "plugins/plugin_permission_deny.html", {}
                        )
                    # Apply new values
                    plugin.name = plugin_data["name"]
                    plugin.description = plugin_data["description"]
                    plugin.author = plugin_data["author"]
                    plugin.email = plugin_data["email"]
                    is_new = False
                except Plugin.DoesNotExist:
                    plugin = Plugin(**plugin_data)
                    is_new = True

                # Check icon, don't change if not valid
                if plugin_data["icon"]:
                    plugin.icon = plugin_data["icon"]

                # Server is optional
                plugin.server = form.cleaned_data.get("server", False)

                # Other optional fields
                warnings = []

                if form.cleaned_data.get("homepage"):
                    plugin.homepage = form.cleaned_data.get("homepage")
                elif not plugin.homepage:
                    warnings.append(
                        _(
                            "<strong>homepage</strong> field is empty, this field is not required but is recommended, please consider adding it to metadata."
                        )
                    )
                if form.cleaned_data.get("tracker"):
                    plugin.tracker = form.cleaned_data.get("tracker")
                elif not plugin.tracker:
                    raise ValidationError(
                        _(
                            '"tracker" metadata is required! Please add it to <code>metadata.txt</code>.'
                        )
                    )
                if form.cleaned_data.get("repository"):
                    plugin.repository = form.cleaned_data.get("repository")
                elif not plugin.repository:
                    raise ValidationError(
                        _(
                            '"repository" metadata is required! Please add it to <code>metadata.txt</code>.'
                        )
                    )
                if form.cleaned_data.get("about"):
                    plugin.about = form.cleaned_data.get("about")
                elif not plugin.about:
                    raise ValidationError(
                        _(
                            '"about" metadata is required! Please add it to <code>metadata.txt</code>.'
                        )
                    )

                # Save main Plugin object
                plugin.save()

                if is_new:
                    plugin_notify(plugin)

                # Takes care of tags
                if form.cleaned_data.get("tags"):
                    plugin.tags.set(
                        [
                            t.strip().lower()
                            for t in form.cleaned_data.get("tags").split(",")
                        ]
                    )

                version_data = {
                    "plugin": plugin,
                    "min_qg_version": form.cleaned_data.get("qgisMinimumVersion"),
                    "max_qg_version": form.cleaned_data.get("qgisMaximumVersion"),
                    "version": form.cleaned_data.get("version"),
                    "created_by": request.user,
                    "package": form.cleaned_data.get("package"),
                    "approved": request.user.has_perm("plugins.can_approve")
                    or plugin.approved,
                    "experimental": form.cleaned_data.get("experimental", False),
                    "supports_qt6": form.cleaned_data.get("supportsQt6", False),
                    "changelog": form.cleaned_data.get("changelog", ""),
                    "external_deps": form.cleaned_data.get("external_deps", ""),
                }

                # Add screenshot if available from package
                if form.cleaned_data.get("screenshot_file"):
                    version_data["screenshot"] = form.cleaned_data.get(
                        "screenshot_file"
                    )

                new_version = PluginVersion(**version_data)
                new_version.save()

                # Update plugin-level screenshot when version has one
                if form.cleaned_data.get("screenshot_file"):
                    plugin.screenshot = form.cleaned_data.get("screenshot_file")
                    plugin.save(update_fields=["screenshot"])
                msg = _("The Plugin has been successfully created.")
                messages.success(request, msg, fail_silently=True)

                # Run security scan on the uploaded package
                security_scan = run_security_scan(new_version)
                if security_scan:
                    # Add security scan results to messages with link to details
                    scan_url = f"{new_version.get_absolute_url()}#security-tab"
                    badge_info = get_scan_badge_info(security_scan)
                    if security_scan.overall_status == "passed":
                        messages.success(
                            request,
                            mark_safe(
                                _(
                                    f"✓ Security scan completed: {badge_info['text']}. <a href='{scan_url}'>View detailed report</a>"
                                )
                            ),
                            fail_silently=True,
                        )
                    elif security_scan.overall_status == "critical":
                        warnings.append(
                            mark_safe(
                                _(
                                    f"⚠ Security scan found {security_scan.critical_count} critical issues. <a href='{scan_url}'><strong>View details and address these issues</strong></a>"
                                )
                            )
                        )
                    elif security_scan.overall_status == "warning":
                        warnings.append(
                            mark_safe(
                                _(
                                    f"ℹ Security scan found {security_scan.warning_count} warnings. <a href='{scan_url}'>Review details</a>"
                                )
                            )
                        )

                # Update plugins cached xml
                generate_plugins_xml.delay()

                if not new_version.approved:
                    msg = _(
                        "Your plugin is awaiting approval from a staff member and will be approved as soon as possible."
                    )
                    warnings.append(msg)
                    if not is_new:
                        version_notify(new_version)
                if not form.cleaned_data.get("metadata_source") == "metadata.txt":
                    msg = _(
                        "Your plugin does not contain a metadata.txt file, metadata have been read from the __init__.py file. This is deprecated and its support will eventually cease."
                    )
                    warnings.append(msg)

                # Grouped messages:
                if warnings:
                    messages.warning(
                        request,
                        _("<p><strong>Warnings:</strong></p>")
                        + "\n".join([("<p>%s</p>" % w) for w in warnings]),
                        fail_silently=True,
                    )

                if form.cleaned_data.get("multiple_parent_folders"):
                    parent_folders = form.cleaned_data.get("multiple_parent_folders")
                    messages.warning(
                        request,
                        _(
                            f"Your plugin includes multiple parent folders: {parent_folders}. Please be aware that only the first folder has been recognized. It is strongly advised to have a single parent folder."
                        ),
                        fail_silently=True,
                    )
                    del form.cleaned_data["multiple_parent_folders"]

            except (IntegrityError, ValidationError, DjangoUnicodeDecodeError) as e:
                connection.close()
                messages.error(request, e, fail_silently=True)
                if not plugin.pk:
                    return render(request, "plugins/plugin_upload.html", {"form": form})
            return HttpResponseRedirect(plugin.get_absolute_url())
    else:
        form = PackageUploadForm()

    return render(request, "plugins/plugin_upload.html", {"form": form})


class PluginDetailView(DetailView):
    model = Plugin
    queryset = Plugin.objects.all()
    title = _("Plugin details")

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super(PluginDetailView, self).dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        plugin = kwargs.get("object")
        context = super(PluginDetailView, self).get_context_data(**kwargs)
        # Sort plugin versions by created_on descending
        context["plugin_versions_sorted"] = plugin.pluginversion_set.all().order_by(
            "-created_on"
        )
        # Warnings for owners
        if check_plugin_access(self.request.user, plugin):
            if not plugin.homepage:
                msg = _(
                    '<strong>homepage</strong> metadata is missing, this is not required but recommended. Please consider adding "homepage" to  <code>metadata.txt</code>.'
                )
                messages.warning(self.request, msg, fail_silently=True)
            for md in set(PLUGIN_REQUIRED_METADATA) - set(
                ("version", "qgisMinimumVersion")
            ):
                if not getattr(plugin, md, None):
                    msg = _(
                        "<strong>%s</strong> metadata is missing, this metadata entry is <strong>required</strong>. Please add <strong>%s</strong> to <code>metadata.txt</code>."
                    ) % (md, md)
                    messages.error(self.request, msg, fail_silently=True)
        stats_url = f"{settings.METABASE_DOWNLOAD_STATS_URL}?package_name={plugin.package_name}#hide_parameters=package_name"
        context.update(
            {
                "stats_url": stats_url,
                "rating": plugin.rating.get_rating(),
                "votes": plugin.rating.votes,
                "title": self.title,
            }
        )
        return context


@login_required
def plugin_delete(request, package_name):
    """
    Marks a plugin for deletion (soft delete).
    The plugin will be hidden from public lists but visible in 'My Plugins'.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/plugin_permission_deny.html", {})
    if "delete_confirm" in request.POST:
        plugin.is_deleted = True
        plugin.deleted_on = datetime.datetime.now()
        plugin.save()
        msg = _(
            "The Plugin has been marked for deletion and will be permanently deleted in 30 days."
        )
        messages.success(request, msg, fail_silently=True)
        return HttpResponseRedirect(reverse("my_plugins"))
    return render(request, "plugins/plugin_delete_confirm.html", {"plugin": plugin})


@login_required
def plugin_restore(request, package_name):
    """
    Restores a soft-deleted plugin.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name, is_deleted=True)
    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/plugin_permission_deny.html", {})
    if "restore_confirm" in request.POST:
        plugin.is_deleted = False
        plugin.deleted_on = None
        plugin.save()
        msg = _("The Plugin has been successfully restored.")
        messages.success(request, msg, fail_silently=True)
        return HttpResponseRedirect(
            reverse("plugin_detail", args=(plugin.package_name,))
        )
    return render(request, "plugins/plugin_restore_confirm.html", {"plugin": plugin})


@login_required
def plugin_permanent_delete(request, package_name):
    """
    Permanently deletes a soft-deleted plugin.
    Only staff users can permanently delete plugins.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name, is_deleted=True)
    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/plugin_permission_deny.html", {})

    # Only staff users can permanently delete
    if not request.user.is_staff:
        msg = _(
            "Only staff users can permanently delete plugins. Please contact the plugin approvers to request permanent deletion."
        )
        messages.error(request, msg, fail_silently=True)
        return HttpResponseRedirect(
            reverse("plugin_detail", args=(plugin.package_name,))
        )

    if "permanent_delete_confirm" in request.POST:
        plugin.delete()
        msg = _("The Plugin has been permanently deleted.")
        messages.success(request, msg, fail_silently=True)
        return HttpResponseRedirect(reverse("my_plugins"))
    return render(
        request, "plugins/plugin_permanent_delete_confirm.html", {"plugin": plugin}
    )


def _check_optional_metadata(form, request):
    """
    Checks for the presence of optional metadata
    """
    if not form.cleaned_data.get("homepage"):
        messages.warning(
            request,
            _(
                "Homepage field is empty, this field is not required but is recommended, please consider adding it to  <code>metadata.txt</code>."
            ),
            fail_silently=True,
        )


@login_required
def plugin_update(request, package_name):
    """
    Plugin update form
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/plugin_permission_deny.html", {})
    if request.method == "POST":
        form = PluginForm(request.POST, request.FILES, instance=plugin)
        form.fields["owners"].queryset = User.objects.exclude(
            pk=plugin.created_by.pk
        ).order_by("username")
        if form.is_valid():
            new_object = form.save(commit=False)
            new_object.modified_by = request.user
            new_object.save()
            # Without this next line the tags won't be saved.
            form.save_m2m()
            new_object.owners.clear()
            for o in form.cleaned_data["owners"]:
                new_object.owners.add(o)
            msg = _("The Plugin has been successfully updated.")
            messages.success(request, msg, fail_silently=True)

            # Checks for optional metadata
            _check_optional_metadata(form, request)

            return HttpResponseRedirect(new_object.get_absolute_url())
    else:
        form = PluginForm(instance=plugin)
        form.fields["owners"].queryset = User.objects.exclude(
            pk=plugin.created_by.pk
        ).order_by("username")

    return render(
        request,
        "plugins/plugin_form.html",
        {"form": form, "form_title": _("Edit plugin"), "plugin": plugin},
    )


class PluginTokenListView(ListView):
    """
    Plugin token list
    """

    model = PluginOutstandingToken
    queryset = PluginOutstandingToken.objects.all().order_by("-token__created_at")
    template_name = "plugins/plugin_token_list.html"

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super(PluginTokenListView, self).dispatch(*args, **kwargs)

    def get_filtered_queryset(self, qs):
        package_name = self.kwargs.get("package_name")
        plugin = get_object_or_404(Plugin, package_name=package_name)
        if not check_plugin_token_access(self.request.user, plugin):
            return qs.filter(
                plugin__pk=plugin.pk,
                is_blacklisted=False,
                token__user=self.request.user,
            )
        return qs.filter(
            plugin__pk=plugin.pk,
            is_blacklisted=False,
        )

    def get_queryset(self):
        qs = super(PluginTokenListView, self).get_queryset()
        qs = self.get_filtered_queryset(qs)
        return qs

    def get_context_data(self, **kwargs):
        package_name = self.kwargs.get("package_name")
        plugin = get_object_or_404(Plugin, package_name=package_name)
        if not check_plugin_access(self.request.user, plugin):
            context = {}
            self.template_name = "plugins/plugin_token_permission_deny.html"
            return context
        context = super(PluginTokenListView, self).get_context_data(**kwargs)
        context.update({"plugin": plugin})
        return context


class PluginTokenDetailView(DetailView):
    """
    Plugin token detail
    """

    model = OutstandingToken
    queryset = OutstandingToken.objects.all()
    template_name = "plugins/plugin_token_detail.html"

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super(PluginTokenDetailView, self).dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(PluginTokenDetailView, self).get_context_data(**kwargs)
        package_name = self.kwargs.get("package_name")
        token_id = self.kwargs.get("pk")
        plugin = get_object_or_404(Plugin, package_name=package_name)
        if not check_plugin_access(self.request.user, plugin):
            context = {}
            self.template_name = "plugins/plugin_token_permission_deny.html"
            return context

        outstanding_token = get_object_or_404(
            OutstandingToken, pk=token_id, user=self.request.user
        )
        plugin_token = get_object_or_404(
            PluginOutstandingToken,
            token__pk=outstanding_token.pk,
            is_blacklisted=False,
            is_newly_created=True,
        )
        try:
            token = RefreshToken(outstanding_token.token)
            token["plugin_id"] = plugin.pk
            token["refresh_jti"] = token[api_settings.JTI_CLAIM]
            del token["user_id"]
        except (InvalidToken, TokenError):
            context = {}
            self.template_name = "plugins/plugin_token_invalid_or_expired.html"
            return context
        timestamp_from_last_edit = int(time.time())
        context.update(
            {
                "access_token": str(token.access_token),
                "plugin": plugin,
                "object": outstanding_token,
                "timestamp_from_last_edit": timestamp_from_last_edit,
            }
        )
        plugin_token.is_newly_created = False
        plugin_token.save()
        return context


@login_required
@transaction.atomic
def plugin_token_create(request, package_name):
    if request.method == "POST":
        plugin = get_object_or_404(Plugin, package_name=package_name)
        user = request.user
        if not check_plugin_access(user, plugin):
            return render(request, "plugins/plugin_permission_deny.html", {})

        refresh = RefreshToken.for_user(user)
        refresh["plugin_id"] = plugin.pk

        jti = refresh[api_settings.JTI_CLAIM]

        outstanding_token = OutstandingToken.objects.get(jti=jti)

        plugin_token = PluginOutstandingToken.objects.create(
            plugin=plugin,
            token=outstanding_token,
            is_blacklisted=False,
            is_newly_created=True,
        )

        return HttpResponseRedirect(
            reverse(
                "plugin_token_detail", args=(plugin.package_name, outstanding_token.pk)
            )
        )


@login_required
@transaction.atomic
def plugin_token_update(request, package_name, token_id):
    plugin = get_object_or_404(Plugin, package_name=package_name)
    outstanding_token = get_object_or_404(OutstandingToken, pk=token_id)
    if not check_plugin_token_access(request.user, plugin):
        outstanding_token = get_object_or_404(
            OutstandingToken, pk=token_id, user=request.user
        )
    plugin_token = get_object_or_404(
        PluginOutstandingToken, token__pk=outstanding_token.pk, is_blacklisted=False
    )
    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/version_permission_deny.html", {})
    if request.method == "POST":
        form = PluginTokenForm(request.POST, instance=plugin_token)
        if form.is_valid():
            form.save()
            msg = _("The token description has been successfully updated.")
            messages.success(request, msg, fail_silently=True)
            return HttpResponseRedirect(
                reverse("plugin_token_list", args=(plugin.package_name,))
            )
    else:
        form = PluginTokenForm(instance=plugin_token)

    return render(
        request, "plugins/plugin_token_form.html", {"form": form, "token": plugin_token}
    )


@login_required
@transaction.atomic
def plugin_token_delete(request, package_name, token_id):
    plugin = get_object_or_404(Plugin, package_name=package_name)
    outstanding_token = get_object_or_404(OutstandingToken, pk=token_id)
    if not check_plugin_token_access(request.user, plugin):
        outstanding_token = get_object_or_404(
            OutstandingToken, pk=token_id, user=request.user
        )
    plugin_token = get_object_or_404(
        PluginOutstandingToken, token__pk=outstanding_token.pk, is_blacklisted=False
    )

    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/version_permission_deny.html", {})
    if "delete_confirm" in request.POST:
        try:
            token = RefreshToken(outstanding_token.token)
            token.blacklist()
            plugin_token.is_blacklisted = True
        except (InvalidToken, TokenError):
            plugin_token.is_blacklisted = True
        plugin_token.save()

        msg = _("The token has been successfully deleted.")
        messages.success(request, msg, fail_silently=True)
        return HttpResponseRedirect(
            reverse("plugin_token_list", args=(plugin.package_name,))
        )
    return render(
        request,
        "plugins/plugin_token_delete_confirm.html",
        {"plugin": plugin, "username": outstanding_token.user},
    )


class PluginsList(ListView):
    """
    List of approved plugins.
    """

    model = Plugin
    queryset = Plugin.approved_objects.all()
    title = _("All plugins")
    additional_context = {}
    paginate_by = settings.PAGINATION_DEFAULT_PAGINATION

    def get_paginate_by(self, queryset):
        """
        Paginate by specified value in querystring, or use default class property value.
        """
        try:
            paginate_by = int(self.request.GET.get("per_page", self.paginate_by))
            # Limit maximum items per page to 100
            if paginate_by > 100:
                paginate_by = 100
        except ValueError:
            paginate_by = self.paginate_by
        return paginate_by

    def get_filtered_queryset(self, qs):
        return qs

    def get_queryset(self):
        qs = super(PluginsList, self).get_queryset()
        qs = self.get_filtered_queryset(qs)

        # Get the sort and order parameters from the URL (with default values)
        sort_by = self.request.GET.get("sort", None)  # Default sort by name
        sort_order = self.request.GET.get("order", None)  # Default to ascending order

        if sort_by and sort_order:
            # Determine the correct sorting direction
            if sort_order == "desc":
                sort_by = "-" + sort_by  # Prepend '-' to sort in descending order

            # Validate the sort field
            if sort_by.lstrip("-") in [
                "average_vote",
                "latest_version_date",
                "weighted_rating",
            ] or self._is_valid_field(sort_by.lstrip("-")):
                qs = qs.order_by(sort_by)
            elif not qs.ordered:
                qs = qs.order_by(Lower("name"))

        return qs

    def _is_valid_field(self, field_name):
        try:
            self.model._meta.get_field(field_name)
            return True
        except FieldDoesNotExist:
            return False

    def get_context_data(self, **kwargs):
        context = super(PluginsList, self).get_context_data(**kwargs)
        context.update(
            {
                "title": self.title,
            }
        )
        context.update(self.additional_context)
        context["current_sort_query"] = self.get_sortstring()
        context["current_querystring"] = self.get_querystring()
        context["per_page_list"] = [20, 50, 75, 100]

        try:
            # Get the next value of per page from per_page_list
            next_per_page_id = (
                context["per_page_list"].index(context["paginator"].per_page) + 1
            )
            next_per_page = context["per_page_list"][next_per_page_id]
        except (ValueError, IndexError):
            # If the 'per_page' value in the request parameter
            # is not found in the 'per_page_list' or if the
            # next index is out of range, set the 'next_per_page'
            # value to a number greater than the total count
            # of records. This action effectively disables the button."
            next_per_page = context["paginator"].count + 1
        context["show_more_items_number"] = next_per_page

        # Check if any plugin is deprecated
        page = context["page_obj"]
        self.any_deprecated = any(
            obj.deprecated
            for obj in self.get_queryset()[
                (page.start_index() - 1) if page.start_index() else 0 : (
                    page.end_index() if page.end_index() else 0
                )
            ]
        )
        context["any_deprecated"] = self.any_deprecated
        return context

    def get_sortstring(self):
        if self.request.GET.get("sort", None):
            return "sort=%s" % self.request.GET.get("sort")
        return ""

    def get_querystring(self):
        """
        Clean existing query string (GET parameters) by removing
        arguments that we don't want to preserve (sort parameter, 'page')
        """
        to_remove = ["page", "sort"]
        query_string = urlparse(self.request.get_full_path()).query
        query_dict = parse_qs(query_string)
        for arg in to_remove:
            if arg in query_dict:
                del query_dict[arg]
        clean_query_string = urlencode(query_dict, doseq=True)
        return clean_query_string


class MyPluginsList(PluginsList):
    """
    List of plugins created by the user.
    Includes soft-deleted plugins so users can restore or permanently delete them.
    """

    def get_queryset(self):
        """Override to include soft-deleted plugins for the user's own plugins."""
        # Use objects.all() to bypass the BasePluginManager filter that excludes soft-deleted items
        qs = Plugin.objects.all()
        # Apply the user filter
        qs = self.get_filtered_queryset(qs)

        # Handle sorting (copied from parent class)
        sort_by = self.request.GET.get("sort", None)
        sort_order = self.request.GET.get("order", None)

        if sort_by and sort_order:
            if sort_order == "desc":
                sort_by = "-" + sort_by

            if sort_by.lstrip("-") in [
                "average_vote",
                "latest_version_date",
                "weighted_rating",
            ] or self._is_valid_field(sort_by.lstrip("-")):
                qs = qs.order_by(sort_by)
            elif not qs.ordered:
                qs = qs.order_by(Lower("name"))

        return qs

    def get_filtered_queryset(self, qs):
        return (
            qs.filter(owners=self.request.user).distinct()
            | qs.filter(created_by=self.request.user).distinct()
        )


class UserPluginsList(PluginsList):
    """
    List of plugins created by a specific user
    """

    def get_filtered_queryset(self, qs):
        user = get_object_or_404(User, username=self.kwargs["username"])
        return qs.filter(created_by=user)


class AuthorPluginsList(PluginsList):
    """
    List of plugins created by a specific author
    """

    def get_filtered_queryset(self, qs):
        return qs.filter(author=unquote(self.kwargs["author"]))

    def get_context_data(self, **kwargs):
        context = super(AuthorPluginsList, self).get_context_data(**kwargs)
        context.update(
            {
                "title": _("Plugins by %s") % unquote(self.kwargs["author"]),
            }
        )
        return context


class UserDetailsPluginsList(PluginsList):
    """
    List plugins created_by OR owned by user
    """

    template_name = "plugins/user.html"

    def get_filtered_queryset(self, qs):
        user = get_object_or_404(User, username=self.kwargs["username"])
        return qs.filter(Q(created_by=user) | Q(owners=user))

    def get_context_data(self, **kwargs):
        user = get_object_or_404(User, username=self.kwargs["username"])
        user_is_trusted = user.has_perm("plugins.can_approve")
        context = super(UserDetailsPluginsList, self).get_context_data(**kwargs)
        context.update(
            {
                "title": _("Plugins from %s") % user,
                "user_is_trusted": user_is_trusted,
                "plugin_user": user,
            }
        )
        return context


class TagsPluginsList(PluginsList):
    def get_filtered_queryset(self, qs):
        response = qs.filter(tagged_items__tag__slug=unquote(self.kwargs["tags"]))
        return response

    def get_context_data(self, **kwargs):
        context = super(TagsPluginsList, self).get_context_data(**kwargs)
        context.update(
            {
                "title": _("Plugins tagged with: %s") % unquote(self.kwargs["tags"]),
                "page_title": _("Tag: %s") % unquote(self.kwargs["tags"]),
            }
        )
        return context


class FeedbackCompletedPluginsList(PluginsList):
    """List of Plugins that has feedback resolved in its versions.

    The plugins editor can only see their plugin feedbacks.
    The staff can see all plugin feedbacks.
    """

    queryset = Plugin.feedback_completed_objects.all().order_by("-latest_version_date")

    def get_filtered_queryset(self, qs):
        user = get_object_or_404(User, username=self.request.user)
        if not user.is_staff:
            raise Http404
        return qs


class FeedbackReceivedPluginsList(PluginsList):
    """List of Plugins that has feedback received in its versions.

    The plugins editor can only see their plugin feedbacks.
    The staff can see all plugin feedbacks.
    """

    queryset = Plugin.feedback_received_objects.all().order_by("-latest_version_date")

    def get_filtered_queryset(self, qs):
        user = get_object_or_404(User, username=self.request.user)
        if not user.is_staff:
            raise Http404
        return qs


class FeedbackPendingPluginsList(PluginsList):
    """List of Plugins that has feedback pending in its versions.

    Only staff can see plugin feedback list.
    """

    queryset = Plugin.feedback_pending_objects.all().order_by("-latest_version_date")

    def get_filtered_queryset(self, qs):
        user = get_object_or_404(User, username=self.request.user)
        if not user.is_staff:
            raise Http404
        return qs


class AwaitingDeletionPluginsList(PluginsList):
    """List of plugins marked for deletion (soft-deleted).

    Only staff can see this list.
    """

    queryset = Plugin.objects.filter(is_deleted=True).order_by("-deleted_on")

    def get_filtered_queryset(self, qs):
        user = get_object_or_404(User, username=self.request.user)
        if not user.is_staff:
            raise Http404
        return qs


@login_required
@require_POST
def plugin_manage(request, package_name):
    """
    Entry point for the plugin management functions
    """
    if request.POST.get("set_featured"):
        return plugin_set_featured(request, package_name)
    if request.POST.get("unset_featured"):
        return plugin_unset_featured(request, package_name)
    if request.POST.get("delete"):
        return plugin_delete(request, package_name)

    return HttpResponseRedirect(reverse("user_details", args=[username]))


###############################################

# User management functions

###############################################


@staff_required
@require_POST
def user_block(request, username):
    """
    Completely blocks a user
    """
    user = get_object_or_404(User, username=username, is_staff=False)
    # Disable
    user.is_active = False
    user.save()
    msg = _("The user %s is now blocked." % user)
    messages.success(request, msg, fail_silently=True)
    return HttpResponseRedirect(reverse("user_details", args=[user.username]))


@staff_required
@require_POST
def user_unblock(request, username):
    """
    unblocks a user
    """
    user = get_object_or_404(User, username=username, is_staff=False)
    # Enable
    user.is_active = True
    user.save()
    msg = _("The user %s is now unblocked." % user)
    messages.success(request, msg, fail_silently=True)
    return HttpResponseRedirect(reverse("user_details", args=[user.username]))


@staff_required
@require_POST
def user_trust(request, username):
    """
    Assigns can_approve permission to the plugin creator
    """
    user = get_object_or_404(User, username=username)
    user.user_permissions.add(
        Permission.objects.get(
            codename="can_approve",
            content_type=ContentType.objects.get(app_label="plugins", model="plugin"),
        )
    )
    msg = _("The user %s is now a trusted user." % user)
    messages.success(request, msg, fail_silently=True)
    user_trust_notify(user)
    return HttpResponseRedirect(reverse("user_details", args=[user.username]))


@staff_required
@require_POST
def user_untrust(request, username):
    """
    Revokes can_approve permission to the plugin creator
    """
    user = get_object_or_404(User, username=username)
    user.user_permissions.remove(
        Permission.objects.get(
            codename="can_approve",
            content_type=ContentType.objects.get(app_label="plugins", model="plugin"),
        )
    )
    msg = _("The user %s is now an untrusted user." % user)
    messages.success(request, msg, fail_silently=True)
    user_trust_notify(user)
    return HttpResponseRedirect(reverse("user_details", args=[user.username]))


@staff_required
@require_POST
def user_permissions_manage(request, username):
    """
    Entry point for the user management functions
    """
    if request.POST.get("user_block"):
        return user_block(request, username)
    if request.POST.get("user_unblock"):
        return user_unblock(request, username)
    if request.POST.get("user_trust"):
        return user_trust(request, username)
    if request.POST.get("user_untrust"):
        return user_untrust(request, username)

    return HttpResponseRedirect(reverse("user_details", args=[username]))


###############################################

# Version management functions

###############################################


def _main_plugin_update(request, plugin, form):
    """
    Updates the main plugin object from version metadata
    """
    # Check if update name from metadata is allowed
    metadata_fields = [
        "author",
        "email",
        "description",
        "about",
        "homepage",
        "tracker",
        "repository",
    ]
    if plugin.allow_update_name:
        metadata_fields.insert(0, "name")

    # Update plugin from metadata
    for f in metadata_fields:
        value = form.cleaned_data.get(f)
        if value is not None:
            # Check max_length if defined on the model field
            field = plugin._meta.get_field(f)
            max_length = getattr(field, "max_length", None)
            if max_length is not None and len(str(value)) > max_length:
                messages.warning(
                    request,
                    _(
                        f"Field '{f}' exceeds the maximum allowed length of {max_length} characters. It will be truncated."
                    ),
                    fail_silently=True,
                )
                value = str(value)[:max_length]
            setattr(plugin, f, value)

    # Icon has a special treatment
    if form.cleaned_data.get("icon_file"):
        setattr(plugin, "icon", form.cleaned_data.get("icon_file"))
    if form.cleaned_data.get("tags"):
        plugin.tags.set(
            [t.strip().lower() for t in form.cleaned_data.get("tags").split(",")]
        )
    plugin.save()


@has_valid_token
@csrf_exempt
def version_create_api(request, package_name):
    """
    Create a new version using a valid token.
    We make sure that the token is valid before
    disabling CSRF protection.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = PluginVersion(
        plugin=plugin, is_from_token=True, token=request.plugin_token
    )

    return _version_create(request, plugin, version)


@login_required
def version_create(request, package_name):
    plugin = get_object_or_404(Plugin, package_name=package_name)
    if not check_plugin_access(request.user, plugin):
        return render(
            request, "plugins/version_permission_deny.html", {"plugin": plugin}
        )
    version = PluginVersion(plugin=plugin, created_by=request.user)
    is_trusted = request.user.has_perm("plugins.can_approve")
    return _version_create(request, plugin, version, is_trusted=is_trusted)


def _version_create(request, plugin, version, is_trusted=False):
    """
    The form will create versions according to permissions,
    plugin name and description are updated according to the info
    contained in the package metadata
    """
    if request.method == "POST":

        form = PluginVersionForm(
            request.POST, request.FILES, instance=version, is_trusted=is_trusted
        )
        if form.is_valid():
            try:
                new_object = form.save()
                msg = _("The Plugin Version has been successfully created.")
                messages.success(request, msg, fail_silently=True)

                # Run security scan on the uploaded package
                security_scan = run_security_scan(new_object)
                if security_scan:
                    # Add security scan results to messages with link to details
                    scan_url = f"{new_object.get_absolute_url()}#security-tab"
                    badge_info = get_scan_badge_info(security_scan)
                    if security_scan.overall_status == "passed":
                        messages.success(
                            request,
                            mark_safe(
                                _(
                                    f"✓ Security scan completed: {badge_info['text']}. <a href='{scan_url}'>View detailed report</a>"
                                )
                            ),
                            fail_silently=True,
                        )
                    elif security_scan.overall_status == "critical":
                        messages.warning(
                            request,
                            mark_safe(
                                _(
                                    f"⚠ Security scan found {security_scan.critical_count} critical issues. <a href='{scan_url}'><strong>View details and address these issues</strong></a>"
                                )
                            ),
                            fail_silently=True,
                        )
                    elif security_scan.overall_status == "warning":
                        messages.info(
                            request,
                            mark_safe(
                                _(
                                    f"ℹ Security scan found {security_scan.warning_count} warnings. <a href='{scan_url}'>Review details</a>"
                                )
                            ),
                            fail_silently=True,
                        )

                # The approved flag is also controlled in the form, but we
                # are checking it here in any case for additional security
                if not is_trusted:
                    new_object.approved = False
                    new_object.save()
                    messages.warning(
                        request,
                        _(
                            "You do not have approval permissions, plugin version has been set unapproved."
                        ),
                        fail_silently=True,
                    )
                    version_notify(new_object)
                if form.cleaned_data.get("icon_file"):
                    form.cleaned_data["icon"] = form.cleaned_data.get("icon_file")

                # Handle screenshot from package if available
                if form.cleaned_data.get("screenshot_file"):
                    new_object.screenshot = form.cleaned_data.get("screenshot_file")
                    new_object.save()
                    # Also update plugin-level screenshot
                    new_object.plugin.screenshot = form.cleaned_data.get(
                        "screenshot_file"
                    )
                    new_object.plugin.save(update_fields=["screenshot"])

                if form.cleaned_data.get("multiple_parent_folders"):
                    parent_folders = form.cleaned_data.get("multiple_parent_folders")
                    messages.warning(
                        request,
                        _(
                            f"Your plugin includes multiple parent folders: {parent_folders}. Please be aware that only the first folder has been recognized. It is strongly advised to have a single parent folder."
                        ),
                        fail_silently=True,
                    )
                    del form.cleaned_data["multiple_parent_folders"]

                _main_plugin_update(request, new_object.plugin, form)
                _check_optional_metadata(form, request)
                return HttpResponseRedirect(new_object.plugin.get_absolute_url())
            except (IntegrityError, ValidationError, DjangoUnicodeDecodeError) as e:
                messages.error(request, e, fail_silently=True)
                connection.close()
            return HttpResponseRedirect(plugin.get_absolute_url())
    else:
        form = PluginVersionForm(is_trusted=is_trusted)

    return render(
        request,
        "plugins/version_form.html",
        {"form": form, "plugin": plugin, "form_title": _("New version for plugin")},
    )


@has_valid_token
@csrf_exempt
def version_update_api(request, package_name, version):
    """
    Update a version using a valid token.
    We make sure that the token is valid before
    disabling CSRF protection.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    if version.approved:
        msg = _(
            "You cannot edit an approved version, please create a new version instead."
        )
        return JsonResponse({"detail": msg}, status=401)
    version.is_from_token = True
    version.token = request.plugin_token
    return _version_update(request, plugin, version)


@login_required
def version_update(request, package_name, version):
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    if not check_plugin_access(request.user, plugin):
        return render(
            request, "plugins/version_permission_deny.html", {"plugin": plugin}
        )
    if version.approved:
        msg = _(
            "You cannot edit an approved version, please create a new version instead."
        )
        messages.error(request, msg, fail_silently=True, extra_tags="is-danger")
        return HttpResponseRedirect(plugin.get_absolute_url())
    version.created_by = request.user
    is_trusted = request.user.has_perm("plugins.can_approve")
    return _version_update(request, plugin, version, is_trusted=is_trusted)


def _version_update(request, plugin, version, is_trusted=False):
    """
    The form will update versions according to permissions
    """

    if request.method == "POST":
        form = PluginVersionForm(
            request.POST,
            request.FILES,
            instance=version,
            is_trusted=is_trusted,
        )
        if form.is_valid():
            try:
                new_object = form.save()
                # update metadata for the main plugin object
                _main_plugin_update(request, new_object.plugin, form)
                msg = _("The Plugin Version has been successfully updated.")
                messages.success(request, msg, fail_silently=True)

                if form.cleaned_data.get("multiple_parent_folders"):
                    parent_folders = form.cleaned_data.get("multiple_parent_folders")
                    messages.warning(
                        request,
                        _(
                            f"Your plugin includes multiple parent folders: {parent_folders}. Please be aware that only the first folder has been recognized. It is strongly advised to have a single parent folder."
                        ),
                        fail_silently=True,
                    )
                    del form.cleaned_data["multiple_parent_folders"]

            except (IntegrityError, ValidationError, DjangoUnicodeDecodeError) as e:
                messages.error(request, e, fail_silently=True)
                connection.close()
            return HttpResponseRedirect(plugin.get_absolute_url())
    else:
        form = PluginVersionForm(instance=version, is_trusted=is_trusted)

    return render(
        request,
        "plugins/version_form.html",
        {
            "form": form,
            "plugin": plugin,
            "version": version,
            "form_title": _("Edit version for plugin"),
        },
    )


@login_required
def version_delete(request, package_name, version):
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    if not check_plugin_access(request.user, plugin):
        return render(request, "plugins/version_permission_deny.html", {})
    if "delete_confirm" in request.POST:
        version.delete()
        msg = _("The Plugin Version has been successfully deleted.")
        messages.success(request, msg, fail_silently=True)
        return HttpResponseRedirect(
            reverse("plugin_detail", args=(plugin.package_name,))
        )
    return render(
        request,
        "plugins/version_delete_confirm.html",
        {"plugin": plugin, "version": version},
    )


@login_required
@transaction.atomic
def versions_bulk_delete(request, package_name):
    """
    Bulk delete selected plugin versions with confirmation.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    if not check_plugin_access(request.user, plugin):
        messages.error(
            request, _("You do not have permission to delete versions for this plugin.")
        )
        return HttpResponseRedirect(plugin.get_absolute_url())

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected_versions")
        versions = PluginVersion.objects.filter(pk__in=selected_ids, plugin=plugin)
        if "confirm_bulk_delete" in request.POST:
            # Perform deletion
            deleted_versions = list(versions)
            versions.delete()
            messages.success(
                request, _(f"Deleted {len(deleted_versions)} plugin version(s).")
            )
            return HttpResponseRedirect(plugin.get_absolute_url())
        elif selected_ids:
            # Show confirmation page
            return TemplateResponse(
                request,
                "plugins/versions_bulk_delete_confirm.html",
                {
                    "plugin": plugin,
                    "versions": versions,
                },
            )
        else:
            messages.warning(request, _("No versions selected for deletion."))
            return HttpResponseRedirect(plugin.get_absolute_url())
    # GET fallback
    return HttpResponseRedirect(plugin.get_absolute_url())


@login_required
@require_POST
def version_approve(request, package_name, version):
    """
    Approves the plugin version
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    if not check_plugin_version_approval_rights(request.user, version.plugin):
        msg = _("You do not have approval rights for this plugin.")
        messages.error(request, msg, fail_silently=True)
        return HttpResponseRedirect(version.get_absolute_url())
    version.approved = True
    version.save()
    msg = (
        _(
            "The plugin version '%s' is now approved. "
            "Please note that there may be a delay of up to 15 minutes "
            "between the approval of the plugin and its actual availability in the XML."
        )
        % version
    )
    messages.success(request, msg, fail_silently=True)
    plugin_approve_notify(version.plugin, msg, request.user)
    try:
        redirect_to = request.META["HTTP_REFERER"]
    except:
        redirect_to = version.get_absolute_url()
    return HttpResponseRedirect(redirect_to)


@login_required
@require_POST
def version_unapprove(request, package_name, version):
    """
    unapproves the plugin version
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    if not check_plugin_version_approval_rights(request.user, version.plugin):
        msg = _("You do not have approval rights for this plugin.")
        messages.error(request, msg, fail_silently=True)
        return HttpResponseRedirect(version.get_absolute_url())
    version.approved = False
    version.save()
    msg = _('The plugin version "%s" is now unapproved' % version)
    messages.success(request, msg, fail_silently=True)
    plugin_approve_notify(version.plugin, msg, request.user)
    try:
        redirect_to = request.META["HTTP_REFERER"]
    except:
        redirect_to = version.get_absolute_url()
    return HttpResponseRedirect(redirect_to)


@login_required
@require_POST
def version_manage(request, package_name, version):
    """
    Entry point for the user management functions
    """
    if "version_approve" in request.POST:
        return version_approve(request, package_name, version)
    if "version_unapprove" in request.POST:
        return version_unapprove(request, package_name, version)

    return HttpResponseRedirect(reverse("plugin_detail", args=[package_name]))


@login_required
@never_cache
def version_feedback(request, package_name, version):
    """
    The form will add a comment/ feedback for the package version.
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    is_user_plugin_owner: bool = request.user in plugin.editors
    is_user_has_approval_rights: bool = check_plugin_version_approval_rights(
        request.user, plugin
    )
    if not is_user_plugin_owner and not is_user_has_approval_rights:
        return render(
            request,
            template_name="plugins/version_permission_deny.html",
            context={},
            status=403,
        )
    if request.method == "POST":
        form = VersionFeedbackForm(request.POST, request.FILES)
        if form.is_valid():
            tasks = form.cleaned_data["tasks"]
            images = form.cleaned_data.get("images", [])

            # Create feedback entries for each task
            feedback_objects = []
            for task in tasks:
                feedback = PluginVersionFeedback.objects.create(
                    version=version, reviewer=request.user, task=task
                )
                feedback_objects.append(feedback)

            # If images are uploaded, create attachment entries for the first feedback
            if images and feedback_objects:
                for image in images:
                    PluginVersionFeedbackAttachment.objects.create(
                        feedback=feedback_objects[0],  # Attach to first feedback
                        image=image,
                        caption=f"Attachment for {feedback_objects[0].task}",
                    )

            version_feedback_notify(version, request.user)
            return HttpResponseRedirect(
                reverse("version_feedback", args=[package_name, version.version])
            )
    form = VersionFeedbackForm()
    feedbacks = PluginVersionFeedback.objects.filter(version=version).prefetch_related(
        "attachments"
    )

    return render(
        request,
        "plugins/plugin_feedback.html",
        {
            "feedbacks": feedbacks,
            "form": form,
            "version": version,
            "is_user_has_approval_rights": is_user_has_approval_rights,
            "is_user_plugin_owner": is_user_plugin_owner,
        },
    )


@login_required
@require_POST
def version_feedback_update(request, package_name, version):
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)
    has_update_permission: bool = (
        request.user in plugin.editors
        or check_plugin_version_approval_rights(request.user, plugin)
    )
    if not has_update_permission:
        return JsonResponse({"success": False}, status=401)
    completed_tasks = request.POST.getlist("completed_tasks")
    for task_id in completed_tasks:
        try:
            task_id = int(task_id)
        except ValueError:
            continue
        feedback = PluginVersionFeedback.objects.filter(
            version=version, pk=task_id
        ).first()
        feedback.is_completed = True
        feedback.save()
    all_tasks = PluginVersionFeedback.objects.filter(version=version)
    if all_tasks.count() == len(completed_tasks):
        version_feedback_resolved_notify(version, request.user, all_tasks)

    return JsonResponse({"success": True}, status=201)


@login_required
@require_POST
def version_feedback_edit(request, package_name, version, feedback):
    feedback = get_object_or_404(
        PluginVersionFeedback,
        version__plugin__package_name=package_name,
        version__version=version,
        pk=feedback,
    )
    plugin = feedback.version.plugin

    has_update_permission: bool = (
        request.user in plugin.editors
        or check_plugin_version_approval_rights(request.user, plugin)
    )
    if not has_update_permission:
        return JsonResponse({"success": False}, status=401)

    # Update task text
    task = request.POST.get("task")
    feedback.task = str(task)
    feedback.modified_on = datetime.datetime.now()
    feedback.save()

    # Handle attachment deletions
    deleted_attachments = request.POST.get("deleted_attachments", "")
    if deleted_attachments:
        deleted_urls = [
            url.strip() for url in deleted_attachments.split(",") if url.strip()
        ]
        for url in deleted_urls:
            # Extract attachment ID or filename from URL to identify the attachment
            # Assuming URL format like /media/feedback_attachments/filename.jpg
            try:
                import os

                filename = os.path.basename(url)
                attachment = PluginVersionFeedbackAttachment.objects.filter(
                    feedback=feedback, image__endswith=filename
                ).first()
                if attachment:
                    attachment.delete()  # This will trigger the signal to delete the file
            except Exception as e:
                logging.warning(f"Failed to delete attachment {url}: {e}")

    # Handle new image uploads
    new_images = request.FILES.getlist("new_images")
    if new_images:
        for image in new_images:
            # Validate file type and size (same as in form)
            if not image.content_type.startswith("image/"):
                return JsonResponse(
                    {"success": False, "error": "Only image files are allowed."},
                    status=400,
                )
            if image.size > 5 * 1024 * 1024:  # 5MB
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Image file size must be less than 5MB.",
                    },
                    status=400,
                )

            # Create new attachment
            PluginVersionFeedbackAttachment.objects.create(
                feedback=feedback,
                image=image,
                caption=f"Additional attachment for {feedback.task}",
            )

    return JsonResponse(
        {"success": True, "modified_on": feedback.modified_on}, status=200
    )


@login_required
@require_POST
def version_feedback_delete(request, package_name, version, feedback):
    feedback = get_object_or_404(
        PluginVersionFeedback,
        version__plugin__package_name=package_name,
        version__version=version,
        pk=feedback,
    )
    plugin = feedback.version.plugin
    status = request.POST.get("status_feedback")
    is_update_succeed: bool = False
    is_user_can_update_feedback: bool = (
        request.user in plugin.editors
        or check_plugin_version_approval_rights(request.user, plugin)
    )
    if status == "deleted" and feedback.reviewer == request.user:
        feedback.delete()
        is_update_succeed: bool = True
    elif (status == "completed" or status == "uncompleted") and (
        is_user_can_update_feedback
    ):
        feedback.is_completed = status == "completed"
        feedback.save()
        is_update_succeed: bool = True
    return JsonResponse({"success": is_update_succeed})


def version_download(request, package_name, version):
    """
    Update download counter(s) using atomic operations to prevent race conditions
    and improve performance under high concurrent load.
    """
    from django.db.models import F

    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)

    # Atomic increment using F() expressions - prevents race conditions
    PluginVersion.objects.filter(pk=version.pk).update(downloads=F("downloads") + 1)

    # Atomic increment for plugin - single query, no race condition
    Plugin.objects.filter(pk=plugin.pk).update(downloads=F("downloads") + 1)

    remote_addr = parse_remote_addr(request)
    g = GeoIP2()

    country_code = "N/D"
    country_name = "N/D"

    if remote_addr:
        try:
            country_data = g.country(remote_addr)
            country_code = country_data["country_code"] or "N/D"
            country_name = country_data["country_name"] or "N/D"
        except Exception as e:  # AddressNotFoundErrors:
            pass

    download_record, created = PluginVersionDownload.objects.get_or_create(
        plugin_version=version,
        country_code=country_code,
        country_name=country_name,
        download_date=now().date(),
        defaults={"download_count": 1},
    )
    if not created:
        # Atomic increment for download tracking
        PluginVersionDownload.objects.filter(pk=download_record.pk).update(
            download_count=F("download_count") + 1
        )

    if not version.package.file.file.closed:
        version.package.file.file.close()
    zipfile = open(version.package.file.name, "rb")
    file_content = zipfile.read()
    response = HttpResponse(file_content, content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=%s-%s.zip" % (
        version.plugin.package_name,
        version.version,
    )
    return response


def version_detail(request, package_name, version):
    """
    Show version details
    """
    plugin = get_object_or_404(Plugin, package_name=package_name)
    version = get_object_or_404(PluginVersion, plugin=plugin, version=version)

    # Get security scan results if available
    try:
        security_scan = version.security_scan
        scan_badge = get_scan_badge_info(security_scan)
    except PluginVersionSecurityScan.DoesNotExist:
        security_scan = None
        scan_badge = get_scan_badge_info(None)

    return render(
        request,
        "plugins/version_detail.html",
        {
            "version": version,
            "security_scan": security_scan,
            "scan_badge": scan_badge,
        },
    )


###############################################

# Misc functions

###############################################

from django.views.decorators.cache import cache_page


def _add_patch_version(version: str, additional_patch: str) -> str:
    """To add patch number in version.

    e.g qgis version = 3.16 we add patch number (99) in versioning -> 3.16.99
    We use this versioning to query against PluginVersion min_qg_version,
    so that the query result will include all PluginVersion with
    minimum QGIS version 3.16 regardless of the patch number.
    """

    if not version:
        return version
    separator = "."
    v = version.split(separator)
    if len(v) == 2:
        two_first_segment = separator.join(v[:2])
        version = f"{two_first_segment}.{additional_patch}"
    return version


@cache_page(60 * 15)
def xml_plugins(request, qg_version=None, stable_only=None, package_name=None):
    """
    The XML file

    accepted parameters:

        * qgis: qgis version
        * stable_only: 0/1
        * package_name: Plugin.package_name

    """
    request_version = request.GET.get("qgis", "1.8.0")
    version_level = len(str(request_version).split(".")) - 1
    qg_version = (
        qg_version
        if qg_version is not None
        else vjust(request_version, fillchar="0", level=version_level, force_zero=True)
    )
    stable_only = (
        stable_only if stable_only is not None else request.GET.get("stable_only", "0")
    )
    package_name = (
        package_name
        if package_name is not None
        else request.GET.get("package_name", None)
    )

    filters = {}
    version_filters = {}
    object_list = []

    if qg_version:
        filters.update(
            {"pluginversion__min_qg_version__lte": _add_patch_version(qg_version, "99")}
        )
        version_filters.update(
            {"min_qg_version__lte": _add_patch_version(qg_version, "99")}
        )
        # For QGIS 4.x, only include plugins that support Qt6
        # and have min_qg_version >= 3.0. This has been set automatically
        # if it was not defined by the plugin author in the plugin metadata.
        # See: https://github.com/qgis/QGIS-Plugins-Website/issues/181
        # and https://github.com/qgis/QGIS-Plugins-Website/issues/185
        if qg_version.split(".")[0] == "004":
            filters.update({"pluginversion__supports_qt6": True})
            version_filters.update({"supports_qt6": True})
            filters.update(
                {
                    "pluginversion__min_qg_version__gte": vjust(
                        "3.0", fillchar="0", level=2, force_zero=True
                    )
                }
            )
            version_filters.update(
                {
                    "min_qg_version__gte": vjust(
                        "3.0", fillchar="0", level=2, force_zero=True
                    )
                }
            )
        else:
            filters.update(
                {
                    "pluginversion__max_qg_version__gte": _add_patch_version(
                        qg_version, "0"
                    )
                }
            )
            version_filters.update(
                {"max_qg_version__gte": _add_patch_version(qg_version, "0")}
            )

    # Get all versions for the given plugin)
    if package_name:
        filters.update({"package_name": package_name})
        try:
            plugin = Plugin.approved_objects.get(**filters)
            plugin_version_filters = copy.copy(version_filters)
            plugin_version_filters.update({"plugin": plugin})
            for plugin_version in PluginVersion.stable_objects.filter(
                **plugin_version_filters
            ):
                object_list.append(plugin_version)
            if stable_only != "1":
                for plugin_version in PluginVersion.experimental_objects.filter(
                    **plugin_version_filters
                ):
                    object_list.append(plugin_version)
        except Plugin.DoesNotExist:
            pass
    else:

        # Checked the cached plugins
        qgis_version = request.GET.get("qgis", None)
        qgis_filename = "plugins_{}.xml".format(qgis_version)
        folder_name = os.path.join(settings.MEDIA_ROOT, "cached_xmls")
        path_file = os.path.join(folder_name, qgis_filename)
        if os.path.exists(path_file):
            return HttpResponse(open(path_file).read(), content_type="application/xml")

        trusted_users_ids = list(
            zip(
                *User.objects.filter(
                    Q(
                        user_permissions__codename="can_approve",
                        user_permissions__content_type__app_label="plugins",
                    )
                    | Q(is_superuser=True)
                )
                .distinct()
                .values_list("id")
            )
        )[0]
        qs = Plugin.approved_objects.filter(**filters).annotate(
            is_trusted=RawSQL(
                "%s.created_by_id in (%s)"
                % (
                    Plugin._meta.db_table,
                    (",").join([str(tu) for tu in trusted_users_ids]),
                ),
                (),
            )
        )
        for plugin in qs:
            plugin_version_filters = copy.copy(version_filters)
            plugin_version_filters.update({"plugin_id": plugin.pk})
            try:
                data = PluginVersion.stable_objects.filter(**plugin_version_filters)[0]
                setattr(data, "is_trusted", plugin.is_trusted)
                object_list.append(data)
            except IndexError:
                pass
            if stable_only != "1":
                try:
                    data = PluginVersion.experimental_objects.filter(
                        **plugin_version_filters
                    )[0]
                    setattr(data, "is_trusted", plugin.is_trusted)
                    object_list.append(data)
                except IndexError:
                    pass

    return render(
        request,
        "plugins/plugins.xml",
        {"object_list": object_list},
        content_type="text/xml",
    )


@cache_page(60 * 15)
def xml_plugins_new(request, qg_version=None, stable_only=None, package_name=None):
    """
    The XML file

    accepted parameters:

        * qgis: qgis version
        * stable_only: 0/1
        * package_name: Plugin.package_name

    """
    request_version = request.GET.get("qgis", "1.8.0")
    version_level = len(str(request_version).split(".")) - 1
    qg_version = (
        qg_version
        if qg_version is not None
        else vjust(request_version, fillchar="0", level=version_level, force_zero=True)
    )
    stable_only = (
        stable_only if stable_only is not None else request.GET.get("stable_only", "0")
    )
    package_name = (
        package_name
        if package_name is not None
        else request.GET.get("package_name", None)
    )

    filters = {}
    version_filters = {}
    object_list = []

    if qg_version:
        filters.update(
            {"pluginversion__min_qg_version__lte": _add_patch_version(qg_version, "99")}
        )
        version_filters.update(
            {"min_qg_version__lte": _add_patch_version(qg_version, "99")}
        )
        # For QGIS 4.x, only include plugins that support Qt6
        # and have min_qg_version >= 3.0. This has been set automatically
        # if it was not defined by the plugin author in the plugin metadata.
        # See: https://github.com/qgis/QGIS-Plugins-Website/issues/181
        # and https://github.com/qgis/QGIS-Plugins-Website/issues/185
        if qg_version.split(".")[0] == "004":
            filters.update({"pluginversion__supports_qt6": True})
            version_filters.update({"supports_qt6": True})
            filters.update(
                {
                    "pluginversion__min_qg_version__gte": vjust(
                        "3.0", fillchar="0", level=2, force_zero=True
                    )
                }
            )
            version_filters.update(
                {
                    "min_qg_version__gte": vjust(
                        "3.0", fillchar="0", level=2, force_zero=True
                    )
                }
            )
        else:
            filters.update(
                {
                    "pluginversion__max_qg_version__gte": _add_patch_version(
                        qg_version, "0"
                    )
                }
            )
            version_filters.update(
                {"max_qg_version__gte": _add_patch_version(qg_version, "0")}
            )

    # Get all versions for the given plugin
    if package_name:
        filters.update({"package_name": package_name})
        try:
            plugin = Plugin.approved_objects.get(**filters)
            plugin_version_filters = copy.copy(version_filters)
            plugin_version_filters.update({"plugin": plugin})
            for plugin_version in PluginVersion.stable_objects.filter(
                **plugin_version_filters
            ):
                object_list.append(plugin_version)
            if stable_only != "1":
                for plugin_version in PluginVersion.experimental_objects.filter(
                    **plugin_version_filters
                ):
                    object_list.append(plugin_version)
        except Plugin.DoesNotExist:
            pass
        object_list_new = object_list
    else:

        # Fast lane: uses raw queries

        trusted_users_ids = """
        (SELECT DISTINCT "auth_user"."id"
            FROM "auth_user"
            LEFT OUTER JOIN "auth_user_user_permissions"
                ON ( "auth_user"."id" = "auth_user_user_permissions"."user_id" )
            LEFT OUTER JOIN "auth_permission"
                ON ( "auth_user_user_permissions"."permission_id" = "auth_permission"."id" )
            LEFT OUTER JOIN "django_content_type"
                ON ( "auth_permission"."content_type_id" = "django_content_type"."id" )
        WHERE (("auth_permission"."codename" = 'can_approve'
            AND "django_content_type"."app_label" = 'plugins')
            OR "auth_user"."is_superuser" = True))
        """

        # Check if QGIS version is 4.x
        is_qgis_4 = qg_version.split(".")[0] == "004"

        if is_qgis_4:
            # For QGIS 4.x, only include plugins that support Qt6 and have min_qg_version >= 3.0
            sql = """
            SELECT DISTINCT ON (pv.plugin_id) pv.*,
            pv.created_by_id IN %(trusted_users_ids)s AS is_trusted
                FROM %(pv_table)s pv
                WHERE (
                    pv.approved = True
                    AND pv."min_qg_version" <= '%(qg_version_with_patch_99)s'
                    AND pv."min_qg_version" >= '%(min_qg_version_3_0)s'
                    AND pv.supports_qt6 = True
                    AND pv.experimental = %(experimental)s
                )
                ORDER BY pv.plugin_id, pv.version DESC
            """
        else:
            sql = """
            SELECT DISTINCT ON (pv.plugin_id) pv.*,
            pv.created_by_id IN %(trusted_users_ids)s AS is_trusted
                FROM %(pv_table)s pv
                WHERE (
                    pv.approved = True
                    AND pv."max_qg_version" >= '%(qg_version_with_patch_0)s'
                    AND pv."min_qg_version" <= '%(qg_version_with_patch_99)s'
                    AND pv.experimental = %(experimental)s
                )
                ORDER BY pv.plugin_id, pv.version DESC
            """

        sql_params = {
            "pv_table": PluginVersion._meta.db_table,
            "p_table": Plugin._meta.db_table,
            "qg_version_with_patch_0": _add_patch_version(qg_version, "0"),
            "qg_version_with_patch_99": _add_patch_version(qg_version, "99"),
            "experimental": "False",
            "trusted_users_ids": str(trusted_users_ids),
        }

        if is_qgis_4:
            sql_params["min_qg_version_3_0"] = vjust(
                "3.0", fillchar="0", level=2, force_zero=True
            )

        object_list_new = PluginVersion.objects.raw(sql % sql_params)

        if stable_only != "1":
            # Do the query
            object_list_new = [o for o in object_list_new]

            sql_params["experimental"] = "True"
            object_list_new += [o for o in PluginVersion.objects.raw(sql % sql_params)]

    return render(
        request,
        "plugins/plugins.xml",
        {"object_list": object_list_new},
        content_type="text/xml",
    )
