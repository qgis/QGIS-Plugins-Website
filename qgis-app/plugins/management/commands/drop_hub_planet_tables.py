from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Drops planet and hub tables from the database with confirmation'

    def handle(self, *args, **options):
        # List of table prefixes to remove
        table_prefixes = [
            'feedjack_',
            'geopackages_',
            'styles_',
            'models_',
            'layerdefinitions_',
            'wavefronts_',
        ]

        # Get a cursor to execute SQL commands
        with connection.cursor() as cursor:
            # Get the list of all tables in the database
            cursor.execute("""
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public';
            """)
            tables = [row[0] for row in cursor.fetchall()]

            # Iterate through all tables and drop those that match the prefixes
            for table in tables:
                if any(table.startswith(prefix) for prefix in table_prefixes):
                    # Ask for user confirmation
                    self.stdout.write(f'Found table: {table}')
                    confirmation = input(f'Are you sure you want to permanently delete the table "{table}"? This action cannot be undone. Type "yes" to confirm: ')

                    if confirmation.lower() == 'yes':
                        self.stdout.write(f'Dropping table: {table}')
                        cursor.execute(f"DROP TABLE IF EXISTS \"{table}\" CASCADE;")
                    else:
                        self.stdout.write(f'Skipping table: {table}')

        self.stdout.write(self.style.SUCCESS('Process completed. Tables with specified prefixes have been handled.'))