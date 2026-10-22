from importlib import import_module

Migration = import_module("preferences.migrations.0001_initial").Migration
