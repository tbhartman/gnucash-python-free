#!/usr/bin/env python2
"""gnucash-python-free

This is an attempt to get the functionality of gnucash-python
bindings without the overhead/hassle of those.
"""

import logging
import argparse
import sys
import os
import time
import gzip
import functools
import datetime
import tempfile
from xml.dom import minidom
import xml.etree.ElementTree

logging.basicConfig(level=0)
logger = logging.getLogger(__name__)
logger.setLevel(0)

def gncvalue_to_float(string):
    num,denom = map(float,string.split('/'))
    if denom < 0:
        value = num * (-denom)
    else:
        value = num / denom
    return value

class Transaction(object):
    def __init__(self,xmldom):
        self._xmldom = xmldom
    @property
    def timestamp(self):
        posted = self._xmldom.getElementsByTagName('trn:date-posted')[0]
        raw = posted.getElementsByTagName('ts:date')[0].firstChild.nodeValue
        date = raw[:-6]
        offset = int(raw[-5:]) / 100
        timestamp = datetime.datetime.strptime(date,'%Y-%m-%d %H:%M:%S')
        # ignoring UTC offset for now
        #timestamp -= offset * 60
        return timestamp
    @property
    def splits(self):
        splits = self._xmldom.getElementsByTagName('trn:splits')[0].getElementsByTagName('trn:split')
        accounts = [i.getElementsByTagName('split:account')[0].firstChild.nodeValue for i in splits]
        values = [i.getElementsByTagName('split:value')[0].firstChild.nodeValue for i in splits]
        values = map(gncvalue_to_float,values)
        return zip(accounts,values)

class Account(object):
    _parent = None
    _book = None
    def __init__(self,xmldom,parent=None):
        self._xmldom = xmldom
        if parent:
            self.set_parent(parent)
        self.children = set()
    @property
    def guid(self):
        me = self._xmldom.getElementsByTagName('act:id')[0].firstChild.nodeValue
        return me
    def __hash__(self):
        return int('0x'+self.guid,0)
    def _get_parent_guid(self):
        tags = self._xmldom.getElementsByTagName('act:parent')
        if tags:
            return tags[0].firstChild.nodeValue
        else:
            return None
    @property
    def name(self):
        return self._xmldom.getElementsByTagName('act:name')[0].firstChild.nodeValue
    @property
    def parent(self):
        return self._parent
    def set_parent(self,parent):
        if parent and self.parent and not parent == self.parent:
            raise Exception('Parent already set!')
        self._parent = parent
        parent.children.add(self)



class BookIOError(IOError):pass
class BookParseError(Exception):pass
class Book(object):
    filename = None
    _xmldom = None
    def __init__(self,filename):
        logging.debug('Checking for {:s}'.format(filename))
        if not os.path.exists(filename):
            raise BookIOError('No such file "{:s}"'.format(filename))
        self.filename = filename
        self._load()
        
    @property
    def is_compressed(self):
        f = gzip.GzipFile(self.filename)
        try:
            f.readline()
        except:
            compressed = False
        else:
            compressed = True
        f.close()
        return compressed
    
    def get_transactions(self):
        try:
            return self._transactions
        except AttributeError:
            txs = self._xmldom.getElementsByTagName('gnc:transaction')
            txs =  map(Transaction,txs)
            self._transactions = txs
            return txs


    def _load(self):
        if self.is_compressed:
            f = gzip.GzipFile(self.filename)
        else:
            f = open(self.filename)
        try:
            logger.info('start parse xml')
            self._xmldom = minidom.parse(f)
            logger.info('end parse xml')
        except Exception as e:
            raise BookParseError(*e.args)
        finally:
            f.close()
    def get_root_account(self):
        accounts = {}
        xml_accounts = self._xmldom.getElementsByTagName('gnc:account')
        all_accounts = map(Account,xml_accounts)
        for a in all_accounts:
            def temp(**kwargs):
                return self.get_account_balance(a.guid,**kwargs)
            a.get_balance = temp
        guid = [i.guid for i in all_accounts]
        accounts = dict(zip(guid,all_accounts))
        root = all_accounts.pop(0)
        for a in all_accounts:
            parent = a._get_parent_guid()
            if parent:
                a.set_parent(accounts[a._get_parent_guid()])
        return root
    def get_account_monthly_balance(self,guid,year,month):
        return self.get_account_balance(guid,
                                        start = datetime.datetime(year,month,1,0,0),
                                        end = datetime.datetime(year,month+1,1,0,0) + datetime.timedelta(-1e-3))
    def get_account_balance(self,guid,start=datetime.datetime(1,1,1),end=datetime.datetime(9999,1,1)):
        balance = 0
        for tx in self.get_transactions():
            if not (tx.timestamp >= start and tx.timestamp <= end):
                continue
            splits = tx.splits
            for id,value in splits:
                if id == guid:
                    balance += value
        return balance


    def _get_budgets(self, year, month):
        xmldom = self._xmldom.getElementsByTagName('gnc:budget')[0]
        assert xmldom.getAttribute('version') == u'2.0.0'
        budget_start_date = xmldom.getElementsByTagName('gdate')[0].firstChild.data
        budget_start_date = string_to_date(budget_start_date)
        request_date = ymd_tuple_to_date((year,month,1))
        slot_number = int((request_date - budget_start_date).days * 12/365.25)
        slots = xmldom.getElementsByTagName('slot')
        guids = [s.getElementsByTagName('slot:key')[0].firstChild.data for s in slots]
        budget = []
        for s in slots:
            sub_slots = s.getElementsByTagName('slot')
            keys = [ss.getElementsByTagName('slot:key')[0].firstChild.data for ss in sub_slots]
            keys = map(int,keys)
            try:
                index = keys.index(slot_number)
            except ValueError:
                value = 0.0
            else:
                value = sub_slots[index].getElementsByTagName('slot:value')[0].firstChild.data
                num,denom = map(float,value.split('/'))
                if denom < 0:
                    value = num * (-denom)
                else:
                    value = num / denom
            budget.append(value)
        budget = dict(zip(guids,budget))
        return budget


def ymd_tuple_to_date(t):
    return string_to_date('{:04d}-{:02d}-{:02d}'.format(*t))
def string_to_date(string):
    return datetime.datetime.strptime(string,'%Y-%m-%d')

