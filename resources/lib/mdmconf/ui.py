"""Remote-friendly hub using existing Kodi/addon setup flows."""
import xbmc
import xbmcgui
from . import status

def message(text):xbmcgui.Dialog().ok('MDM Conf',text)

def need(data,identifier):
    if identifier not in status.ADDONS:return False
    if data['addons'][identifier]['state']!='enabled':
        message(status.ADDONS[identifier]+' is '+data['addons'][identifier]['state']+'. Install/enable it in Kodi Add-ons, then refresh Conf.')
        return False
    return True

def dispatch(action,data):
    if action=='connections':
        from . import connections
        return connections.run()
    if action=='network':
        from . import network
        network.run()
        return False
    if action=='profiles':
        from . import profiles
        return profiles.run()
    if action=='builds':
        from . import build_ui
        return build_ui.run()
    if action=='storage':
        import xbmcaddon
        from . import build_ui
        build_ui.setup_storage(xbmcaddon.Addon('script.mdm.conf'));return False
    if action=='addons':xbmc.executebuiltin('ActivateWindow(addonbrowser)');return True
    if action=='status':xbmcgui.Dialog().textviewer('MDM Conf - Setup status',status.report(data));return False
    if action=='device':xbmcgui.Dialog().textviewer('MDM Conf - Device information',status.device());return False
    if action in ('flix_settings','provider_settings'):
        identifier=status.FLIX if action=='flix_settings' else data['provider_addon']
        if action=='provider_settings' and data['provider']=='unknown':message('Choose the provider in Flix settings first.');return False
        if not need(data,identifier):return False
        target=status.addon(identifier)
        if target is None:message('Addon settings are unavailable. Refresh Conf and try again.');return False
        target.openSettings();return False
    if action in ('account_tools','flix'):
        if data['provider']=='unknown' and action=='account_tools':message('Choose the provider in Flix settings first.');return False
        if action=='account_tools' and data['provider_addon']==status.LINK:
            if not need(data,status.LINK):return False
            xbmc.executebuiltin('RunAddon(script.mdm.link)');return True
        if not need(data,status.FLIX) or not need(data,status.CORE) or not need(data,status.LINK):return False
        url='plugin://plugin.video.mdm.flix/?action=tools' if action=='account_tools' else 'plugin://plugin.video.mdm.flix/'
        xbmc.executebuiltin('ActivateWindow(Videos,'+url+',return)');return True
    message('This action is unavailable. Refresh Conf.');return False

def guide(data):
    if not data['issues']:message('Setup checks complete. Credentials have not been validated online; open Flix to browse.');return False
    choice=xbmcgui.Dialog().select('MDM Conf - Setup steps',[text for text,action in data['issues']])
    if type(choice) is int and 0<=choice<len(data['issues']):return dispatch(data['issues'][choice][1],data)
    return False

def setup_device():
    monitor=xbmc.Monitor()
    while not monitor.abortRequested():
        data=status.snapshot()
        entries=[('Review setup checks','guide'),('Choose this device’s profile','profiles'),
                 ('Check DNS and provider connection','network'),('Set up cloud storage','storage'),
                 ('Open MDM Flix','flix'),('Back','back')]
        choice=xbmcgui.Dialog().select('MDM Conf - Set up this device',[label for label,_ in entries])
        if type(choice) is not int or not 0<=choice<len(entries) or entries[choice][1]=='back':
            return False
        action=entries[choice][1]
        leave=guide(data) if action=='guide' else dispatch(action,data)
        if leave:
            return True
    return False

def run():
    from . import build_ui,builds
    monitor=xbmc.Monitor()
    entries=(('Set up this device',setup_device),
             ('Restore a cloud build',lambda:build_ui.remote(guided=True)),
             ('Create a cloud build',build_ui.create_cloud),
             ('Open MDM Flix',lambda:dispatch('flix',status.snapshot())),
             ('More tools',tools))
    while not monitor.abortRequested():
        choice=xbmcgui.Dialog().select('MDM Conf',[label for label,_ in entries])
        if type(choice) is not int or not 0<=choice<len(entries):
            return
        try:
            if entries[choice][1]():
                return
        except builds.BuildError as error:
            message(str(error))
        except Exception:
            message('The selected action is unavailable. Check installed add-ons or storage settings and try again.')

def tools():
    monitor=xbmc.Monitor()
    while not monitor.abortRequested():
        try:
            data=status.snapshot()
            entries=[('Setup status','status'),('Guided setup','guide'),('Flix / TMDB settings','flix_settings'),
                     ('Provider / source mode settings','provider_settings'),('AllDebrid account tools','account_tools'),
                     ('Open MDM Flix','flix'),('Manage installed addons','addons'),('Device information','device'),('Refresh status','refresh'),
                     ('Build backups / cloud / restore','builds'),('Storage settings','storage'),('Device profiles / quality limits','profiles'),('Connection / file-size preferences','connections'),
                     ('Check DNS and provider connection','network')]
            choice=xbmcgui.Dialog().select('MDM Conf - Setup hub',[label for label,action in entries])
            if type(choice) is not int or choice<0:return
            if choice>=len(entries):continue
            action=entries[choice][1]
            if action=='refresh':continue
            leave=guide(data) if action=='guide' else dispatch(action,data)
            if leave:return True
        except Exception:
            message('Setup status or the selected action is unavailable. Check installed addons and try again.')
            return
