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


## Portable builds (0.2.0)

Conf > Build backups provides Create build, Local builds, Cloud builds, storage connection check and Restore recovery. This first format saves addon IDs/versions, supported portable addon settings and supported skin/interface preferences. It does **not** clone all Kodi userdata or copy Windows binaries to Android. Custom artwork files, media databases, account credentials, URLs and machine-local paths are excluded; some widgets and skin customisations cannot transfer yet.

Preview the downloaded build first. Install missing addons through enabled Kodi repositories, enable required addons, activate the recorded skin and reopen Conf. Installed addon versions are retained; differences and unsupported fields appear in the preview. Restore confirms the supported subset and saves the previous values before changing anything. Failures/cancellation trigger rollback; interruption requires Restore recovery before another restore. Recovery holds the most recent restore only. Restart Kodi after restore/recovery.

### Koofr setup

Koofr currently advertises a free 10 GB plan with no credit card required (checked 2026-10-10; future provider terms may change): https://koofr.eu/pricing/ . Create your account yourself, then create a dedicated application password under Koofr Preferences > Password. WebDAV requires that application password, not your main account password: https://koofr.eu/help/koofr_with_webdav/how-do-i-connect-a-service-to-koofr-through-webdav/ .

In Conf Storage settings select Koofr and enter your email and app password **on each device**. Check storage connection creates/confirms `MDM_Builds`. Choose a saved Local build to upload, then Cloud builds on another device to download and preview. Credentials stay in the local Kodi addon settings and are not encrypted by Conf; the password field is masked. Conf excludes its own settings from builds. Custom WebDAV requires a final HTTPS endpoint with no embedded login/query.

Uploads use unique identities, verify downloaded bytes and publish with no overwrite. Interrupted uploads can leave hidden `.upload-*` files; remove those in Koofr if desired. ZIP SHA-256 checks detect corruption but do not authenticate authors: use trusted builds. Transfers and archives are bounded (8 MiB archive / 4 MiB JSON); this configuration format deliberately has no bulk assets. Missing/disabled addons and a different active skin block restore.

Automated verification uses fake Kodi/WebDAV services. Real Koofr credentials and PC/Firestick transfer acceptance remain separate manual checks; no account data is used by the development tests. Full custom skin assets/widget layout portability and automatic device optimisation remain on the roadmap.
