"""Portable configuration archives and journalled restore; no addon binaries."""
import hashlib
import json
import math
import os
import re
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import xbmc
import xbmcaddon
import xbmcvfs

MAX_JSON=4*1024*1024;MAX_ARCHIVE=8*1024*1024;MAX_ADDONS=1000;MAX_SETTINGS=10000
GUI=('lookandfeel.font','lookandfeel.skincolors','lookandfeel.skintheme','lookandfeel.skinzoom','lookandfeel.soundskin')
PRIVATE=re.compile(r'password|passwd|secret|token|api.?key|auth|cookie|session|account|login|username|email|credential|pin(?:$|[._-])|last_search|alldebrid_enabled',re.I)
IDENTIFIER=re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}')
KEY=re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}')
FILENAME=re.compile(r'[a-z0-9][a-z0-9-]{0,39}-[0-9]{8}T[0-9]{6}Z-([a-f0-9]{32})\.mdmbuild\.zip')
TEXT_ALLOWED={'plugin.video.mdm.flix':{'scraper_provider','playback_mode','tmdb_language'},'script.mdm.link':{'source_mode'}}

class BuildError(Exception):pass
class Cancelled(BuildError):pass

def check_default():pass

def rpc(method,params=None):
    request={'jsonrpc':'2.0','id':1,'method':method}
    if params is not None:request['params']=params
    try:
        reply=json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        if not isinstance(reply,dict) or 'error' in reply or 'result' not in reply:raise ValueError()
        return reply['result']
    except Exception:raise BuildError('Kodi could not read or update the requested configuration.') from None

def identifier(value):return isinstance(value,str) and bool(IDENTIFIER.fullmatch(value))

def safe_key(value):return isinstance(value,str) and bool(KEY.fullmatch(value)) and not PRIVATE.search(value) and not value.startswith('device_')

def safe_string(value):
    # Conservative portable strings: omit paths, URLs, commands and credential-like data.
    return isinstance(value,str) and len(value)<=200 and bool(re.fullmatch(r'[\w .+,-]*',value,re.UNICODE)) and not re.search(r'(?i)(bearer|password|token|secret|api.?key)',value)

def primitive(value):
    return type(value) is bool or type(value) is int and abs(value)<10**9 or type(value) is float and math.isfinite(value) and abs(value)<10**9 or safe_string(value)

def clean_name(value):
    if not isinstance(value,str):raise BuildError('Enter a build name.')
    value=re.sub(r'[\[\]\x00-\x1f\x7f]','',value).strip()[:80]
    if not value:raise BuildError('Enter a build name.')
    return value

def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

def digest(raw):return hashlib.sha256(raw).hexdigest()

def profile():
    root=Path(xbmcvfs.translatePath(xbmcaddon.Addon('script.mdm.conf').getAddonInfo('profile')))
    root.mkdir(parents=True,exist_ok=True);return root

def directory(name):
    if name not in ('builds','recovery'):raise BuildError('Invalid storage location.')
    root=profile()/name;root.mkdir(exist_ok=True);return root

def atomic(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.mdm-',delete=False) as stream:
            temporary=stream.name;stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    except Exception:raise BuildError('Could not save the build or recovery data. Check free storage.') from None
    finally:
        if temporary and os.path.exists(temporary):os.unlink(temporary)

def definitions(target):
    try:
        path=Path(xbmcvfs.translatePath(target.getAddonInfo('path')))/'resources/settings.xml'
        if not path.is_file() or path.stat().st_size>MAX_JSON:return {}
        raw=path.read_bytes()
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():return {}
        root=ET.fromstring(raw);found={}
        for setting in root.iter('setting'):
            key=setting.get('id');kind=setting.get('type','').lower()
            control=setting.find('control')
            if not safe_key(key) or setting.get('option')=='hidden' or setting.get('visible')=='false':continue
            if control is not None and (control.get('format')=='password' or control.find("attributes/attribute[@name='hidden']") is not None):continue
            if kind in ('bool','boolean','int','integer','number','float','enum','labelenum','select'):
                found[key]=kind
            elif key in TEXT_ALLOWED.get(target.getAddonInfo('id'),set()):found[key]='text'
        return found
    except Exception:return {}

def permitted(kind,value):
    if not isinstance(value,str) or len(value)>200:return False
    if value=='':return True
    if kind in ('bool','boolean'):return value in ('true','false')
    if kind in ('int','integer'):return bool(re.fullmatch(r'-?[0-9]{1,9}',value))
    if kind in ('number','float'):
        try:return math.isfinite(float(value)) and abs(float(value))<10**9
        except ValueError:return False
    return safe_string(value)

def installed():
    result=rpc('Addons.GetAddons',{'enabled':'all','installed':True,'properties':['version','enabled']})
    if not isinstance(result,dict) or not isinstance(result.get('addons',[]),list):raise BuildError('Kodi addon inventory is unavailable.')
    limits=result.get('limits',{})
    if isinstance(limits,dict) and limits.get('end',0)<limits.get('total',0):raise BuildError('Kodi returned an incomplete addon inventory.')
    rows=result.get('addons',[])
    if len(rows)>MAX_ADDONS:raise BuildError('Too many addons for this build format.')
    return {r['addonid']:r for r in rows if isinstance(r,dict) and identifier(r.get('addonid'))}

def capture(name,check=check_default,update=lambda x,y:None):
    name=clean_name(name);rows=installed();addons=[];omitted=0
    system=Path(xbmcvfs.translatePath('special://xbmc/')).resolve()
    for index,(id,row) in enumerate(rows.items()):
        check();update(int(index*70/max(len(rows),1)),'Reading portable addon configuration')
        if id=='script.mdm.conf':continue # Storage login and machine-local Conf paths never travel.
        try:
            target=xbmcaddon.Addon(id);path=Path(xbmcvfs.translatePath(target.getAddonInfo('path'))).resolve()
            if path==system or system in path.parents:continue
            defs=definitions(target);values={}
            for key,kind in defs.items():
                check()
                try:value=target.getSetting(key)
                except Exception:omitted+=1;continue
                if permitted(kind,value):values[key]=value
                else:omitted+=1
            addons.append({'id':id,'version':str(row.get('version',''))[:64],'enabled':row.get('enabled') is True,'settings':values})
        except Cancelled:raise
        except Exception:omitted+=1
    check();gui={}
    for key in GUI:
        try:
            value=rpc('Settings.GetSettingValue',{'setting':key})['value']
            if primitive(value):gui[key]=value
        except (BuildError,KeyError,TypeError):omitted+=1
    skin=rpc('Settings.GetSettingValue',{'setting':'lookandfeel.skin'}).get('value')
    if not identifier(skin) or not skin.startswith('skin.'):raise BuildError('Kodi active skin could not be read.')
    skins={}
    try:
        result=rpc('Settings.GetSkinSettings')
        if not isinstance(result,dict) or result.get('skin')!=skin or not isinstance(result.get('settings'),list):raise BuildError('Skin settings are unavailable.')
        for setting in result.get('settings',[]):
            if isinstance(setting,dict) and safe_key(setting.get('id')) and type(setting.get('value')) in (str,bool) and primitive(setting['value']):skins[setting['id']]=setting['value']
            else:omitted+=1
    except BuildError:omitted+=1
    return {'format':1,'id':uuid.uuid4().hex,'name':name,'created':datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
            'addons':addons,'gui':gui,'skin':skin,'skin_settings':skins,'omitted':omitted}

def validate(data):
    if not isinstance(data,dict) or type(data.get('format')) is not int or data.get('format')!=1 or not isinstance(data.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',data['id']):raise BuildError('Invalid build manifest.')
    if set(data)!={'format','id','name','created','addons','gui','skin','skin_settings','omitted'}:raise BuildError('Unsupported build manifest fields.')
    if clean_name(data.get('name'))!=data.get('name') or not isinstance(data.get('created'),str) or not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z',data['created']):raise BuildError('Invalid build identity.')
    try:datetime.strptime(data['created'],'%Y%m%dT%H%M%SZ')
    except ValueError:raise BuildError('Invalid build date.') from None
    if not identifier(data.get('skin')) or not data['skin'].startswith('skin.'):raise BuildError('Invalid build skin.')
    if not isinstance(data.get('addons'),list) or len(data['addons'])>MAX_ADDONS:raise BuildError('Invalid addon inventory.')
    seen=set();total=0
    for row in data['addons']:
        if not isinstance(row,dict) or not identifier(row.get('id')) or row['id']=='script.mdm.conf' or row['id'] in seen:raise BuildError('Invalid or repeated addon entry.')
        if set(row)!={'id','version','enabled','settings'}:raise BuildError('Unsupported addon entry fields.')
        seen.add(row['id'])
        if type(row.get('enabled')) is not bool or not isinstance(row.get('version'),str) or not re.fullmatch(r'[A-Za-z0-9.+_-]{0,64}',row['version']):raise BuildError('Invalid addon version/state.')
        values=row.get('settings')
        if not isinstance(values,dict):raise BuildError('Invalid addon configuration.')
        for key,value in values.items():
            if not safe_key(key) or not isinstance(value,str) or not permitted('text',value):raise BuildError('Build contains unsupported or private addon fields.')
        total+=len(values)
    if not isinstance(data.get('gui'),dict) or any(key not in GUI or not primitive(value) for key,value in data['gui'].items()):raise BuildError('Invalid interface configuration.')
    if not isinstance(data.get('skin_settings'),dict) or any(not safe_key(key) or type(value) not in (str,bool) or not primitive(value) for key,value in data['skin_settings'].items()):raise BuildError('Invalid portable skin settings.')
    total+=len(data['skin_settings'])
    if total>MAX_SETTINGS or len(encode(data))>MAX_JSON:raise BuildError('Build configuration exceeds its size limit.')
    if type(data.get('omitted')) is not int or data['omitted']<0:raise BuildError('Invalid build coverage information.')
    return data

def filename(data):
    slug=re.sub('[^a-z0-9]+','-',data['name'].lower()).strip('-')[:40].rstrip('-') or 'build'
    return f"{slug}-{data['created']}-{data['id']}.mdmbuild.zip"

def save(data,check=check_default):
    validate(data);check();raw=encode(data);path=directory('builds')/filename(data)
    if path.exists():raise BuildError('A local build with this identity already exists.')
    import io
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',raw);archive.writestr('integrity.json',encode({'sha256':digest(raw),'size':len(raw)}))
    check();atomic(path,stream.getvalue());return path

def read(path):
    try:
        path=Path(path)
        if path.stat().st_size>MAX_ARCHIVE:raise ValueError()
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)!=2 or {e.filename for e in entries}!={'manifest.json','integrity.json'}:raise ValueError()
            if any(e.flag_bits&1 or e.file_size>MAX_JSON or e.is_dir() or (e.external_attr>>16)&0o170000==0o120000 for e in entries):raise ValueError()
            raw=archive.read('manifest.json');integrity=json.loads(archive.read('integrity.json'),object_pairs_hook=unique_object)
            if integrity!={'sha256':digest(raw),'size':len(raw)}:raise ValueError()
            data=validate(json.loads(raw,object_pairs_hook=unique_object))
            match=FILENAME.fullmatch(path.name)
            if not match or match.group(1)!=data['id']:raise ValueError()
            return data
    except BuildError:raise
    except Exception:raise BuildError('Build archive is invalid, corrupt or unsupported. No settings were changed.') from None

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Repeated JSON key')
        result[key]=value
    return result

def local_builds():
    paths=[p for p in directory('builds').iterdir() if p.is_file() and FILENAME.fullmatch(p.name)]
    return sorted(paths,key=lambda p:p.name,reverse=True)

def plan(data,check=check_default):
    validate(data);rows=installed();missing=[];disabled=[];versions=[];operations=[];skipped=0
    for row in data['addons']:
        check();id=row['id'];existing=rows.get(id)
        if existing is None:
            if row['enabled'] or row['settings']:missing.append(id)
            continue
        if existing.get('enabled') is not True:
            if row['enabled'] or row['settings']:disabled.append(id)
            continue
        if existing.get('version')!=row['version']:versions.append(id)
        try:target=xbmcaddon.Addon(id);defs=definitions(target)
        except Exception:raise BuildError('Addon configuration is unavailable. Refresh before restoring.') from None
        for key,value in row['settings'].items():
            if key in defs and permitted(defs[key],value):operations.append({'kind':'addon','addon':id,'key':key,'value':value})
            else:skipped+=1
    skin=rpc('Settings.GetSettingValue',{'setting':'lookandfeel.skin'}).get('value')
    if data['skin'] not in rows and data['skin'] not in missing:missing.append(data['skin'])
    elif rows.get(data['skin'],{}).get('enabled') is not True and data['skin'] not in disabled:disabled.append(data['skin'])
    for key,value in data['gui'].items():operations.append({'kind':'gui','key':key,'value':value})
    for key,value in data['skin_settings'].items():operations.append({'kind':'skin','key':key,'value':value})
    return {'missing':missing,'disabled':disabled,'version_differences':versions,'skin_matches':skin==data['skin'],
            'operations':operations,'skipped':skipped,'skin':data['skin']}

def preview(data,prepared):
    return '\n'.join([data['name'],f"{len(data['addons'])} addon records; {len(prepared['operations'])} portable settings",
                      'Skin: '+data['skin'],'Missing addons: '+(', '.join(prepared['missing']) or 'none'),
                      'Disabled required addons: '+(', '.join(prepared['disabled']) or 'none'),
                      'Different addon versions: '+(', '.join(prepared['version_differences']) or 'none'),
                      'Current skin matches: '+('yes' if prepared['skin_matches'] else 'no'),
                      f"{data['omitted']} unavailable/unsupported values omitted during capture; {prepared['skipped']} fields unavailable on this destination.",
                      'Private credentials, URLs, paths, addon binaries, databases and custom artwork files are not included.',
                      'Addon versions are recorded; installed repository versions are used, not forcibly downgraded.',
                      'Restore creates recovery data first. Keep the build skin active for layout restoration.'])

def operation_value(operation):
    kind=operation.get('kind');key=operation.get('key')
    if kind=='addon':
        id=operation.get('addon')
        if not identifier(id) or id=='script.mdm.conf' or not safe_key(key):raise BuildError('Invalid recovery setting.')
        target=xbmcaddon.Addon(id);defs=definitions(target)
        if key not in defs:raise BuildError('This addon setting is no longer available.')
        value=target.getSetting(key)
        if not permitted(defs[key],value):raise BuildError('This setting cannot be recovered safely.')
        return value
    if kind=='gui' and key in GUI:return rpc('Settings.GetSettingValue',{'setting':key})['value']
    if kind=='skin' and safe_key(key):return rpc('Settings.GetSkinSettingValue',{'setting':key})['value']
    raise BuildError('Invalid recovery operation.')

def equivalent(operation,actual):
    expected=operation['value']
    if operation['kind']=='addon':
        defs=definitions(xbmcaddon.Addon(operation['addon']));kind=defs.get(operation['key'])
        if kind in ('int','integer','number','float') and actual!='' and expected!='' and permitted(kind,actual) and permitted(kind,expected):
            return float(actual)==float(expected)
    return type(actual) is type(expected) and actual==expected

def operation_label(operation):
    owner=operation.get('addon') if operation.get('kind')=='addon' else operation.get('kind')
    return '{} / {}'.format(owner,operation.get('key'))

def apply(operation):
    # Revalidate destination definitions, including when recovering after a restart.
    current=operation_value(operation);kind=operation['kind'];key=operation['key'];value=operation['value']
    if equivalent(operation,current):return # Avoid callbacks/writes for unchanged configuration.
    if kind=='addon':
        target=xbmcaddon.Addon(operation['addon']);defs=definitions(target)
        if not permitted(defs[key],value):raise BuildError('Incompatible addon setting value.')
        target.setSetting(key,value)
        if not equivalent(operation,target.getSetting(key)):raise BuildError('Kodi did not save an addon setting.')
    else:
        if kind=='gui' and not primitive(value) or kind=='skin' and (type(value) not in (str,bool) or not primitive(value)):raise BuildError('Invalid interface setting value.')
        method='Settings.SetSettingValue' if kind=='gui' else 'Settings.SetSkinSettingValue'
        # Kodi skin setters return the assigned value (including false/empty string).
        # Successful RPC plus verified readback is authoritative, not result truthiness.
        rpc(method,{'setting':key,'value':value})
        actual=operation_value(operation)
        if type(actual) is not type(value) or actual!=value:raise BuildError('Kodi did not save the requested interface value.')

def journal_path():return directory('recovery')/'last-restore.json'

def journal():
    path=journal_path()
    if not path.exists():return None
    try:
        if path.stat().st_size>MAX_JSON:raise ValueError()
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or type(value.get('format')) is not int or value.get('format')!=1 or value.get('state') not in ('pending','complete','recovered') or not identifier(value.get('skin')) or not isinstance(value.get('before'),list) or len(value['before'])>MAX_SETTINGS:raise ValueError()
        for operation in value['before']:
            if not isinstance(operation,dict):raise ValueError()
            kind=operation.get('kind');key=operation.get('key');previous=operation.get('value')
            if kind=='addon':
                if not identifier(operation.get('addon')) or operation['addon']=='script.mdm.conf' or not safe_key(key) or not permitted('text',previous):raise ValueError()
            elif kind=='gui':
                if key not in GUI or not primitive(previous):raise ValueError()
            elif kind=='skin':
                if not safe_key(key) or type(previous) not in (str,bool) or not primitive(previous):raise ValueError()
            else:raise ValueError()
        return value
    except Exception:raise BuildError('Recovery data is unreadable. Preserve it and resolve storage before restoring another build.') from None

def _recover(check=check_default,update=lambda x,y:None):
    value=journal()
    if value is None or value['state']=='recovered':raise BuildError('No restore recovery is available.')
    if rpc('Settings.GetSettingValue',{'setting':'lookandfeel.skin'}).get('value')!=value['skin']:raise BuildError('Switch back to the recorded build skin before recovering its layout.')
    value['state']='pending';atomic(journal_path(),encode(value))
    failures=[]
    for index,operation in enumerate(reversed(value['before'])):
        check()
        try:apply(operation)
        except Exception:failures.append(operation_label(operation))
        update(int((index+1)*100/max(len(value['before']),1)),'Recovering previous settings')
    value['recovery_errors']=failures[:20];value['recovery_error_count']=len(failures)
    if failures:
        atomic(journal_path(),encode(value))
        raise BuildError('Recovery restored available settings, but {} setting(s) still need recovery: {}. Open Restore diagnostics for details.'.format(len(failures),'; '.join(failures[:3])))
    value['state']='recovered';atomic(journal_path(),encode(value))

def _restore(data,check=check_default,update=lambda x,y:None):
    pending=journal()
    if pending and pending['state']=='pending':raise BuildError('A previous restore needs recovery before another can start.')
    prepared=plan(data,check)
    if prepared['missing'] or prepared['disabled'] or not prepared['skin_matches']:raise BuildError('Install/enable required addons and switch to the build skin before restoring.')
    before=[];changed=[]
    for operation in prepared['operations']:
        check();value=operation_value(operation)
        if operation['kind']=='gui' and not primitive(value) or operation['kind']=='skin' and (type(value) not in (str,bool) or not primitive(value)):raise BuildError('Previous interface values cannot be saved safely.')
        if operation['kind'] in ('gui','skin') and type(value) is not type(operation['value']):raise BuildError('Destination interface setting types differ. No settings were changed.')
        if not equivalent(operation,value):before.append(dict(operation,value=value));changed.append(operation)
    # New journals contain only changed settings. Legacy 0.2.0 full journals remain readable.
    value={'format':1,'state':'pending','skin':data['skin'],'build_id':data['id'],'before':before}
    raw=encode(value)
    if len(raw)>MAX_JSON:raise BuildError('Recovery data exceeds its size limit. No settings were changed.')
    check();atomic(journal_path(),raw)
    try:
        for index,operation in enumerate(changed):
            check();apply(operation);update(int((index+1)*100/max(len(before),1)),'Restoring portable settings')
        value['state']='complete';atomic(journal_path(),encode(value))
    except Exception as error:
        value['state']='pending'
        value['restore_error']=operation_label(operation) if changed else 'recovery journal'
        try:atomic(journal_path(),encode(value))
        except BuildError:pass # Original durable before-values still permit rollback.
        try:_recover() # Recovery ignores the cancelled progress so already-applied changes are undone.
        except Exception:raise BuildError('Restore stopped at {} and recovery is still needed. Reopen Conf > Build backups > Restore recovery; Restore diagnostics shows any remaining settings.'.format(value['restore_error'])) from None
        if isinstance(error,Cancelled):raise Cancelled('Restore cancelled; previous settings recovered.') from None
        raise BuildError('Restore stopped at {}; previous settings recovered. Check addon compatibility and retry.'.format(value['restore_error'])) from None
    return prepared

def diagnostics():
    value=journal()
    if value is None:return 'No restore recovery record exists.'
    # Display validated setting identifiers only, never values or raw exception text.
    labels={operation_label(operation) for operation in value['before']}
    failed=value.get('restore_error');errors=value.get('recovery_errors',[])
    lines=['Recovery state: '+value['state'],'Recorded settings: '+str(len(value['before']))]
    if isinstance(failed,str) and failed in labels:lines.append('Restore stopped at: '+failed)
    if isinstance(errors,list):lines.extend('Recovery still needed: '+label for label in errors if isinstance(label,str) and label in labels)
    if value['state']=='pending' and not errors:lines.append('Previous release did not record the failing setting. Run Restore recovery with this update; the existing record is retained.')
    return '\n'.join(lines)

@contextmanager
def editing(recovery=False):
    path=profile()/'restore.lock';owned=False
    try:
        if recovery and path.exists():
            try:old=json.loads(path.read_text(encoding='utf-8'))
            except Exception:raise BuildError('Restore lock is unreadable. Preserve recovery data and restart Kodi.') from None
            if old.get('pid')!=os.getpid():path.unlink()
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);owned=True
        except FileExistsError:raise BuildError('Another restore is running or a previous Kodi session needs recovery. Restart Kodi, then open Restore recovery.') from None
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump({'pid':os.getpid()},stream);stream.flush();os.fsync(stream.fileno())
        yield
    finally:
        if owned and path.exists():path.unlink()

def recover(check=check_default,update=lambda x,y:None):
    with editing(recovery=True):return _recover(check,update)

def restore(data,check=check_default,update=lambda x,y:None):
    with editing():return _restore(data,check,update)
