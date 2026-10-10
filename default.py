"""Standalone setup hub; addon accounts remain in their owning addons."""
import os
import sys
import xbmcaddon
import xbmcvfs

if __name__=='__main__':
    path=xbmcvfs.translatePath(xbmcaddon.Addon('script.mdm.conf').getAddonInfo('path'))
    sys.path.insert(0,os.path.join(path,'resources','lib'))
    from mdmconf.ui import run
    run()
