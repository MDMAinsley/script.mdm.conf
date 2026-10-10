"""Explicit connection/file-size preferences with a separate local undo record."""
import json
import math
import re
import xbmcaddon
import xbmcgui
from . import builds,status

MINIMUM={status.FLIX:(0,5,0),status.LINK:(0,3,0)}
DEFAULTS={'device_connection_mbps':'0','device_max_size_gib':'0','device_source_order':'Quality',
          'device_unknown_size':'Show','device_slow_sources':'Show','device_unknown_bitrate':'Show'}
OPTIONS={'device_source_order':('Quality','Connection','Smallest'),'device_unknown_size':('Show','Hide'),
         'device_slow_sources':('Show','Hide'),'device_unknown_bitrate':('Show','Hide')}

def valid(key,value,empty=False):
    if not isinstance(value,str):return False
    if empty and value=='':return True
    if key in OPTIONS:return value in OPTIONS[key]
    return key in ('device_connection_mbps','device_max_size_gib') and bool(re.fullmatch(r'\d{1,5}(?:\.\d{1,3})?',value)) and 0<=float(value)<=10000

def preferences():
    own=xbmcaddon.Addon('script.mdm.conf');values={key:own.getSetting(key) or default for key,default in DEFAULTS.items()}
    validate(values);return values

def validate(values,empty=False):
    if not isinstance(values,dict) or set(values)!=set(DEFAULTS) or not all(valid(key,value,empty) for key,value in values.items()):
        raise builds.BuildError('Choose valid connection preferences: numeric values 0–10000 with up to three decimal places; use the listed ordering and Show/Hide choices.')

def ready():
    records=status.inventory()
    for identifier,minimum in MINIMUM.items():
        row=records[identifier];match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)',row['version'])
        if row['state']!='enabled' or not match or tuple(map(int,match.groups()))<minimum:
            raise builds.BuildError('Update and enable Flix 0.5.0 and Link 0.3.0 before applying connection preferences.')

def path():return builds.profile()/'connection-preferences.json'

def journal():
    if not path().exists():return None
    try:
        data=json.loads(path().read_text(encoding='utf-8'))
        if data.get('format')!=1 or data.get('state') not in ('pending','applied','undone') or set(data['before'])!=set(MINIMUM):raise ValueError()
        for values in data['before'].values():validate(values,empty=True)
        return data
    except Exception:raise builds.BuildError('Connection recovery record is unreadable. Preserve it before trying again.') from None

def save(data):builds.atomic(path(),builds.encode(data))

def same(key,left,right):
    if left==right:return True
    return key not in OPTIONS and valid(key,left) and valid(key,right) and float(left)==float(right)

def write(identifier,key,value):
    if identifier not in MINIMUM or not valid(key,value,empty=True):raise builds.BuildError('Invalid connection setting.')
    target=xbmcaddon.Addon(identifier);target.setSetting(key,value)
    if not same(key,target.getSetting(key),value):raise builds.BuildError('Connection setting could not be verified: '+identifier+' / '+key)

def rollback(data):
    failures=[]
    for identifier,values in data['before'].items():
        for key,value in values.items():
            try:write(identifier,key,value)
            except Exception:failures.append(identifier+' / '+key)
    data['state']='pending' if failures else 'undone';save(data)
    if failures:raise builds.BuildError('Connection recovery is still needed for: '+', '.join(failures))

def apply(values):
    validate(values)
    with builds.editing():
        ready();previous=journal();restore=builds.journal()
        if previous and previous['state']=='pending':raise builds.BuildError('Undo interrupted connection preferences first.')
        if restore and restore['state']=='pending':raise builds.BuildError('Recover the previous build restore first.')
        before={identifier:{key:xbmcaddon.Addon(identifier).getSetting(key) for key in DEFAULTS} for identifier in MINIMUM}
        for settings in before.values():validate(settings,empty=True)
        data={'format':1,'state':'pending','before':before};save(data)
        try:
            for identifier in MINIMUM:
                for key,value in values.items():write(identifier,key,value)
            data['state']='applied';save(data)
        except Exception:
            rollback(data)
            raise builds.BuildError('Connection preferences stopped; previous values were restored.') from None

def undo():
    with builds.editing(recovery=True):
        ready();data=journal()
        if not data or data['state']=='undone':raise builds.BuildError('No connection preferences need undo.')
        rollback(data)

def describe(values):
    labels={'device_connection_mbps':'Connection Mbps (0 = off)','device_max_size_gib':'Maximum reported GiB (0 = unlimited)',
            'device_source_order':'Order within debrid/free groups','device_unknown_size':'Unknown size with active size cap',
            'device_slow_sources':'Above estimated connection budget','device_unknown_bitrate':'Unknown bitrate with active connection'}
    return '\n'.join(labels[key]+': '+values[key] for key in DEFAULTS)

def explanation():
    return ('Debrid results stay first. Connection ordering prefers estimated fits, then unknown, then above-budget sources within each access group. Smaller reported files are preferred in Smallest mode.\n'
            'A positive size cap filters before ranking; unknown-size Hide only acts with that cap. Connection Hide choices only act when speed is positive.\n'
            'Average bitrate uses reported size and title duration; 25% of entered speed is reserved. Unknown duration or episode-pack size means unknown bitrate. Peaks, host speed and buffering can differ; this is no stability guarantee or speed test.\n'
            'GiB = 1024^3 bytes; Mbps = 1,000,000 bits/s. Pack-size limits are conservative and may exclude packs with smaller episodes. Preferences stay on this device and are excluded from portable backups. Accounts, quality and performance profiles are preserved.')

def run():
    dialog=xbmcgui.Dialog()
    while True:
        choice=dialog.select('MDM Conf - Connection / file size',['Preview / apply preferences','Current connection preferences','Undo last application / recover interrupted preferences','Flix settings','Link settings'])
        if type(choice) is not int or choice<0:return False
        try:
            if choice==0:
                xbmcaddon.Addon('script.mdm.conf').openSettings();values=preferences()
                dialog.textviewer('MDM Conf - Connection preview',describe(values)+'\n\n'+explanation())
                if dialog.yesno('MDM Conf','Apply these connection and file-size preferences to Flix and Link?'):
                    apply(values);dialog.ok('MDM Conf','Preferences applied. Search again to refresh sources. Undo is available here.')
            elif choice==1:
                lines=[]
                for identifier in MINIMUM:
                    target=xbmcaddon.Addon(identifier);values={key:target.getSetting(key) or default for key,default in DEFAULTS.items()}
                    validate(values);lines.append(status.ADDONS[identifier]+'\n'+describe(values))
                dialog.textviewer('MDM Conf - Current connection preferences','\n\n'.join(lines)+'\n\n'+explanation())
            elif choice==2:
                if dialog.yesno('MDM Conf','Restore the preferences saved before the last connection application?'):
                    undo();dialog.ok('MDM Conf','Previous connection preferences restored.')
            elif choice in (3,4):xbmcaddon.Addon(status.FLIX if choice==3 else status.LINK).openSettings()
        except builds.BuildError as error:dialog.ok('MDM Conf',str(error))
        except Exception:dialog.ok('MDM Conf','Connection preferences are unavailable. Check addon versions and settings.')
