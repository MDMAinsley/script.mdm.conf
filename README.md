# MDM Conf 0.1.0

Run MDM Conf from Program add-ons. This first batch is a standalone setup hub: inspect readiness, follow guided setup, open Flix/TMDB or selected-provider settings, open existing AllDebrid account tools, launch Flix, manage addons, and view device information. Conf needs only Kodi's Python API; it can explain missing addons before the rest of the MDM suite is installed.

Status distinguishes enabled, disabled, missing and unknown addons. Auto currently uses CocoScrapers; its account belongs to Flix. MDM Link owns its separate Free/Debrid/Combined settings and account. Combined without AllDebrid can use free providers; the hub explains how to add debrid candidates. Configured means the relevant value is present, not that credentials have been verified online or a provider will return a source. Custom stream URLs are counted as configured slots, not validated as working free/paid providers.

Conf reads configuration inside Kodi and displays only readiness. It does not copy credentials, alter provider settings, import accounts, enable addons or make account/network requests during a status check. Existing account tools perform their own explicit account actions. Opening the installed-addon browser leaves Conf; open it again after installation or enabling. Settings return to the hub and the next status read is fresh.

Device information reports platform, current total/free memory and current Kodi screen dimensions. Unknown values stay unknown. Current screen dimensions do not establish the display/decoder's maximum capability, and free memory is a transient reading. No automatic tuning or source filtering is enabled in 0.1.0.

Portable build backup/restore, private upload/download to other devices, device profiles and bandwidth/file-size filtering are agreed future batches in MDM_Conf_V1_Checklist.md. They are not implemented by this version. The storage service remains to be chosen when the remote-build batch starts.

Implementation references:
- Kodi addon/settings API: https://xbmc.github.io/docs.kodi.tv/master/kodi-base/dd/dae/group__python__xbmcaddon.html
- Installed-addon JSON-RPC schema: https://github.com/xbmc/xbmc/blob/master/xbmc/interfaces/json-rpc/schema/methods.json
- Device information labels: https://kodi.wiki/view/InfoLabels

Minimum manifest dependency is xbmc.python 3.0.0. Actual platform acceptance is recorded separately; declaration alone is not a compatibility claim.
