"""Read-only readiness. Never return credentials or exception messages."""
import json
import re
import xbmc
import xbmcaddon

FLIX='plugin.video.mdm.flix';LINK='script.mdm.link';CORE='script.mdm.core';COCO='script.module.cocoscrapers'
ADDONS={CORE:'MDM Core',FLIX:'MDM Flix',LINK:'MDM Link','script.mdm.conf':'MDM Conf','skin.mdm.skin':'MDM Skin',
        'repository.mdm.repo':'MDM Repo','repository.mdm.repo.dev':'MDM Repo (Development)',COCO:'CocoScrapers'}

def addon(identifier):
    if identifier not in ADDONS:return None
    try:return xbmcaddon.Addon(identifier)
    except Exception:return None

def setting(identifier,key):
    target=addon(identifier)
    if target is None:return None
    try:
        value=target.getSetting(key)
        return value if isinstance(value,str) else None
    except Exception:return None

def enabled_setting(identifier,key,default=True):
    value=setting(identifier,key)
    if value=='':return default
    if value=='true':return True
    if value=='false':return False
    return None

def credential_present(identifier,key):
    value=setting(identifier,key)
    return bool(value.strip()) if value is not None else None

def version(value):
    return value if isinstance(value,str) and re.fullmatch(r'[0-9][A-Za-z0-9.+_-]{0,63}',value) else 'unknown'

def inventory():
    records={};complete=False
    try:
        request={'jsonrpc':'2.0','id':1,'method':'Addons.GetAddons','params':{'enabled':'all','installed':True,'properties':['version','enabled']}}
        reply=json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        result=reply.get('result') if isinstance(reply,dict) and 'error' not in reply else None
        if isinstance(result,dict) and isinstance(result.get('addons',[]),list):
            limits=result.get('limits',{})
            complete=not isinstance(limits,dict) or limits.get('end',0)>=limits.get('total',0)
            for row in result.get('addons',[]):
                if isinstance(row,dict) and row.get('addonid') in ADDONS:
                    records[row['addonid']]={'state':'enabled' if row.get('enabled') is True else 'disabled' if row.get('enabled') is False else 'unknown','version':version(row.get('version'))}
    except Exception:complete=False
    for identifier in ADDONS:
        if identifier in records:continue
        target=addon(identifier)
        if target is None:records[identifier]={'state':'missing' if complete else 'unknown','version':'unknown'}
        else:
            try:current=version(target.getAddonInfo('version'))
            except Exception:current='unknown'
            records[identifier]={'state':'unknown','version':current}
    return records

def account(identifier):
    active=enabled_setting(identifier,'alldebrid_enabled')
    present=credential_present(identifier,'alldebrid_api_key')
    if active is None or present is None:return 'unknown'
    if not active:return 'disabled'
    return 'configured' if present else 'needs authorisation'

def snapshot():
    records=inventory();issues=[];provider=setting(FLIX,'scraper_provider')
    provider=provider or 'Auto' if provider is not None else 'unknown'
    if provider not in ('Auto','CocoScrapers','MDM Link'):provider='unknown'
    for identifier in (CORE,FLIX):
        if records[identifier]['state']!='enabled':issues.append((f"{ADDONS[identifier]}: {records[identifier]['state']}. Install/enable it in Kodi Add-ons.",'addons'))
    token=credential_present(FLIX,'tmdb_token');key=credential_present(FLIX,'tmdb_api_key')
    tmdb='configured' if token or key else 'unknown' if token is None or key is None else 'needs credentials'
    if tmdb!='configured':issues.append(('TMDB: '+tmdb+'. Open Flix settings to configure the catalogue.','flix_settings'))
    target=LINK if provider=='MDM Link' else COCO
    service_owner=LINK if provider=='MDM Link' else FLIX
    service=account(service_owner);mode='Debrid';available=None
    if provider=='unknown':issues.append(('Selected provider could not be read. Choose MDM Link or CocoScrapers in Flix settings.','flix_settings'))
    if records[target]['state']!='enabled':issues.append((f"{ADDONS[target]}: {records[target]['state']}. Install/enable the selected provider.",'addons'))
    if provider=='MDM Link':
        mode=setting(LINK,'source_mode');mode='Combined' if mode=='' else mode
        if mode not in ('Free','Debrid','Combined'):mode='unknown';issues.append(('Link source mode could not be read. Choose Free, Debrid or Combined.','provider_settings'))
        slots=[(credential_present(LINK,'provider_stream_'+str(i)+'_url'),enabled_setting(LINK,'provider_stream_'+str(i)+'_enabled')) for i in range(1,4)]
        custom=any(p is True and e is True for p,e in slots)
        uncertain=any(p is None or (p is True and e is None) for p,e in slots)
        archive=enabled_setting(LINK,'provider_archive');torrentio=enabled_setting(LINK,'provider_torrentio')
        free=archive is True or custom
        paid=service=='configured' and (torrentio is True or custom)
        available=free if mode=='Free' else paid if mode=='Debrid' else free or paid if mode=='Combined' else None
        if available is False:
            if uncertain or archive is None or torrentio is None:issues.append(('Link provider settings could not be read. Check Provider Settings.','provider_settings'))
            else:issues.append(('No Link provider is configured for the current mode. Enable Internet Archive, Torrentio or a stream provider.','provider_settings'))
        if mode=='Combined' and service!='configured':issues.append(('Combined currently uses free sources; AllDebrid is '+service+'. Open account tools to add debrid sources.','account_tools'))
        if mode=='Debrid' and service!='configured':issues.append(('Debrid mode needs AllDebrid enabled and authorised. Current status: '+service+'.','account_tools'))
    elif provider in ('Auto','CocoScrapers') and service!='configured':issues.append(('CocoScrapers needs AllDebrid enabled and authorised in Flix. Current status: '+service+'.','account_tools'))
    return {'addons':records,'provider':provider,'mode':mode,'tmdb':tmdb,'alldebrid':service,'issues':issues}

def report(data):
    lines=['Catalogue (TMDB): '+data['tmdb'],'Selected provider: '+data['provider']+(' (uses CocoScrapers)' if data['provider']=='Auto' else ''),
           'Source mode: '+data['mode'],'AllDebrid: '+data['alldebrid'],
           'Configured means credentials are present; account validity and source availability are not checked here.','']
    lines+=['Next steps:']+[message for message,action in data['issues']] if data['issues'] else ['Setup checks complete. Open Flix to browse.']
    lines+=['','Installed addons:']+[f"{ADDONS[key]}: {row['state']} | {row['version']}" for key,row in data['addons'].items()]
    return '\n'.join(lines)

def label(name):
    try:return xbmc.getInfoLabel(name)
    except Exception:return ''

def positive(value):
    if not isinstance(value,str):return None
    match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:MB)?\s*',value,re.I)
    if not match:return None
    result=float(match.group(1));return int(result) if 0<result<10000000 else None

def device():
    platform='unknown'
    for condition,name in (('Android','Android'),('Windows','Windows'),('OSX','macOS'),('Linux','Linux')):
        try:
            if xbmc.getCondVisibility('System.Platform.'+condition):platform=name;break
        except Exception:pass
    free=positive(label('System.Memory(free)'));total=positive(label('System.Memory(total)'))
    width=positive(label('System.ScreenWidth'));height=positive(label('System.ScreenHeight'))
    kodi=version(label('System.BuildVersionShort'))
    return '\n'.join(['Platform: '+platform,'Kodi: '+kodi,'Total memory: '+(str(total)+' MB' if total else 'unknown'),
                      'Free memory now: '+(str(free)+' MB' if free else 'unknown'),
                      'Current Kodi screen: '+(f'{width} x {height}' if width and height else 'unknown'),
                      'Current screen size is not the maximum supported video/display resolution.',
                      'Device information is read-only; no optimisation settings were applied.'])
