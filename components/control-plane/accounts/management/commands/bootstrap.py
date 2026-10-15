"""Provision or rotate the infrastructure account before serving requests."""

from django.core.management.base import BaseCommand
from common.stores import stores


class Command(BaseCommand):
    help = "Provision the infrastructure admin from its password file."

    def handle(self, **options):
        stores()
        self.stdout.write("Infrastructure admin is configured.")
