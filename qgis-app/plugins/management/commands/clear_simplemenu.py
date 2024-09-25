from django.core.management.base import BaseCommand
from django.apps import apps

class Command(BaseCommand):
    help = 'Delete all objects from all models in the simplemenu app'

    def handle(self, *args, **kwargs):
        # Get all models in the 'simplemenu' app
        app_models = apps.get_app_config('simplemenu').get_models()

        for model in app_models:
            # Delete all objects in the model
            model_name = model.__name__
            try:
                deleted_count, _ = model.objects.all().delete()
                self.stdout.write(f'Successfully deleted {deleted_count} objects from {model_name}.')
            except Exception as e:
                self.stderr.write(f'Failed to delete objects from {model_name}: {str(e)}')