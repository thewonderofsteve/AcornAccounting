from decimal import Decimal
import datetime

from django.core.urlresolvers import reverse
from django.db import models
from mptt.models import MPTTModel, TreeForeignKey
from django import forms


class BankAccountManager(models.Manager):
    def get_query_set(self):
        return super(BankAccountManager, self).get_query_set().filter(bank=True)


class BaseAccountModel(MPTTModel):
    """
    Abstract class storing common attributes of Headers and Accounts
    """
    ASSET = 1
    LIABILITY = 2
    EQUITY = 3
    INCOME = 4
    COST_OF_SALES = 5
    EXPENSE = 6
    OTHER_INCOME = 7
    OTHER_EXPENSE = 8
    TYPE_CHOICES = (
        (ASSET, 'Asset'),
        (LIABILITY, 'Liability'),
        (EQUITY, 'Equity'),
        (INCOME, 'Income'),
        (COST_OF_SALES, 'Cost of Sales'),
        (EXPENSE, 'Expense'),
        (OTHER_INCOME, 'Other Income'),
        (OTHER_EXPENSE, 'Other Expense')
    )

    name = models.CharField(max_length=50, unique=True)
    type = models.PositiveSmallIntegerField(choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    slug = models.SlugField(help_text="Unique identifier used in URL naming",
                            unique=True)

    class Meta:
        abstract = True

    class MPTTMeta:
        order_insertion_by = ['name']

    def account_number(self):
        siblings = self.get_siblings(include_self=True).order_by('name')
        number = list(siblings).index(self) + 1
        return number

    def flip_balance(self):
        if self.type in (self.ASSET, self.EXPENSE, self.COST_OF_SALES, self.OTHER_EXPENSE):
            return True
        else:
            return False


class Header(BaseAccountModel):
    """
    Groups Accounts Together
    """

    parent = TreeForeignKey('self', blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __unicode__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('accounts.views.show_accounts_chart', args=[str(self.slug)])

    def save(self, *args, **kwargs):
        super(Header, self).save(*args, **kwargs)

    def get_full_number(self):
        """Traverses parent Headers to generate a full account number"""
        full_number = ""
        if self.parent:
            ancestors = self.parent.get_ancestors(include_self=True)
            for ancestor in ancestors:
                full_number += "{0:02d}".format(ancestor.account_number())
        full_number += "{0:02d}".format(self.account_number())
        return full_number
    get_full_number.short_description = "Number"

    def get_account_balance(self):
        ''''Traverses child Headers and Accounts to generate the current balance'''
        balance = Decimal("0.00")
        descendants = self.get_descendants()
        for header in descendants:
            accounts = header.account_set.all()
            for account in accounts:
                balance += account.balance
        for account in self.account_set.all():
            balance += account.balance
        if self.flip_balance():
            balance = -1 * balance
        return balance


class Account(BaseAccountModel):
    """
    Holds information on Accounts
    """
    balance = models.DecimalField(help_text="Positive balance is a credit, negative is a debit",
                                  max_digits=19, decimal_places=4, default="0.00",
                                  editable=False)
    parent = models.ForeignKey(Header)
    active = models.BooleanField(default=True)
    bank = models.BooleanField(default=False, help_text="Adds account to Bank Register")

    objects = models.Manager()
    banks = BankAccountManager()

    class Meta:
        ordering = ['name']

    def __unicode__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('accounts.views.show_account_detail', args=[str(self.slug)])

    def get_full_number(self):
        """Traverses parent Headers to generate a full account number"""
        full_number = ""
        ancestors = self.parent.get_ancestors(include_self=True)
        for ancestor in ancestors:
            full_number += "{0:02d}".format(ancestor.account_number())
        full_number += "-{0:02d}".format(self.account_number())
        return full_number
    get_full_number.short_description = "Number"

    def get_balance(self):
        if self.flip_balance():
            return self.balance * -1
        else:
            return self.balance


class BaseJournalEntry(models.Model):
    """
    Groups a series of Transactions together
    """
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True, default=datetime.datetime.now)
    updated_at = models.DateTimeField(auto_now=True, default=datetime.datetime.now)
    memo = models.CharField(max_length=60)

    class Meta:
        abstract = True
        verbose_name_plural = "journal entries"
        ordering = ['date', 'id']

    def __unicode__(self):
        return self.memo

    def get_absolute_url(self):
        return reverse('accounts.views.show_journal_entry', args=[str(self.id)])

    def get_edit_url(self):
        return reverse('accounts.views.add_journal_entry', args=[str(self.id)])

    def get_number(self):
        return "GJ#{0:06d}".format(self.id)


class JournalEntry(BaseJournalEntry):
    pass


class BankSpendingEntry(BaseJournalEntry):
    '''
    Holds information about a Check or ACH payment for a Bank Account
    Main Transaction is linked to a Bank Account
    '''
    check_number = models.CharField(max_length=10, unique=True, blank=True, null=True)
    ach_payment = models.BooleanField(default=False, help_text="Invalidates Check Number")
    payee = models.CharField(max_length=20, blank=True, null=True)
    void = models.BooleanField(default=False, help_text="Refunds Associated Transactions.")

    class Meta:
        verbose_name_plural = "bank spending entries"
        ordering = ['date', 'id']

    def __unicode__(self):
        return self.memo

    def get_absolute_url(self):
        return reverse('accounts.views.show_bank_entry', kwargs={'journal_id': str(self.id),
                                                                 'journal_type': 'CD'})

    def get_edit_url(self):
        return reverse('accounts.views.add_bank_entry', args=['CD', str(self.id)])

    def save(self, *args, **kwargs):
        if self.ach_payment:
            self.check_number = None
        super(BankSpendingEntry, self).save(*args, **kwargs)

    def get_number(self):
        if self.ach_payment:
            return "##ACH##"
        else:
            return "CD#{0:06d}".format(int(self.check_number))


class BankReceivingEntry(BaseJournalEntry):
    payor = models.CharField(max_length=50)

    class Meta:
        verbose_name_plural = "bank receiving entries"
        ordering = ['date', 'id']

    def __unicode__(self):
        return self.memo

    def get_absolute_url(self):
        return reverse('accounts.views.show_bank_entry', kwargs={'journal_id': str(self.id),
                                                                 'journal_type': 'CR'})

    def get_edit_url(self):
        return reverse('accounts.views.add_bank_entry', args=['CR', str(self.id)])

    def get_number(self):
        return "CR#{0:06d}".format(self.id)


class Transaction(models.Model):
    """
    Holds information about a single Transaction
    """
    journal_entry = models.ForeignKey(JournalEntry, blank=True, null=True)
    bankspend_entry = models.ForeignKey(BankSpendingEntry, blank=True, null=True)
    bankreceive_entry = models.ForeignKey(BankReceivingEntry, blank=True, null=True)
    account = models.ForeignKey(Account)
    detail = models.CharField(max_length=50, help_text="Short description", blank=True)
    balance_delta = models.DecimalField(help_text="Positive balance is a credit, negative is a debit",
                                        max_digits=19, decimal_places=4)
    event = models.PositiveIntegerField(blank=True, null=True)
    reconciled = models.BooleanField(default=False)
    last_account = models.IntegerField(editable=False, default=None, blank=True,
                                       null=True)
    last_delta = models.DecimalField(help_text="Positive balance is a credit, negative is a debit",
                                     max_digits=19, decimal_places=4,
                                     default="0.00", editable=False)

    class Meta:
        ordering = ['journal_entry__date', 'id']

    def __unicode__(self):
        return self.detail

    def save(self, *args, **kwargs):
        '''Changes Account balances if Account or balance_delta is changed'''
        if not self.last_account:
            self.last_account = self.account.id

        balance_change = self.last_delta != self.balance_delta
        last_account = Account.objects.get(id=self.last_account)
        account_change = last_account != self.account
        if balance_change and account_change:
            last_account.balance = last_account.balance - Decimal(self.last_delta)
            self.account.balance = self.account.balance + self.balance_delta
            self.last_account = self.account.id
            self.last_delta = self.balance_delta
            last_account.save()
        elif account_change:
            last_account.balance = last_account.balance - self.balance_delta
            self.account.balance = self.account.balance + self.balance_delta
            self.last_account = self.account.id
            last_account.save()
        elif balance_change:
            self.account.balance = self.account.balance - Decimal(self.last_delta) + self.balance_delta
            self.last_delta = self.balance_delta
        self.account.save()
        super(Transaction, self).save(*args, **kwargs)

    def clean(self):
        '''Make sure a Journal or Bank Entry is assigned'''
        super(Transaction, self).clean()
        if not (self.journal_entry or self.bankreceive_entry or self.bankspend_entry):
            raise forms.ValidationError("A Journal or Bank Entry must be assigned.")

    def delete(self):
        '''Refunds Transaction before deleting from database.'''
        self.account.balance = self.account.balance - self.balance_delta
        self.account.save()
        super(Transaction, self).delete()

    def get_date(self):
        return self.get_journal_entry().date

    def get_entry_number(self):
        return self.get_journal_entry().get_number()

    def get_final_account_balance(self):
        """Returns Account balance after transaction has occured."""
        date = self.get_date()
        acct_balance = self.account.balance
        query = (models.Q(journal_entry__date__gt=date) | models.Q(bankspend_entry__date__gt=date) |
                 models.Q(bankreceive_entry__date__gt=date) |
                ((models.Q(journal_entry__date=date) | models.Q(bankspend_entry__date=date) |
                  models.Q(bankreceive_entry__date=date))
                    & models.Q(id__gt=self.id)))
        newer_transactions = self.account.transaction_set.filter(query)
        for transaction in newer_transactions:
            acct_balance += (-1 * (transaction.balance_delta))
        if self.account.flip_balance():
            acct_balance = -1 * acct_balance
        return acct_balance

    def get_initial_account_balance(self):
        final = self.get_final_account_balance()
        if self.account.flip_balance():
            return final + self.balance_delta
        else:
            return final - self.balance_delta

    def get_journal_entry(self):
        if self.journal_entry:
            return self.journal_entry
        elif self.bankspend_entry:
            return self.bankspend_entry
        elif self.bankreceive_entry:
            return self.bankreceive_entry

    def get_memo(self):
        return self.get_journal_entry().memo
