"""Views for Importing Bank Statements."""
import datetime
from django.shortcuts import render, redirect

from entries.models import Transaction, BankSpendingEntry, BankReceivingEntry

from .forms import (BankAccountForm, TransferImportFormSet,
                    SpendingImportFormSet, ReceivingImportFormSet)


def import_bank_statement(request):
    """Render the Import Upload Form, & the FormSets."""
    context = {}
    template_name = "bank_import/import_form.html"
    if request.method == 'POST' and request.POST.get('submit', '') == 'Import':
        account_form = BankAccountForm(request.POST, request.FILES)
        if account_form.is_valid():
            data = _parse_input_file(account_form)
            transfers, deposits, withdrawals = _group_data(data)
            account = account_form.cleaned_data['bank_account']
            matched_transfers, unmatched_transfers = _match_transactions(
                account, transfers)
            matched_deposits, unmatched_deposits = _match_transactions(
                account, deposits)
            matched_withdrawals, unmatched_withdrawals = _match_transactions(
                account, withdrawals)
            context['transfer_formset'] = TransferImportFormSet(
                prefix='transfer',
                initial=_build_initial_data(
                    _build_transfer, account, unmatched_transfers))
            context['withdrawal_formset'] = SpendingImportFormSet(
                prefix='withdrawal',
                initial=_build_initial_data(
                    _build_spending, account, unmatched_withdrawals))
            context['deposit_formset'] = ReceivingImportFormSet(
                prefix='deposit',
                initial=_build_initial_data(
                    _build_receiving, account, unmatched_deposits))
    elif request.method == 'POST' and request.POST.get('submit', '') == 'Save':
        transfer_formset = TransferImportFormSet(
            request.POST, prefix='transfer')
        withdrawal_formset = SpendingImportFormSet(
            request.POST, prefix='withdrawal')
        deposit_formset = ReceivingImportFormSet(
            request.POST, prefix='deposit')
        formsets_valid = (
            transfer_formset.is_valid() and withdrawal_formset.is_valid() and
            deposit_formset.is_valid())
        if formsets_valid:
            for form in transfer_formset.forms:
                form.save()
            for form in withdrawal_formset.forms:
                form.save()
            for form in deposit_formset.forms:
                form.save()
            return redirect('bank_import.views.import_bank_statement')
        else:
            context.update({'transfer_formset': transfer_formset,
                            'withdrawal_formset': withdrawal_formset,
                            'deposit_formset': deposit_formset})
    else:
        context['import_form'] = BankAccountForm()
    return render(request, template_name, context)


def _parse_input_file(account_form):
    account = account_form.cleaned_data['bank_account']
    import_file = account_form.cleaned_data['import_file']
    importer_class = account.get_importer_class()
    importer = importer_class(import_file)
    return importer.get_data()


def _group_data(data):
    """Group the input data into Transfers, Deposits, and withdrawals."""
    transfers = []
    deposits = []
    withdrawals = []
    for item in data:
        if 'transfer' in item['type']:
            transfers.append(item)
        elif item['type'] == 'deposit':
            deposits.append(item)
        else:
            withdrawals.append(item)
    return (transfers, deposits, withdrawals)


def _match_transactions(bank_account, items):
    """Try to match the data to existing Transactions/Entries."""
    matched = []
    unmatched = []
    date_fuzz = datetime.timedelta(days=7)
    for item in items:
        amount = item['amount']
        if 'deposit' in item['type']:
            amount = -1 * amount

        match = False
        if item['check_number'] not in ('', '0'):
            matches = Transaction.objects.filter(
                bankspendingentry__check_number=item['check_number'],
                account=bank_account.account, balance_delta=amount
            )
        else:
            matches = Transaction.objects.filter(
                date=item['date'], account=bank_account.account,
                balance_delta=amount)
        match = _find_match(matches, matched)

        if not match:
            matches = Transaction.objects.filter(
                date__gte=item['date'] - date_fuzz,
                date__lte=item['date'] + date_fuzz,
                account=bank_account.account, balance_delta=amount)
            match = _find_match(matches, matched)
        if not match:
            unmatched.append(item)
        else:
            matched.append(match)
    return matched, unmatched


def _find_match(matches, already_matched):
    """Return the first match that has not already been matched, or False."""
    for match in matches:
        if match not in already_matched:
            return match
    return False


def _build_initial_data(build_function, bank_account, items):
    return [build_function(bank_account.account.id, item) for item in items]


def _build_transfer(account_id, transfer):
    data = {
        'amount': abs(transfer['amount']),
        'date': transfer['date'],
        'memo': transfer['memo']
    }
    if 'deposit' in transfer['type']:
        data['destination'] = account_id
    else:
        data['source'] = account_id
    return data


def _build_spending(account_id, withdrawal):
    data = {
        'amount': abs(withdrawal['amount']),
        'date': withdrawal['date'],
        'memo': withdrawal['memo'],
        'ach_payment': withdrawal['check_number'] == '0',
        'account': account_id,
    }
    if not data['ach_payment']:
        data['check_number'] = withdrawal['check_number']
    if data['memo'] != '':
        matching_entries = BankSpendingEntry.objects.filter(
            memo__icontains=data['memo'], date__day=data['date'].day)
        for entry in matching_entries:
            if entry.transaction_set.count() == 1:
                transaction = entry.transaction_set.all()[0]
                data['expense_account'] = transaction.account.id
                data['payee'] = entry.payee
                break
        if 'expense_account' not in data:
            matching_entries = BankSpendingEntry.objects.filter(
                memo__icontains=data['memo'])
            for entry in matching_entries:
                if entry.transaction_set.count() == 1:
                    transaction = entry.transaction_set.all()[0]
                    data['expense_account'] = transaction.account.id
                    data['payee'] = entry.payee
                    break
    return data


def _build_receiving(account_id, deposit):
    data = {
        'amount': abs(deposit['amount']),
        'date': deposit['date'],
        'memo': deposit['memo'],
        'account': account_id,
    }
    if data['memo'] != '':
        matching_entries = BankReceivingEntry.objects.filter(
            memo__icontains=data['memo'], date__day=data['date'].day)
        for entry in matching_entries:
            if entry.transaction_set.count() == 1:
                transaction = entry.transaction_set.all()[0]
                data['receiving_account'] = transaction.account.id
                data['payor'] = entry.payor
                break
        if 'receiving_account' not in data:
            matching_entries = BankReceivingEntry.objects.filter(
                memo__icontains=data['memo'])
            for entry in matching_entries:
                if entry.transaction_set.count() == 1:
                    transaction = entry.transaction_set.all()[0]
                    data['receiving_account'] = transaction.account.id
                    data['payor'] = entry.payor
                    break
    return data
