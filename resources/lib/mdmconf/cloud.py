"""Authenticated HTTPS WebDAV, immutable uploads and bounded downloads."""
import base64
import http.client
import json
import re
import ssl
import time
import uuid
from urllib.parse import quote,unquote,urlsplit,urlunsplit
import xml.etree.ElementTree as ET
from pathlib import Path
from . import builds

KOOFR='https://app.koofr.net/dav/Koofr'
FOLDER='MDM_Builds';MAX_LIST=2*1024*1024

def endpoint(value):
    try:
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or any(ord(c)<33 for c in value):raise ValueError()
        parsed.port
        parts=[unquote(x) for x in parsed.path.split('/')]
        if any(x in ('.','..') or '/' in x or '\\' in x or '%' in x or any(ord(c)<32 for c in x) for x in parts):raise ValueError()
        return urlunsplit(('https',parsed.netloc,parsed.path.rstrip('/'),'',''))
    except Exception:raise builds.BuildError('Use a valid HTTPS WebDAV address without embedded login details or query parameters.') from None

class Client:
    def __init__(self,base,username,password,check=builds.check_default,update=lambda x,y:None,connection=None):
        self.base=endpoint(base);self.url=urlsplit(self.base);self.check=check;self.update=update
        if not isinstance(username,str) or not username.strip() or ':' in username or not isinstance(password,str) or not password or any(ord(c)<32 for c in username+password):raise builds.BuildError('Enter your storage username/email and application password in Conf settings.')
        self.authorization='Basic '+base64.b64encode((username.strip()+':'+password).encode()).decode()
        self.connection=connection or http.client.HTTPSConnection
        self.deadline=time.monotonic()+180

    def tick(self):
        self.check()
        if time.monotonic()>self.deadline:raise builds.BuildError('Storage operation timed out. Retry on a stable connection.')

    def request(self,method,path,body=b'',headers=None,limit=MAX_LIST):
        self.tick();connection=None
        try:
            connection=self.connection(self.url.hostname,self.url.port or 443,timeout=10,context=ssl.create_default_context())
            connection.putrequest(method,path);connection.putheader('Authorization',self.authorization)
            connection.putheader('Content-Length',str(len(body)))
            for key,value in (headers or {}).items():connection.putheader(key,value)
            connection.endheaders()
            for offset in range(0,len(body),65536):
                self.tick();part=body[offset:offset+65536];connection.send(part);self.update(int((offset+len(part))*90/max(len(body),1)),'Sending storage request')
            self.tick();reply=connection.getresponse();code=reply.status
            if code in (401,403):raise builds.BuildError('Storage login was rejected. Check email/username and the application password.')
            if code==507:raise builds.BuildError('Cloud storage is full or has insufficient quota.')
            if 300<=code<400:raise builds.BuildError('Storage redirected the request. Use its final HTTPS WebDAV address; login details were not forwarded.')
            if code>=400 and not (method=='MKCOL' and code==405):raise builds.BuildError('Storage could not complete this operation (HTTP {}).'.format(code))
            if code<200:raise builds.BuildError('Storage returned an incomplete response.')
            length=reply.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length)>limit):raise builds.BuildError('Storage response exceeds the permitted size.')
            result=bytearray()
            while True:
                self.tick();part=reply.read(min(65536,limit+1-len(result)))
                if not part:break
                result.extend(part)
                if len(result)>limit:raise builds.BuildError('Storage response exceeds the permitted size.')
                if method=='GET':self.update(min(95,int(len(result)*95/int(length))) if length and int(length)>0 else 0,'Downloading build')
            if length is not None and len(result)!=int(length):raise builds.BuildError('Storage transfer was interrupted. Retry the download.')
            return code,bytes(result)
        except builds.BuildError:raise
        except Exception:raise builds.BuildError('Storage connection failed. Check the network and storage settings.') from None
        finally:
            if connection is not None:connection.close()

    @property
    def folder(self):return self.url.path.rstrip('/')+'/'+FOLDER

    def path(self,name):
        if not builds.FILENAME.fullmatch(name):raise builds.BuildError('Invalid remote build filename.')
        return self.folder+'/'+quote(name,safe='')

    def ensure_folder(self):
        self.request('MKCOL',self.folder,limit=MAX_LIST)
        # A 405 can mean an existing file, not a collection: confirm the folder.
        self.list()

    def list(self):
        body=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/></d:prop></d:propfind>'
        code,raw=self.request('PROPFIND',self.folder+'/',body,{'Depth':'1','Content-Type':'application/xml'},MAX_LIST)
        if code!=207 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise builds.BuildError('Storage returned an invalid folder listing.')
        try:root=ET.fromstring(raw)
        except ET.ParseError:raise builds.BuildError('Storage returned an unreadable folder listing.') from None
        if root.tag!='{DAV:}multistatus':raise builds.BuildError('Storage returned an invalid folder listing.')
        result=[];folder_found=False
        for response in root.findall('{DAV:}response'):
            href=response.findtext('{DAV:}href','');parsed=urlsplit(href)
            if parsed.query or parsed.fragment or parsed.netloc and (parsed.scheme!='https' or parsed.netloc!=self.url.netloc):continue
            path=unquote(parsed.path)
            for propstat in response.findall('{DAV:}propstat'):
                if not re.search(r'\s200(?:\s|$)',propstat.findtext('{DAV:}status','')):continue
                prop=propstat.find('{DAV:}prop')
                if prop is None:continue
                collection=prop.find('{DAV:}resourcetype/{DAV:}collection') is not None
                if path.rstrip('/')==unquote(self.folder) and collection:folder_found=True
                prefix=unquote(self.folder)+'/'
                if collection or not path.startswith(prefix):continue
                name=path[len(prefix):]
                if not builds.FILENAME.fullmatch(name):continue
                size=prop.findtext('{DAV:}getcontentlength','')
                if not size.isdigit() or int(size)>builds.MAX_ARCHIVE:continue
                if name not in result:result.append(name)
                if len(result)>1000:raise builds.BuildError('Too many remote builds to list. Organise the build folder in storage.')
        if not folder_found:raise builds.BuildError('Storage build folder is not available as a WebDAV collection.')
        return sorted(result,reverse=True)

    def upload(self,path):
        path=Path(path);builds.read(path);raw=path.read_bytes();final=self.path(path.name)
        self.ensure_folder();temporary=final+'.upload-'+uuid.uuid4().hex
        code,_=self.request('PUT',temporary,raw,{'Content-Type':'application/zip','If-None-Match':'*'},MAX_LIST)
        if code not in (200,201,204):raise builds.BuildError('Storage did not accept the uploaded build.')
        code,received=self.request('GET',temporary,limit=builds.MAX_ARCHIVE)
        if code!=200 or builds.digest(raw)!=builds.digest(received):raise builds.BuildError('Uploaded build failed its integrity check; it was not published to the build list.')
        self.tick();destination=urlunsplit(('https',self.url.netloc,final,'',''))
        code,_=self.request('MOVE',temporary,headers={'Destination':destination,'Overwrite':'F'})
        if code not in (201,204):raise builds.BuildError('Storage did not publish the uploaded build.')
        self.update(100,'Build uploaded and verified')

    def download(self,name):
        code,raw=self.request('GET',self.path(name),limit=builds.MAX_ARCHIVE)
        if code!=200:raise builds.BuildError('Storage did not return a complete build.')
        root=builds.directory('builds');path=root/name
        # Validate in an isolated local temp folder; never overwrite an existing identity.
        import tempfile
        with tempfile.TemporaryDirectory(dir=root,prefix='.mdm-download-') as folder:
            temporary=Path(folder)/name;builds.atomic(temporary,raw);builds.read(temporary);self.tick()
            if path.exists():
                if builds.digest(path.read_bytes())!=builds.digest(raw):raise builds.BuildError('A different local file already uses this build identity. Preserve it before downloading.')
            else:builds.atomic(path,raw)
        self.update(100,'Build downloaded and verified');return path

def configured(addon,check=builds.check_default,update=lambda x,y:None):
    provider=addon.getSetting('storage_provider')
    if provider not in ('','Koofr','Custom WebDAV'):raise builds.BuildError('Choose a supported storage service in Conf settings.')
    base=KOOFR if provider!='Custom WebDAV' else addon.getSetting('storage_endpoint')
    return Client(base,addon.getSetting('storage_username'),addon.getSetting('storage_password'),check,update)
