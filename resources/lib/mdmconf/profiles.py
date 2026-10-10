"""Explicit, reversible device-local tuning. Never copies account settings."""
import json
import re
import xbmcgui
import xbmcaddon
from . import builds,status

MINIMUM={status.FLIX:(0,4,0),status.LINK:(0,2,0)}
KEYS={'device_quality_max','device_unknown_quality','device_workers','device_search_timeout','device_request_timeout','device_artwork'}

def facts():
    total=status.positive(status.label('System.Memory(total)'))
    height=status.positive(status.label('System.ScreenHeight'))
    return {'total':total,'profile':'Low memory' if total is not None and total<=2048 else 'Balanced',
            'suggestion':'4K' if height and height>=2160 else '1080p' if height and height>=1080 else '720p' if height else 'Unlimited'}

def plan(profile,quality,unknown):
    if profile not in ('Low memory','Balanced') or quality not in ('Unlimited','720p','1080p','4K') or unknown not in ('Show','Hide'):
        raise builds.BuildError('Choose valid device preferences.')
    low=profile=='Low memory';result={}
    for identifier in MINIMUM:
        result[identifier]={'device_quality_max':quality,'device_unknown_quality':unknown,
            'device_workers':str((2 if identifier==status.FLIX else 1) if low else (6 if identifier==status.FLIX else 5)),
            'device_search_timeout':str(90 if low else (45 if identifier==status.FLIX else 30)),
            'device_request_timeout':str(30 if low else 15)}
    result[status.FLIX]['device_artwork']='Light' if low else 'Standard'
    return result

def ready():
    records=status.inventory()
    for identifier,minimum in MINIMUM.items():
        row=records[identifier];match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)',row['version'])
        if row['state']!='enabled' or not match or tuple(map(int,match.groups()))<minimum:
            raise builds.BuildError('Update and enable Flix 0.4.0 and Link 0.2.0 before applying a profile.')

def path():return builds.profile()/'device-profile.json'

def journal():
    if not path().exists():return None
    try:
        data=json.loads(path().read_text(encoding='utf-8'))
        assert data['format']==1 and data['state'] in ('pending','applied','undone')
        assert isinstance(data['before'],dict) and set(data['before'])==set(MINIMUM)
        for identifier,values in data['before'].items():
            expected=KEYS if identifier==status.FLIX else KEYS-{'device_artwork'}
            assert set(values)==expected
            for key,value in values.items():
                assert valid(key,value,empty=True)
        return data
    except Exception:raise builds.BuildError('Device recovery data is unreadable. Preserve it before trying again.') from None

def valid(key,value,empty=False):
    if not isinstance(value,str):return False
    if empty and value=='':return True
    if key=='device_quality_max':return value in ('Unlimited','720p','1080p','4K')
    if key=='device_unknown_quality':return value in ('Show','Hide')
    if key=='device_artwork':return value in ('Light','Standard')
    bounds={'device_workers':(1,6),'device_search_timeout':(10,120),'device_request_timeout':(10,60)}
    return key in bounds and bool(re.fullmatch(r'\d{1,3}',value)) and bounds[key][0]<=int(value)<=bounds[key][1]

def save(data):builds.atomic(path(),builds.encode(data))

def write(identifier,key,value):
    if identifier not in MINIMUM or key not in KEYS or not valid(key,value,True):raise builds.BuildError('Invalid device setting.')
    target=xbmcaddon.Addon(identifier);target.setSetting(key,value)
    if target.getSetting(key)!=value:raise builds.BuildError('Device setting could not be verified: '+identifier+' / '+key)

def rollback(data):
    failures=[]
    for identifier,values in data['before'].items():
        for key,value in values.items():
            try:write(identifier,key,value)
            except Exception:failures.append(identifier+' / '+key)
    data['state']='pending' if failures else 'undone';save(data)
    if failures:raise builds.BuildError('Device recovery is still needed for: '+', '.join(failures))

def apply(values):
    # Reject arbitrary mappings before obtaining a lock or writing any setting.
    assert set(values)==set(MINIMUM)
    for identifier,settings in values.items():
        assert set(settings)==(KEYS if identifier==status.FLIX else KEYS-{'device_artwork'})
        assert all(valid(key,value) for key,value in settings.items())
    with builds.editing():
        ready();previous=journal()
        if previous and previous['state']=='pending':raise builds.BuildError('Undo the interrupted device profile first.')
        restore=builds.journal()
        if restore and restore['state']=='pending':raise builds.BuildError('Recover the previous build restore first.')
        before={identifier:{key:xbmcaddon.Addon(identifier).getSetting(key) for key in settings} for identifier,settings in values.items()}
        if not all(valid(key,value,True) for settings in before.values() for key,value in settings.items()):
            raise builds.BuildError('Current device settings are invalid. Correct them in addon settings first.')
        data={'format':1,'state':'pending','before':before};save(data)
        try:
            for identifier,settings in values.items():
                for key,value in settings.items():write(identifier,key,value)
            data['state']='applied';save(data)
        except Exception:
            rollback(data)
            raise builds.BuildError('Profile stopped; previous device settings were restored.') from None

def undo():
    with builds.editing(recovery=True):
        ready();data=journal()
        if not data or data['state']=='undone':raise builds.BuildError('No device profile needs undo.')
        rollback(data)

def report(values):
    detected=facts()
    lines=['Total memory: '+(str(detected['total'])+' MB' if detected['total'] else 'unknown'),
           'Recommended profile: '+detected['profile'],
           'Current Kodi screen suggestion: '+detected['suggestion'],
           'Screen size does not prove TV or decoder capability. Choose your own maximum.',
           'Unknown quality can exceed the limit when Show is selected.',
           'Limits use reported quality; providers may retrieve higher quality before filtering.',
           'External scraper requests already running may finish after a search ends.',
           'Profiles stay on this device; portable backups exclude them.','']
    for identifier,settings in values.items():
        lines.append(status.ADDONS[identifier])
        lines.extend(key.replace('device_','').replace('_',' ')+': '+value for key,value in sorted(settings.items()))
    return '\n'.join(lines)

def run():
    dialog=xbmcgui.Dialog()
    while True:
        choice=dialog.select('MDM Conf - Device profiles',['Preview / apply profile','Current device settings','Undo last profile / recover interrupted profile','Flix settings','Link settings'])
        if choice<0:return False
        try:
            if choice==0:
                detected=facts();own=xbmcaddon.Addon('script.mdm.conf')
                own.openSettings()
                profile=own.getSetting('device_profile') or 'Recommended'
                quality=own.getSetting('device_quality_max') or 'Suggested'
                values=plan(detected['profile'] if profile=='Recommended' else profile,detected['suggestion'] if quality=='Suggested' else quality,own.getSetting('device_unknown_quality') or 'Show')
                dialog.textviewer('MDM Conf - Profile preview',report(values))
                if dialog.yesno('MDM Conf','Apply these device settings to Flix and Link? Account and provider choices are preserved.'):
                    apply(values);dialog.ok('MDM Conf','Profile applied. Search again to refresh sources. Undo is available here.')
            elif choice==1:
                values={identifier:{key:xbmcaddon.Addon(identifier).getSetting(key) for key in KEYS if key!='device_artwork' or identifier==status.FLIX} for identifier in MINIMUM}
                dialog.textviewer('MDM Conf - Current device settings',report(values))
            elif choice==2:
                if dialog.yesno('MDM Conf','Restore the device settings saved before the last profile?'):
                    undo();dialog.ok('MDM Conf','Previous device settings restored.')
            elif choice in (3,4):xbmcaddon.Addon(status.FLIX if choice==3 else status.LINK).openSettings()
        except builds.BuildError as error:dialog.ok('MDM Conf',str(error))
        except Exception:dialog.ok('MDM Conf','Device profile is unavailable. Check addon versions and settings.')
