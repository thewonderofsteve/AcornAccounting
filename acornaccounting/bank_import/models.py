"""Models related to Bank Accounts & Imports."""
import importlib

from django.db import models

from core.models import AccountWrapper


class BankAccount(AccountWrapper):
    """A Communard-Visible Wrapper for an :class:`~accounts.models.Account`.

    .. attribute:: account

        The :class:`~accounts.model.Account` the BankAccount is linked to. This
        is the Account that will have it's Entries imported.

    .. attribute:: name

        A name for the Bank Account, used in forms.

    """

    VCB_CSV_IMPORTER = 'bank_import.importers.vcb.CSVImporter'
    BANK_NAMES_TO_IMPORTERS = (
        (VCB_CSV_IMPORTER, 'Virginia Community Bank'),
    )
    bank = models.CharField(
        blank=False, choices=BANK_NAMES_TO_IMPORTERS, max_length=100,
        help_text="The Bank this Account Belongs to. Used for importing data."
    )

    def get_importer_class(self):
        """Import and return the Importer to use for the Bank Account."""
        (module_name, class_name) = self.bank.rsplit(".", 1)
        return getattr(importlib.import_module(module_name), class_name)
