"""Scan the official Google verification address and type the code on a phone."""
from pathlib import Path
from threading import Event, Thread

import xbmc
import xbmcgui

from . import builds, google_drive


class ApprovalDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args):
        self.cancelled = Event()
        self.approval = None
        self.worker = None
        self.refresh = None
        self.error = None

    def onInit(self):
        approval = self.approval
        self.getControl(10).setLabel(approval.address)
        self.getControl(11).setLabel(approval.code)
        self.getControl(12).setVisible(approval.address == google_drive.VERIFICATION)
        self.setFocusId(20)
        if self.worker is None:
            self.worker = Thread(target=self.poll_approval, daemon=True)
            self.worker.start()

    def onAction(self, action):
        if action.getId() in (9, 10, 92):
            self.cancel()

    def onClick(self, control):
        if control == 20:
            self.cancel()

    def cancel(self):
        self.cancelled.set()
        self.close()

    def poll_approval(self):
        try:
            self.refresh = google_drive.poll(
                self.client, self.approval,
                lambda seconds: self.cancelled.wait(seconds) or self.monitor.abortRequested(),
            )
        except builds.BuildError as error:
            self.error = error
        except Exception:
            self.error = builds.BuildError('Google sign-in could not complete. Try again.')
        finally:
            if not self.cancelled.is_set() and not self.monitor.abortRequested():
                self.close()


def connect(addon):
    client = google_drive.configuration()
    if not client:
        raise builds.BuildError('Google Drive phone setup is unavailable until the MDM Google TV client is configured.')
    monitor = xbmc.Monitor()
    approval = google_drive.start(client)
    if monitor.abortRequested():
        return False
    root = Path(__file__).resolve().parents[3]
    dialog = ApprovalDialog('GoogleDriveApproval.xml', str(root), 'default', '1080i')
    dialog.approval = approval
    dialog.client = client
    dialog.monitor = monitor
    try:
        dialog.doModal()
    finally:
        was_cancelled = dialog.cancelled.is_set()
        dialog.cancelled.set()
    if was_cancelled or monitor.abortRequested():
        return False
    if dialog.error:
        raise dialog.error
    if not dialog.refresh:
        return False
    google_drive.save_login(client, dialog.refresh)
    addon.setSetting('storage_provider', 'Google Drive')
    if addon.getSetting('storage_provider') != 'Google Drive':
        raise builds.BuildError('Kodi did not save the selected storage service.')
    xbmcgui.Dialog().ok('MDM Conf', 'Google Drive connected. You can create or restore a cloud build.')
    return True
