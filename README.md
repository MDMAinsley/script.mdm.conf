# MDM Conf 0.2.1

Run MDM Conf from Program add-ons. The standalone setup hub lets you: inspect readiness, follow guided setup, open Flix/TMDB or selected-provider settings, open existing AllDebrid account tools, launch Flix, manage addons, and view device information. Conf needs only Kodi's Python API; it can explain missing addons before the rest of the MDM suite is installed.

Status distinguishes enabled, disabled, missing and unknown addons. Auto currently uses CocoScrapers; its account belongs to Flix. MDM Link owns its separate Free/Debrid/Combined settings and account. Combined without AllDebrid can use free providers; the hub explains how to add debrid candidates. Configured means the relevant value is present, not that credentials have been verified online or a provider will return a source. Custom stream URLs are counted as configured slots, not validated as working free/paid providers.

Conf reads configuration inside Kodi and displays only readiness. It does not copy credentials, alter provider settings, import accounts, enable addons or make account/network requests during a status check. Existing account tools perform their own explicit account actions. Opening the installed-addon browser leaves Conf; open it again after installation or enabling. Settings return to the hub and the next status read is fresh.

Device information reports platform, current total/free memory and current Kodi screen dimensions. Unknown values stay unknown. Current screen dimensions do not establish the display/decoder's maximum capability, and free memory is a transient reading. Automatic tuning/source policies remain future work.

Configuration builds, Koofr/WebDAV transfer and journalled restore/recovery are implemented below. Complete custom assets/widgets and automatic optimisation remain future batches in MDM_Conf_V1_Checklist.md.

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


## Restore repair (0.2.1)

Kodi skin writes can return the assigned value, including false or an empty string. Conf verifies saved values instead of requiring a true return. Unchanged settings are skipped to avoid needless callbacks. New journals contain only changed settings; the existing 0.2.0 format and archives remain compatible.

If 0.2.0 left pending recovery, update Conf, keep the recorded skin active, then choose Build backups > Restore recovery **before trying another restore**. Do not delete the journal or replace your saved build. Recovery attempts available safe settings, keeps pending state if any remain unresolved, and names the affected setting identifiers in Restore diagnostics. Diagnostics shows no values, account details or raw exception text. Confirm recovery, restart Kodi, then check your source mode.


## Device tuning
Device-local profiles, reversible tuning, bounded worker/search/request settings and reported-quality limits. Light Flix artwork reduces image size and omits catalogue fanart. Unknown quality is configurable. TV/decoder capability is not inferred from the Kodi screen. Portable builds exclude device tuning; external scraper requests may finish after a deadline. No bandwidth ranking or cache/widget tuning in this release.
Use Conf Device profiles to preview/apply Low memory or Balanced and undo the last application. Low memory: Flix 2 workers, Link 1 worker, 90s search, 30s requests, Light artwork. Balanced: Flix 6 / Link 5 workers, 45s / 30s search, 15s requests, Standard artwork. Total memory at or below 2048 MB suggests Low memory; free-memory fluctuations do not reapply settings. Quality filtering happens after provider retrieval and again before resolving; both Flix and Link limits apply to Link playback. Set unknown quality to Hide for strict filtering, at the cost of fewer results. This is a preset, not a measured performance optimisation.


## Connection and file-size preferences
Connection speed, maximum reported GiB, explicit missing-metadata controls, estimated average bitrate with 25% reserve, and Quality/Connection/Smallest ordering. Debrid priority preserved; manual selection and single-source autoplay use the same limits. Device-local preferences; no speed probe or stability guarantee. Whole episode-pack sizes do not produce episode bitrate estimates. Conf provides preview/apply/undo for both addons.
Size uses GiB (1024^3 bytes), not decimal GB. Mbps uses 1,000,000 bits/s. Enter your own connection capacity; 0 disables connection classification. Average bitrate = reported size * 8 / title duration; 75% of entered speed is the budget. Variable bitrate peaks, host throughput and runtime accuracy can differ. Connection order: debrid first, then within each access group Fits estimate, Unknown, Above budget; quality breaks ties. Smallest order: debrid first, smaller reported sizes first, unknown last. A positive size cap filters size before sorting, including in Connection mode. Hide unknown size only acts with a positive size cap; Hide unknown bitrate/Above budget only acts with a positive connection. Defaults preserve quality order without new filtering. Torrent/package-size caps are conservative; an excluded pack may contain smaller eligible files. Current source limits are checked again before resolution and against debrid file/stream metadata where supplied. Returned metadata is not a verified download quota.
