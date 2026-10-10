"""On-device build workflows. Account details never appear in build previews."""
from contextlib import contextmanager
import xbmc
import xbmcaddon
import xbmcgui
from . import builds,cloud

TITLE='MDM Conf - Build backups'
def message(text):xbmcgui.Dialog().ok(TITLE,text)

@contextmanager
def progress(label):
    dialog=xbmcgui.DialogProgress();monitor=xbmc.Monitor();dialog.create(TITLE,label)
    def check():
        if dialog.iscanceled() or monitor.abortRequested():raise builds.Cancelled('Operation cancelled.')
    def update(percent,text):dialog.update(max(0,min(100,percent)),text)
    try:yield check,update
    finally:dialog.close()

def client(check,update):return cloud.configured(xbmcaddon.Addon('script.mdm.conf'),check,update)

def preview(path):
    data=builds.read(path);prepared=builds.plan(data)
    xbmcgui.Dialog().textviewer(TITLE,builds.preview(data,prepared));return data,prepared

def prerequisites(data,prepared):
    if prepared['missing']:
        choices=prepared['missing'];choice=xbmcgui.Dialog().select('Install missing addon through Kodi',choices+['Back'])
        if type(choice) is int and 0<=choice<len(choices):
            # Archive identifiers are validated before becoming a Kodi argument.
            xbmc.executebuiltin('InstallAddon('+choices[choice]+')');message('Finish installation in Kodi, then reopen Conf and preview this build again.');return True
        return False
    if prepared['disabled']:message('Enable required addons in Kodi, then preview again: '+', '.join(prepared['disabled']));return False
    if not prepared['skin_matches']:
        if xbmcgui.Dialog().yesno(TITLE,'Switch to '+data['skin']+' first? Confirm the skin change in Kodi, then reopen Conf to preview and restore.'):
            if builds.rpc('Settings.SetSettingValue',{'setting':'lookandfeel.skin','value':data['skin']}) is not True:raise builds.BuildError('Kodi could not switch to the build skin.')
            return True
        return False
    return None

def local_action(path):
    data,prepared=preview(path)
    choice=xbmcgui.Dialog().select(TITLE,['Upload this build','Restore this build','Back'])
    if choice==0:
        with progress('Uploading and verifying build') as (check,update):client(check,update).upload(path)
        message('Build uploaded and verified. It is available in Cloud builds.')
    elif choice==1:
        leave=prerequisites(data,prepared)
        if leave is not None:return leave
        if not xbmcgui.Dialog().yesno(TITLE,builds.preview(data,prepared)+'\nRestore these supported settings now?'):return False
        with progress('Saving recovery data and restoring') as (check,update):builds.restore(data,check,update)
        message('Supported settings restored. Restart Kodi to refresh affected interfaces. Restore recovery can undo this restore while the recorded skin remains active.')
        return True
    return False

def local():
    paths=builds.local_builds()
    if not paths:message('No local builds yet. Choose Create build first.');return False
    labels=[]
    for path in paths:
        try:
            data=builds.read(path);labels.append(data['name']+' - '+data['created'])
        except builds.BuildError:labels.append('Unreadable build - '+path.name)
    choice=xbmcgui.Dialog().select('Local builds',labels)
    if type(choice) is int and 0<=choice<len(paths):return local_action(paths[choice])
    return False

def remote():
    with progress('Reading cloud builds') as (check,update):
        storage=client(check,update);storage.ensure_folder();names=storage.list()
    if not names:message('No cloud builds yet. Upload a saved build from Local builds.');return False
    choice=xbmcgui.Dialog().select('Download cloud build',names)
    if type(choice) is int and 0<=choice<len(names):
        with progress('Downloading and validating build') as (check,update):path=client(check,update).download(names[choice])
        return local_action(path)
    return False

def run():
    while not xbmc.Monitor().abortRequested():
        choice=xbmcgui.Dialog().select(TITLE,['Create build','Local builds / preview / upload / restore','Cloud builds / download',
            'Storage settings','Check storage connection','Restore recovery','Build contents and limits','Back','Restore diagnostics'])
        if type(choice) is not int or choice<0 or choice==7:return False
        try:
            if choice==0:
                name=xbmcgui.Dialog().input('Name this configuration build')
                if not name.strip():continue
                with progress('Saving portable configuration') as (check,update):
                    data=builds.capture(name,check,update);path=builds.save(data,check)
                preview(path);message('Build saved locally. Choose Local builds to upload or restore it.')
            elif choice==1:
                if local():return True
            elif choice==2:
                if remote():return True
            elif choice==3:xbmcaddon.Addon('script.mdm.conf').openSettings()
            elif choice==4:
                with progress('Checking storage login and build folder') as (check,update):
                    storage=client(check,update);storage.ensure_folder();count=len(storage.list())
                message('Storage connection works. {} saved builds found.'.format(count))
            elif choice==5:
                if xbmcgui.Dialog().yesno(TITLE,'Recover the settings saved before the most recent restore? Keep its skin active. This replaces the supported values changed by that restore.'):
                    with progress('Recovering previous settings') as (check,update):builds.recover(check,update)
                    message('Previous settings recovered. Restart Kodi to refresh affected interfaces.');return True
            elif choice==6:
                xbmcgui.Dialog().textviewer(TITLE,'This first build format saves addon IDs/versions, supported portable addon settings, and supported skin/interface preferences.\n\n'
                    'It excludes account credentials, Conf storage login, URLs, local paths, addon binaries, media databases and custom artwork files. It does not clone a complete Kodi userdata folder. Some widgets and skin customisations will not transfer.\n\n'
                    'Install required addons through Kodi repositories and activate the recorded skin before restore. Preview shows missing addons, version differences and unavailable fields. Installed versions are retained.\n\n'
                    'Koofr: enter your email and a dedicated WebDAV application password in Storage settings on each device. Builds use the MDM_Builds folder. Do not use your main account password.\n\n'
                    'Uploads are verified before publication and never overwrite another build. Interrupted uploads may leave hidden .upload files in Koofr; these can be removed there. Integrity checks detect corruption; only restore builds from people you trust.\n\n'
                    'Restore saves recovery data before changing settings. Recover interrupted restores before starting another. Recovery covers the most recent restore only; saving or uploading a build does not replace it.')
            elif choice==8:xbmcgui.Dialog().textviewer(TITLE,builds.diagnostics())
        except builds.BuildError as error:message(str(error))
        except Exception:message('Build operation failed. Check storage, installed addons and compatibility, then retry. No account details are shown in this error.')
    return False
