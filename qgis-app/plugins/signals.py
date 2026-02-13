from celery import shared_task
from haystack import signals
from haystack.exceptions import NotHandled


@shared_task
def update_search_index(action, instance_pk, app_label, model_name):
    """Async task to update search index"""
    from django.apps import apps

    try:
        model_class = apps.get_model(app_label, model_name)
        instance = model_class.objects.get(pk=instance_pk)

        from haystack import connection_router, connections

        using_backends = connection_router.for_write(instance=instance)

        for using in using_backends:
            try:
                index = connections[using].get_unified_index().get_index(model_class)
                if action == "update":
                    index.update_object(instance, using=using)
                elif action == "delete":
                    index.remove_object(instance, using=using)
            except NotHandled:
                pass

    except model_class.DoesNotExist:
        pass  # Instance was deleted
    except Exception as e:
        # Log error but don't fail
        import logging

        logging.error(f"Search index update failed: {e}")


class CelerySignalProcessor(signals.BaseSignalProcessor):
    """Signal processor that queues updates to Celery"""

    def handle_save(self, sender, instance, **kwargs):
        update_search_index.delay(
            "update", instance.pk, instance._meta.app_label, instance._meta.model_name
        )

    def handle_delete(self, sender, instance, **kwargs):
        update_search_index.delay(
            "delete", instance.pk, instance._meta.app_label, instance._meta.model_name
        )
