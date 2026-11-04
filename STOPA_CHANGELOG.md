# STOPA — Changelog

Formát: Conventional Commits + fáze. Nejnovější nahoře.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 12: cloud-export Microsoft + Amazon)

### Added (oblast D, P2 — port AXIOM extraktorů, 8 nových parserů / 12 AXIOM typů)
- **Microsoft Contacts** (`artifacts/ms_contacts.py`) — kontakty z Microsoft Graph/Outlook
  exportu (displayName/email/phone; tolerantní klíče name/displayName/givenName + surname,
  emailAddresses/emails, phoneNumbers). Vlastní účet → `relationship=account`. Name-based
  detekce s MS markerem v cestě. AXIOM `CloudMicrosoftContactsArtifact` +
  `CloudMicrosoftGraphContactsArtifact`. Artifact type `contact`, `details.engine=ms_contacts`.
- **Outlook Mail (PST export)** (`artifacts/ms_mail_pst.py`) — e-maily z Outlook/PST cloud
  exportu (subject/from/to/body/date; tolerantní klíče subject/From/Sender, To/Recipients,
  Body/TextBody, SentDateTime). Konverzační formát i plošný. AXIOM `CloudOutlookMessagesArtifact`
  + `CloudMicrosoftGraphMailMessagesArtifact`. Artifact type `email_message`,
  `details.engine=ms_mail_pst`.
- **Teams Conversations** (`artifacts/ms_teams_conversations.py`) — Teams konverzace/zprávy
  (senderDisplayName/body/timestamp; tolerantní klíče from/sender, body/content/text).
  Konverzační formát participants/messages i plošný. AXIOM `CloudMicrosoftTeamsConversationsArtifact`
  + `CloudMicrosoftGraphTeamsChatMessagesArtifact`. Artifact type `chat_message`,
  `details.engine=ms_teams_conversations`.
- **Teams Teams & Members** (`artifacts/ms_teams_teams.py`) — Teams týmy a členové
  (displayName/email/role; tolerantní klíče name/displayName, emailAddresses). Člen →
  `contact` s `mimetype=sns:microsoft:teams`, role owner/member. AXIOM
  `CloudMicrosoftTeamsArtifact`. Artifact type `contact`, `details.engine=ms_teams_teams`.
- **Outlook Calendar** (`artifacts/ms_outlook_calendar.py`) — Outlook kalendářové události
  (subject/organizer/start/end/location; tolerantní klíče subject, Start/StartTime, End/EndTime,
  Organizer). AXIOM `CloudMicrosoftCalendarEventsArtifact` +
  `CloudOutlookCalendarEventsArtifact`. Artifact type `calendar_event`,
  `details.engine=ms_outlook_calendar`.
- **SharePoint Warrant Return** (`artifacts/sharepoint_wr.py`) — SharePoint WR (strany →
  `web_page`, dokumenty → `document`; tolerantní klíče title/name, url/webUrl/link, size/fileSize).
  Auto-detekce kind podle struktury payloadu. AXIOM `CloudSharePointPagesArtifact` +
  `CloudSharePointDocumentsArtifact`. Artifact types `web_page`, `document`,
  `details.engine=sharepoint_wr`.
- **Amazon CloudTrail** (`artifacts/amazon_cloudtrail.py`) — CloudTrail API akce
  (eventName/eventTime/userIdentity/sourceIPAddress; tolerantní klíče eventSource, userIdentity
  s explicitním isinstance fallbackem). AXIOM `CloudAmazonCloudTrailEventsArtifact` +
  `CloudAmazonWarrantReturnCloudTrailArtifact`. Artifact type `event_log_entry`,
  `details.engine=amazon_cloudtrail`.
- **Amazon EC2 & S3** (`artifacts/amazon_ec2_s3.py`) — EC2 instance (instanceId/state/privateIp/
  publicIp; tolerantní klíče InstanceId, launchTime) → `network_connection` + S3 objekty
  (key/bucket/size/lastModified; tolerantní klíče Key/Name, Size/fileSize) → `file_metadata`.
  Union detekce podle struktury. AXIOM `CloudAmazonEC2InstancesArtifact` +
  `CloudAmazonS3ObjectsArtifact`. Artifact types `network_connection`, `file_metadata`,
  `details.engine=amazon_ec2_s3`.

### Pipeline dispatch + C3 registry
- Všech 8 parserů napojeno do `_sns_prepass()` — pre-pass na celé cestě PŘED basename chainem.
  Pořadí: specifické MS/Amazon detektory PŘED obecnějšími (conversations PŘED teams, aby
  „TeamsConversations" nekrálo generic teams); bez kolizí s Google contacts ani Twitter/SNS.
- C3 registry (`validation_registry.py`): 8 nových záznamů `ms_contacts`, `ms_mail_pst`,
  `ms_teams_conversations`, `ms_teams_teams`, `ms_outlook_calendar`, `sharepoint_wr`,
  `amazon_cloudtrail`, `amazon_ec2_s3`; limity srovnány s reálnými konstantami parserů (5000).
  `build_registry()` = **66 parserů** (předtím 58).

### Coverage matice
- Flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED: Microsoft Contacts/GraphContacts, Outlook
  Messages/GraphMailMessages, TeamsConversations/GraphTeamsChatMessages, Teams, CalendarEvents/
  OutlookCalendarEvents, SharePointPages/Documents, AmazonCloudTrail/WarrantReturnCloudTrail,
  EC2Instances, S3Objects. Regen `STOPA_COVERAGE_MATRIX.csv` + `docs/re-axiom/AXIOM_COVERAGE.{md,json}`
  deterministicky (SHA-256 diff ✓). covered **147 → 159 / 232**; cloud-export NOT_SUPPORTED
  **51 → 39**.

### Testy + verify
- `tests/test_w12_parsers.py` — **73 syntetických offline testů** (parse/build/detektory/
  pipeline pre-pass dispatch/C3 registry kontrakt per parser). Full suite **1626 passed,
  1 skipped** (baseline 1553 + 73); ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 11: cloud SNS exporty — Twitter/X + Facebook warrant return)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 13 AXIOM typů)
- **Twitter/X Posts** (`artifacts/twitter_posts.py`) — příspěvky z cloud
  exportu/warrant returnu (author/text/created_at; tolerantní klíče
  tweet_id/from_user/body/date). Retweety a odpovědi nesou `post_type`
  (retweet/reply). Name-based detekce s SNS markerem v cestě. AXIOM
  `CloudTwitterPostsArtifact` + `CloudTwitterPostsPublicArtifact` +
  `CloudTwitterWarrantReturnPostsArtifact`. Artifact type `sns_post`,
  `details.engine=twitter_posts`.
- **Twitter/X Direct Messages** (`artifacts/twitter_messages.py`) — DM
  konverzace (sender/recipient/text/timestamp; tolerantní klíče from/to/body).
  Konverzační formát (participants/messages) i plošný. Name-based detekce s SNS
  markerem v cestě. AXIOM `CloudTwitterDirectMessagesArtifact` +
  `CloudTwitterWarrantReturnDirectMessagesArtifact`. Artifact type
  `chat_message`, `details.engine=twitter_messages`.
- **Twitter/X Users** (`artifacts/twitter_users.py`) — uživatelé a sociální graf
  (screen_name/name/followers_count; tolerantní klíče username/full_name).
  Vlastní účet → `relationship=account`; sekce followers/following →
  `relationship=follower`/`following`. Name-based detekce s SNS markerem v
  cestě. AXIOM `CloudTwitterUsersArtifact` + `CloudTwitterUsersPublicArtifact` +
  `CloudTwitterWarrantReturnUsersArtifact`. Artifact type `contact` s
  `mimetype=sns:twitter`.
- **Facebook Warrant Return** (`artifacts/facebook_wr.py`) — Messenger zprávy
  (sender/recipient/body/timestamp; konverzační i flat formát), přátelé →
  `contact` (`sns:facebook`), timeline příspěvky (author/text/created_time) →
  `sns_post` s `post_type=timeline`, info o profilu (name/email/phone) →
  `contact` s `relationship=account`. Auto-detekce sekcí podle struktury
  payloadu. Name-based detekce s SNS markerem v cestě. AXIOM
  `CloudFacebookMessengerMessagesArtifact` + `CloudFacebookFriendsArtifact` +
  `CloudFacebookTimelineArtifact` + `CloudFacebookMobileTimelineArtifact` +
  `CloudFacebookProfileInfoArtifact`. Artifact types `chat_message`, `contact`,
  `sns_post`.

### Pipeline dispatch + C3 registry
- Všech 4 parserů napojeno do `_sns_prepass()` — pre-pass na celé cestě PŘED
  basename chainem (z vlny 10). Pořadí: twitter_posts → twitter_messages →
  twitter_users → facebook; bez kolizí s Instagram/Snapchat detektory ani s
  Google detektory (generic basenames `messages.json`/`Friends.json` bez SNS
  markery nepadnou do pre-passu — ověřeno dispatch testy).
- C3 registry (`validation_registry.py`): nové záznamy `twitter_posts`,
  `twitter_messages`, `twitter_users`, `facebook_wr`.
  `build_registry()` = **58 parserů** (předtím 54).

### Coverage matice (FÁZE 17)
- Flip 13 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **134 → 147 / 232**;
  cloud-export kategorie **64 → 51** (první vlna pod hranicí 50 se blíží);
  memory 0, portable-local 0, base-class 34. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 10: cloud SNS exporty — Instagram/Snapchat warrant return)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 20 AXIOM typů)
- **Instagram Direct Messages** (`artifacts/instagram_messages.py`) — DM
  konverzace z cloud exportu (participants/messages; tolerantní klíče
  sender/from, text/body, timestamp/time). Sdílená média v DM → `message_type=share`
  + `details.media_url`. Name-based detekce s SNS markerem v cestě. AXIOM
  `InstagramMessagesArtifact` + `CloudInstagramDirectMessagesArtifact` +
  `CloudFacebookInstagramMessagesArtifact` + `InstagramDirectSharesArtifact`.
  Artifact type `chat_message`, `details.engine=instagram_messages`.
- **Instagram Posts/Media/Stories/Comments** (`artifacts/instagram_posts.py`) —
  posts (caption/likes/media_url/timestamp), média, fotky, stories
  (`is_story=True` pro story_id/type) a komentáře (user/text/post_id). Name-based
  detekce s SNS markerem v cestě. AXIOM `CloudInstagramPostsArtifact` +
  `CloudInstagramPostsAxiom2Pt1Artifact` + `InstagramMediaArtifact` +
  `InstagramPhotosArtifact` + `InstagramArchivedStoriesArtifact` +
  `InstagramDirectStoriesArtifact` + `InstagramCommentsArtifact`. Artifact types
  `sns_post`, `sns_comment`.
- **Instagram Account Actions/History/Followers** (`artifacts/instagram_account.py`) —
  akce účtu (login/password_change/device/ip_address → `event_log_entry`) a
  followery/following (username/full_name/relationship → `contact` s
  `mimetype=sns:instagram`). Name-based detekce s SNS markerem v cestě. AXIOM
  `InstagramAccountActionsArtifact` + `InstagramAccountHistoryArtifact` +
  `InstagramFollowersAndFollowingArtifact`. Artifact types `event_log_entry`,
  `contact`.
- **Snapchat Warrant Return** (`artifacts/snapchat_wr.py`) — zprávy WR (from/to/
  body/time; konverzace i flat formát, group_id pro skupinové chaty), přátelé →
  `contact` (`sns:snapchat:user`), geolokace (lat/lon tolerantní klíče →
  `location_data`), IP historie (ip_address/event_type → `network_connection`) a
  info o účtu (username/email/phone → `contact`). Auto-detekce subtypu podle
  obsahu. Name-based detekce s SNS markerem v cestě. AXIOM
  `SnapchatMessagesWarrantReturnArtifact` + `SnapchatGroupChatMessagesArtifact` +
  `SnapchatFriendsArtifact` + `SnapchatGeolocationArtifact` +
  `SnapchatIpHistoryArtifact` + `SnapchatAccountInformationArtifact`. Artifact
  types `chat_message`, `contact`, `location_data`, `network_connection`.

### Pipeline dispatch + C3 registry
- Všech 4 parserů napojeno do `_sns_prepass()` — **nový pre-pass na celé cestě**
  PŘED basename chainem. Důvod: generic basenames (`photos.json`, `messages.json`)
  kolidují s Google detektory (Google Photos/Mail), které dostávají jen `name`.
- **Klíčové pořadí v pre-passu**: account detektor je PŘED posts — „AccountHistory"
  obsahuje substring „stor(y)", který by jinak chytil posts detektor.
- C3 registry (`validation_registry.py`): nové záznamy `instagram_messages`,
  `instagram_posts`, `instagram_account`, `snapchat_wr`.
  `build_registry()` = **54 parserů** (předtím 50).

### Coverage matice (FÁZE 17)
- Flip 20 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **114 → 134 / 232**;
  cloud-export kategorie **84 → 64** (největší jednorázový skok v ETAPA B);
  memory 0, portable-local 0, base-class 34. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 9: memory forensics — procesy/spojení/handlery/moduly/hooks)

### Added (oblast D, P2 — port AXIOM extraktorů, 5 nových parserů / 14 AXIOM typů)
- **Memory Processes** (`artifacts/mem_processes.py`) — paměťový dump: seznam
  procesů (pid/name/ppid/cmdline/threads/user/start_time). PsxView subtyp:
  rozdílné jméno EPROCESS vs PEB → anomaly flag `psxview_mismatch` (skrytý
  proces). Name-based detekce. AXIOM `ProcessListArtifact` + `ProcessesArtifact`
  + `ProcessScanArtifact` + `PsxViewArtifact`. Artifact type `mem_process`.
- **Memory Network Connections** (`artifacts/mem_network.py`) — paměťový dump:
  síťová spojení (pid/processName/proto/localAddress/remoteAddress/state).
  Proto i state normalizovány na uppercase. Name-based detekce. AXIOM
  `SocketsArtifact` + `OpenConnectionsArtifact` + `NetworkConnectionsArtifact`.
  Artifact type `mem_connection`.
- **Memory Handles** (`artifacts/mem_handles.py`) — paměťový dump: otevřené
  handlery procesů (pid/processName/handleValue/type/name). Handle value
  normalizován na hex string (int / decimal / hex tolerantně). Name-based
  detekce. AXIOM `HandlesArtifact` + `OpenHandlesArtifact`. Artifact type
  `mem_handle`.
- **Memory Modules** (`artifacts/mem_modules.py`) — paměťový dump: načtené
  moduly (pid/processName/baseAddress/size/name/inLdrList). Adresa normalizována
  na hex. Malfind subtyp: modul v paměti ale ne v LDR listu → anomaly flag
  `hidden_module` (indikátor DLL injection). Name-based detekce. AXIOM
  `ModScanArtifact` + `MalfindArtifact`. Artifact type `mem_module`.
- **Memory API Hooks / Callbacks** (`artifacts/mem_hooks.py`) — paměťový dump:
  zaregistrované hooky a callback funkce (pid/processName/apiFunction/
  callbackAddress/module/hookType). Adresa normalizována na hex. Name-based
  detekce. AXIOM `ApiHooksArtifact` + `CallbacksArtifact` +
  `ExecutiveObjectCallbacksArtifact`. Artifact type `mem_hook`.

### Pipeline dispatch + C3 registry
- Všech 5 parserů napojeno do `NAME_BASED_EXTRACTORS` + `_name_based_match()`.
- **Klíčové pořadí**: memory detektory jsou v dispatchi **PŘED netstatem** —
  sdílená klíčová slova (`connections`, `sockets`) by jinak vedla memory exporty
  do textového netstat parseru. Memory exporty jsou JSON, parsery defenzivní
  (ne-JSON → `[]`), takže cizí soubory projdou bez artifactů.
- C3 registry (`validation_registry.py`): nové záznamy `mem_processes`,
  `mem_network`, `mem_handles`, `mem_modules`, `mem_hooks`.
  `build_registry()` = **50 parserů** (předtím 45).

### Coverage matice (FÁZE 17)
- Flip 14 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **100 → 114 / 232**;
  memory kategorie **vyzerovala 14 → 0 ★** (jako portable-local ve vlně 4);
  cloud-export 84, base-class 34. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 16 AXIOM typů)
- **Google Chrome Preferences** (`artifacts/chrome_preferences.py`) — Chrome
  Preferences JSON (profilový export; `extensions.settings` → rozšíření s
  manifest name/version/stavem, `default_search_provider_data` + custom search
  engines, `sync.data_type_enabled`). Name-based detekce. AXIOM
  `CloudGoogleChromeExtensionsArtifact` + `CloudGoogleChromeExtensionSettingsArtifact`
  + `CloudGoogleChromeSearchEnginesArtifact` + 3× SyncSettings. Artifact types
  `browser_extension`, `browser_setting`.
- **Cloud Drive soubory** (`artifacts/cloud_drive_files.py`) — Google Drive /
  OneDrive / Apple Drive JSON (Takeout/warrant return; název, velikost, MD5
  checksum, MIME, created/modified ISO 8601 i epoch s → unix s). Provider
  auto-detekován podle markerů (`sizeBytes`/`md5Checksum` = Google,
  `lastModifiedDateTime` = OneDrive, název = Apple). Name-based detekce. AXIOM
  `CloudDriveFileArtifact` + `CloudDriveFileVersionArtifact` +
  `CloudOneDriveFileArtifact` + `CloudOneDriveFileVersionArtifact` +
  `CloudAppleDriveArtifact`. Artifact type `cloud_file`.
- **Google Voice Warrant Return** (`artifacts/google_voice_wr.py`) — Google
  Voice JSON s auto-detekcí subtypu (SMS texty / hlasové schránky / kontakty /
  informace o předplatiteli; `timestampMsInEpoch` → unix s). Name-based detekce.
  AXIOM `GoogleVoiceTexts2025Artifact` + `GoogleVoicemail2025Artifact` +
  `GoogleVoiceContactsMetadata2026Artifact` +
  `GoogleVoiceSubscriberInformation2026Artifact`. Artifact types `sms_message`,
  `voicemail`, `contact`, `google_account`.
- **Windows Drivers** (`artifacts/win_drivers.py`) — Windows drivers JSON (live
  forensics / paměťový dump; `driverName`, `baseAddress` normalizace na hex,
  velikost, signatura, popis). Nesignovaný driver → anomaly flag
  `unsigned_driver`. Name-based detekce. AXIOM `DriversArtifact`. Artifact type
  `win_driver`.

### Pipeline dispatch + C3 registry
- Všech 4 parserů napojeno do `NAME_BASED_EXTRACTORS` + `_name_based_match()`.
- **Nový mechanismus**: Takeout soubory se generic názvy (`Drive/Files.json`,
  `Voice/Texts.json`) — klíčové slovo je v rodičovské složce, ne v basename.
  `_extract_artifacts_for()` teď při selhání name-based matche na basename retry
  na celé cestě (parsery jsou defenzivní → cizí soubory projdou bez artifactů).
- C3 registry (`validation_registry.py`): nové záznamy `chrome_preferences`,
  `cloud_drive_files`, `google_voice_wr`, `win_drivers`.
  `build_registry()` = **45 parserů** (předtím 41).

### Coverage matice (FÁZE 16)
- Flip 16 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **84 → 100 / 232** ★
  (první stovka!); cloud-export **99 → 84**, memory **15 → 14**. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 7: Chrome Bookmarks/History/Autofill + Contacts + Skype WR)

### Added (oblast D, P2 — port AXIOM extraktorů, 5 nových parserů / 12 AXIOM typů)
- **Google Chrome Bookmarks** (`artifacts/google_chrome_bookmarks.py`) — Chrome
  Bookmarks JSON (Takeout/warrant return; rekurzivní walk `roots`, `date_added`
  µs od 1601 → unix s, folder path z hierarchie). Name-based detekce. AXIOM
  `GoogleChromeBookmarksWarrantReturnArtifact` + `CloudGoogleChromeBookmarksArtifact`.
  Artifact type `browser_bookmark`.
- **Google Chrome History Warrant Return** (`artifacts/google_chrome_history_wr.py`) —
  Chrome History warrant return JSON (pole záznamů; `url`, `title`, `visit_time`
  µs od 1601 → unix s, transition_type). Name-based detekce. AXIOM
  `GoogleChromeHistoryWarrantReturnArtifact`. Artifact type `browser_history`.
- **Google Contacts Warrant Return** (`artifacts/google_contacts_wr.py`) — Google
  Contacts Takeout/warrant JSON (pole kontaktů; `name`/`givenName`/`familyName`,
  `emails[]`, `phoneNumbers[]`; People API fallback `names[].displayName`).
  Name-based detekce. AXIOM `GoogleContactsWarrantReturnArtifact` +
  `CloudGoogleContactsArtifact`. Artifact type `contact`.
- **Google Chrome Autofill / Contact Info** (`artifacts/google_chrome_autofill.py`) —
  Chrome Autofill/Contact Info JSON (pole záznamů; `name`, `email`, `phoneNumber`,
  adresa). Name-based detekce. AXIOM `GoogleChromeAutofillWarrantReturnArtifact` +
  `GoogleChromeContactInfoWarrantReturnArtifact` + `CloudGoogleChromeAutofillArtifact`.
  Artifact type `autofill_entry`.
- **Skype Warrant Return** (`artifacts/skype_warrant_return.py`) — Skype warrant
  return JSON s auto-detekcí subtypu (account details / chat history records /
  connection history / contacts; `composetime` ISO 8601 i epoch ms → unix s).
  Name-based detekce. AXIOM `SkypeWarrantReturnAccountDetailsArtifact` +
  `SkypeWarrantReturnChatHistoryRecordsArtifact` + `SkypeWarrantReturnConnectionHistoryArtifact`
  + `SkypeWarrantReturnContactsArtifact`. Artifact types `skype_account`,
  `messenger_message`, `contact`.

### Pipeline dispatch + C3 registry
- Všech 5 parserů napojeno do `NAME_BASED_EXTRACTORS` + `_name_based_match()`
  (specifické detekce PŘED obecnějšími Google/Skype detekcemi).
- C3 registry (`validation_registry.py`): nové záznamy `chrome_bookmarks`,
  `chrome_history_wr`, `contacts_wr`, `chrome_autofill`, `skype_warrant_return`.
  `build_registry()` = **41 parserů** (předtím 36).

### Coverage matice (FÁZE 15)
- Flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **72 → 84 / 232**;
  cloud-export **111 → 99**. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 6: Google local profile/takeout + přílohy)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 4 AXIOM typy)
- **Google Photos** (`artifacts/google_photos.py`) — Photos Takeout/warrant JSON
  (pole objektů; `photoTakenTime` ISO 8601 i epoch ms → unix s, `geoData` E7
  souřadnice → stupně, description/mediaItemType). Name-based detekce. AXIOM
  `GooglePhotosArtifact`. Artifact type `google_photo`.
- **Google Mail Message Information** (`artifacts/google_mail_info.py`) — Gmail
  warrant return JSON (pole zpráv; `threadId`, `internalDate` µs od Unix epochy i
  epoch s, from/to/cc jako objekt `{"emailAddress": …}` i plain string). Name-based
  detekce. AXIOM `GoogleMailMessageInformationArtifact`. Artifact type
  `google_mail_info`.
- **Google Bar** (`artifacts/google_bar.py`) — Chrome/Edge History DB tabulka
  `search_terms` (omnibox dotazy z lišty; `term`, `time_last_used` Chrome µs,
  weight/source). Bonus hook v `_extract_chrome_history` (`sqlite_extract.py`).
  AXIOM `GoogleBarArtifact`. Artifact type `browser_search`.
- **Attachment Extractor** (`artifacts/attachment_extractor.py`) — MIME/RFC822
  přílohy (multipart walk; filename z Content-Disposition, content-type, velikost
  z Content-Length bez dekodování payloadu). Bonus hook v `email_mbox` — každá
  příloha → samostatný artifact. AXIOM `AttachmentExtractor`. Artifact type
  `email_attachment`.

### Pipeline dispatch + C3 registry
- Photos a Mail Message Information napojeny do `NAME_BASED_EXTRACTORS` +
  `_name_based_match()` (specifické detekce PŘED obecnějšími Google detekcemi).
- Google Bar bonus v `_extract_chrome_history`; AttachmentExtractor bonus v
  `email_mbox` (bezpečné — existující fixtures nemají přílohy/`search_terms`).
- C3 registry (`validation_registry.py`): nové záznamy `google_photos`,
  `google_mail_info`, `attachment_extractor`; sdílené `sqlite` + `email_mbox`
  rozšířeny. `build_registry()` = **36 parserů** (předtím 34).

### Coverage matice (FÁZE 15)
- Flip 4 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **68 → 72 / 232**;
  portable-local **4 → 0** ★ (všechny lokální typy pokryty). Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 5: Google Takeout rodina + Samsung voice)

### Added (oblast D, P2 — port AXIOM extraktorů, 6 nových parserů / 12 AXIOM typů)
- **Google Aggregated Activities** (`artifacts/google_aggregated_activities.py`) —
  „My Activity" daily JSON export (pole dní s `activities`); identity sessions
  varianta (deviceInfo + session timestamps). Name-based detekce. AXIOM
  `GoogleAggregatedActivitiesArtifact` + `…IdentitySessionsArtifact`. Artifact types
  `google_activity` / `google_identity_session`.
- **Google Maps Activity** (`artifacts/google_maps_activity.py`) — semantic location
  history JSON (`timelineObjects`: placeVisit s E7 souřadnicemi → stupně,
  activitySegment s distance/activityType/confidence). Name-based detekce. AXIOM
  `GoogleMapsActivityArtifact`. Artifact type `google_maps_activity`.
- **Google Chat rodina** (`artifacts/google_chat_family.py`) — sdílený Takeout JSON
  parser pro 4 IM typy (conversations → events, segment text). Name-based detekce.
  AXIOM `GoogleChatArtifact` / `GoogleHangoutsArtifact` / `GooglePlusChatArtifact` /
  `GoogleTalkArtifact`. Artifact type `chat_message`.
- **Google Account metadata** (`artifacts/google_account_meta.py`) — account change
  history (eventy), linked devices, export summary. Name-based detekce. AXIOM
  `GoogleAccountChangeHistoryArtifact` / `GoogleDevicesArtifact` /
  `GoogleExportSummaryArtifact`. Artifact types `google_account_event` /
  `google_device` / `google_export_summary`.
- **Google Drive Activity** (`artifacts/drive_activity.py`) — JSON log aktivit souborů
  (fileId/fileName/action/timestamp, unix s i ISO). Name-based detekce. AXIOM
  `DriveActivityArtifact`. Artifact type `drive_activity`.
- **Samsung Voice Recording** (`artifacts/samsung_voice_recording.py`) — legacy mobile
  voice recorder SQLite DB; schéma-based (tabulka nahrávek, duration ms→s heuristika).
  Napojen do `sqlite_extract.py` dispatch chainu. AXIOM `SamsungVoiceRecordingArtifact`.
  Artifact type `voice_recording`.

### Pipeline dispatch + C3 registry
- Google Takeout JSON rodina (aggregated, maps, chat family, account meta, drive)
  napojena do `NAME_BASED_EXTRACTORS` + `_name_based_match()`; specifické detekce
  PŘED obecnějšími vlna-2 Google detekcemi.
- Samsung Voice Recording (SQLite schéma-based) napojen do `sqlite_extract.py`
  dispatch chainu před Kik/generic fallbackem.
- C3 registry (`validation_registry.py`): nové záznamy pro 8 name-based parserů;
  sdílený `sqlite` rozšířen o Samsung. `build_registry()` = **34 parserů** (předtím 26).

### Coverage matice (FÁZE 15)
- Flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **56 → 68 / 232**;
  portable-local **16 → 4**. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-03 (ETAPA B vlna 4: portable-local AXIOM porty)

### Added (oblast D, P2 — port AXIOM extraktorů, 6 nových parserů)
- **DuckDuckGo Cookies** (`artifacts/ddg_cookies.py`) — Chromium cookies SQLite
  schéma (`host_key/name/value/expires_utc` µs od Windows epochy 1601); detekce
  schéma-based (tabulka `cookies` s `host_key`+`name`), hodnota plaintext jen když
  existuje (Chromium v10+ AES-GCM `encrypted_value` neinterpretujeme). AXIOM
  `DuckDuckGoCookiesArtifact`. Artifact type `browser_cookie`.
- **DDG Allowlisted Websites** (`artifacts/allowlisted_websites.py`) — JSON seznam
  webů s vypnutou tracker protection (pole domén nebo objekt s klíčem
  `exceptions`/`allowlist`/…). Name-based detekce. AXIOM `AllowlistedWebSitesArtifact`.
- **OpenOffice/LibreOffice Base** (`artifacts/openoffice_base.py`) — `.odb` = ZIP/ODF
  kontejner; potvrzení přes `mimetype` + DC metadata (title/creator/date) z
  `content.xml`. Name-based detekce. AXIOM `OpenOfficeBaseArtifact`.
- **iOS Parked Car Locations** (`artifacts/parked_car_locations.py`) — iOS
  `Local.sqlite` tabulka `ZRTVEHICLEEVENTMO` (Routined Location Services); čas
  CFAbsoluteTime, souřadnice `ZLOCLATITUDE/ZLOCLONGITUDE`. Schéma-based. AXIOM
  `ParkedCarLocationsArtifact`. Artifact type `location_data`.
- **iOS Voicemail** (`artifacts/ios_voicemail.py`) — iOS `voicemail.db` tabulka
  `voicemail`; `date`=unix s, `trashed_date`=CFAbsoluteTime (0 = nedělaná).
  Schéma-based. AXIOM `VoiceMailArtifact`. Artifact type `voicemail`.
- **Windows UserAssist MRU** (`artifacts/win_userassist.py`) — NTUSER.DAT registry:
  ROT13 value names + binární payload (run count u32@0, focus time ms u32@4,
  last run FILETIME q64@8); GUID `{CEBFF5CD…}` = programy / `{F4E57C4B…}` = dokumenty.
  Běží v registry chainu (sdílená `regf` magic). Artifact type `app_execution`.

### Pipeline dispatch + C3 registry
- SQLite parsery (ddg_cookies, parked_car_locations, ios_voicemail) napojeni do
  `sqlite_extract.py` dispatch chainu (schéma-based, pattern jako Kik).
- UserAssist přidán do `_extract_registry_all()` (bonus průchod NTUSER.DAT).
- Name-based extraktory: `allowlisted_websites`, `openoffice_base` do
  `NAME_BASED_EXTRACTORS` + `_name_based_match()`.
- C3 registry (`validation_registry.py`): nové záznamy `allowlisted_websites`,
  `openoffice_base`; sdílené `sqlite`/`registry_hive` rozšířeny o vlna 4 formáty.

### Coverage matice (FÁZE 15)
- **5 přímých AXIOM flipů NOT_SUPPORTED → SUPPORTED**: DuckDuckGoCookies,
  AllowlistedWebSites, OpenOfficeBase, ParkedCarLocations, VoiceMail.
- **Coverage: 51 → 56 / 232** (SUPPORTED), NOT_SUPPORTED 147 → 142.

### Testy
- **33 nových testů** (`tests/test_w4_parsers.py`) — syntetické fixtures plně offline:
  in-memory SQLite pro DB parsery, FakeHive/FakeKey pro UserAssist (pattern
  `test_win_sids`), ZIP kontejner pro .odb; detekce + extrakce + pipeline dispatch.

### Backward compat
- Žádné breaking changes — nové artifact typy (`browser_cookie`, `location_data`,
  `voicemail`, `app_execution`) do volného TEXT sloupce `artifacts.artifact_type`
  bez migrace; stávající parsery nezměněni.

## [Unreleased] — 2026-11-03 (STP-023 Export: JSONL/XML/STIX formáty)

### Added (oblast K/Q, P3)
- **JSONL export** (`to_jsonl`) — jeden objekt na řádek, streamovací formát pro velké sady; `ensure_ascii=False` (česky čitelné).
- **XML export** (`to_xml`) — deterministický XML dokument přes ElementTree (UTF-8 deklarace, `ET.indent`); kořen `stopa_<dataset>`, záznamy `<artifact>/<event>/<correlation>`; None hodnoty vynechány, dict/list jako JSON.
- **STIX 2.1 bundle export** (`to_stix_bundle`) — validní STIX 2.1 bundle: artefakty → objekty `file`/`message` (konzervativní mapa typů), ostatní datasety → `x-stopa-record`; původní záznamy v rozšíření `x-stopa`; **deterministická UUIDv5 ID** ze STOPA namespace (reprodukovatelnost C4 — stejný vstup = stejné bundle).
- CLI `stopa export --format` rozšířen: `csv|json|jsonl|xml|stix` (default csv); C4 manifest + integrity checkpoint fungují pro všechny formáty.

### Testy
- **17 nových testů** (`tests/test_stp023.py`) — JSONL řádkování/česky/prázdný vstup; XML validita/root tagy/determinismus; STIX struktura/mapping typů/deterministická ID/ASCII-safe name/x-stopa rozšíření; CLI export do souboru (JSONL/XML) + stdout (STIX) + C4 manifest.

### Backward compat
- Stávající `to_csv`/`to_json` a sloupcová schémata nezměněna; default formát zůstává CSV.

## [Unreleased] — 2026-11-03 (STP-022 Security: SHA-512 integrity vrstva + RBAC minimální + pip-audit CI)

### Added (oblast M, priorita P2 — court-ready integrity + atribuce operací)
- **SHA-512 v integrity vrstvě** (`domain/integrity.py`): `compute_audit_hash(..., algo=)`
  a `verify_chain(rows, algo=)` s parametrem `"sha256"` (výchozí, backward compat —
  stávající řetězce i testy nezměněné) nebo `"sha512"`. **Per-algorithm GENESIS**
  (`_GENESIS_BY_ALGO`: SHA-256 = `0×64`, SHA-512 = `0×128`) + fail-fast validace
  neznámého algoritmu. Exportní manifesty: `build_manifest(include_sha512=True)`
  opt-in — `ManifestEntry.sha512` (default None → backward compat hash manifestu).
- **SHA-512 v pipeline** (`models.py`, `domain/profiles.py`, `pipeline.py`):
  `ProcessingProfile.compute_sha512: bool = False`; **FORENSIC profil počítá SHA-512**
  (ediscovery/quick ne) — v **jednom průchodu** s ostatními algs (hashlib multi-hash,
  bez druhého čtení souboru). `FileRecord.sha512` + sloupec `files.sha512`
  (SCHEMA + idempotentní migrace pro staré case DB); dedupe seed i check zahrnují
  SHA-512; `search_by_hash()` = exact lookup přes **SHA-256 / SHA-512 / MD5**.
- **Report CoC** (`domain/report.py`, `presentation/case_report.py`):
  `CustodyItem.sha512`; manifest tabulka v HTML reportu dostane sloupec **SHA-512
  jen když existuje** (staré case DB bez SHA-512 → vizuálně nezměněný report).
- **RBAC minimální** (`domain/rbac.py` — čistá logika bez IO): `normalize_actor()`
  (trim, max 128 znaků), `require_actor()` (+`ActorError`), `resolve_actor()`.
  `db.log_operation(..., strict=False)` — atribuce operace: **explicitní actor >
  case examiner > None** (backward compat); `strict=True` vyžaduje actora
  (pro budoucí multi-user režim).
- **pip-audit CI** (`.github/workflows/ci.yml`): nový job `security` — audit známých
  zranitelností v závislostech (PyPI Advisory DB) přes `pip freeze | grep -v "^-e \|^stopa @\|^stopa==" > requirements.txt && pip-audit --no-deps -r requirements.txt`
  (přímo `-r pyproject.toml` nefunguje — pip-audit chce requirements formát;
  editovatelný stopa jako VCS link by se snažil buildovat).

### Testy
- **32 nových testů** (`tests/test_stp022.py`): SHA-512 audit chain (délka hexdigestu,
  determinismus, tamper detekce, per-algorithm GENESIS, neznámý algoritmus → ValueError),
  manifesty s/SHA-512 opt-in + backward compat hash, RBAC (normalizace, require_actor,
  resolve_actor fallback na examinera, strict režim), `log_operation` atribuce
  (explicitní > examiner > None), DB sloupec sha512 (upsert/read/migrace staré DB),
  pipeline SHA-512 v jednom průchodu (FORENSIC vs. quick profil), `search_by_hash()`
  přes SHA-512, report CoC manifest s/SHA-512 sloupec.

## [Unreleased] — 2026-11-03 (STP-021 Performance: stream parsing velkých E01 + progress monitoring)

### Added (oblast N/O, priorita P2 — výkon ingestu + viditelnost zpracování)
- **Stream parsing E01/AFF4** (`data/ewf_container.py`): nové veřejné API
  `stream_to_raw(path, typ, dest, progress=None)` — pravý chunked stream
  (1 MiB chunky přímo z kontejneru do RAW souboru). `_ewf_read()`/`_aff_read()`
  refaktorovány na generátory `_ewf_chunks()`/`_aff_chunks()`; `read_container()`
  zůstává jako tenký wrapper (backward compat). **RAM peak klesá z velikosti
  celého obrazu (GB) na jednu chunku (~1 MiB)** — klíčové pro velké E01.
- **Byte-level progress** (`data/image_pipeline.py`): `process_disk_image()`
  dostal keyword-only parametr `extract_progress: Callable[[int, int], None]`;
  extrakce kontejneru jde přes `stream_to_raw(..., progress=...)`.
- **Web Processing Monitor** (`web/app.py`): in-memory job registry + nový
  endpoint `GET /api/cases/{case_id}/processing` (aktivní běh + poslední 10).
  `POST /sources` dostal opt-in flag `background: bool = False`:
  - **sync (default)** — backward compat, stejná pole odpovědi (+ `job_id`);
    progress se zapisuje do registru;
  - **async** — request vrací 201 okamžitě (`source_id=null`, `job_id`,
    `status=running`), ingest běží v daemon threadu s vlastním DB spojením
    (per-thread `sqlite3.connect` → thread-safe bez globálního locku).
- **GUI progress** (`static/index.html`, `js/components/modules.js`): checkbox
  „pozadí" ve formuláři zdroje; při async ingestu frontend polluje
  `/processing` každých 500 ms a status bar zobrazuje živý progress
  („Zpracovávám zdroj: … — 42/180").

### Testy
- 7 nových testů (`tests/test_stp021.py`): stream roundtrip E01/AFF4
  (byte-for-byte shoda s `read_container`, přes 2 chunky), progress callback
  (monotónní done, finální total == velikost obrazu), neznámý typ → EwfError,
  web sync ingest (backward compat pole + job registry) a **web async ingest**
  (201 okamžitě → poll /processing až `done`, source zapsán do DB).

## [Unreleased] — 2026-11-03 (STP-019 AI governance + PII redaktor)

### Added (oblast H/M, priorita P2 — důvěryhodnost AI vrstvy)
- `domain/pii_redaction.py` — **PII redaktor pro LLM prompty** (deterministický,
  bez I/O): maskuje telefony (`+420****3456`), e-maily (`j***@example.com`),
  WhatsApp JID (`wa:+420****3456`) a platformní handle (`skype:j***`) ve všech
  prompt messages PŘED odesláním do LLM. Stavební kameny (regexy, normalizace)
  opakovány z `entities.py` / `entity_resolution.py` — žádná nová heuristika;
  priorita při překryvu JID > e-mail > handle > telefon. Vrací seznam detekcí
  (`PiiDetection`) pro audit.
- **I1 orchestrace** (`intelligence/ai_orchestrator.py`): `build_prompt()` a
  `orchestrate()` dostaly parametr `redact_pii: bool = True` (default ON —
  fail-safe). Auditní SHA-256 promptu se počítá nad redigovaným textem, takže
  odpovídá tomu, co LLM skutečně uviděl.
- **E11 asistent** (`domain/ai_assistant.py`): všechny tři prompt buildery
  (`nl_search`/`summary`/`explain`) maskují PII podle `redact_pii`.
- **Audit E11 modelových volání** (`web/app.py`): dříve auditoval jen I1 —
  teď zapisují `ai_query` záznam (model name + SHA-256 promptu + citace,
  agent `e11:<režim>`) i všechny tři režimy E11.
- **Settings toggle** `ai_redact_pii` (default ON): `GET/PUT /api/settings`,
  CLI `stopa analyze` čte `settings.json` z db_dir (`_load_ai_redact_pii()`).

### Testy
- 23 nových testů (`tests/test_pii_redaction.py`): domain logika (maskování,
  detekce, determinismus, priority), I1 orchestrace (redakce v promptu +
  propis do `llm_call`), E11 buildery a **web E2E** s mockovaným LM Studio —
  PII zmaskovaná před `chat()`, auditní záznamy v `analysis_operations`,
  toggle OFF → surová PII + odlišné prompt hash.
- Full suite **1110 passed, 1 skipped** (baseline 1087 + 23); ruff clean.

## [Unreleased] — 2026-11-03 (STP-020 Report engine 9→20 sekcí)

### Added (oblast L, priorita P1 — court-ready report výstupy)
- `domain/report.py` — rozšíření HTML/PDF reportu z **9 na 20 sekcí**:
  - **Titulní strana** (cover): název případu, ID, znalec, datum vytvoření/
    generování, verze nástroje; nová CSS třída `.cover`.
  - **Sekce 10 — Metodika analýzy**: deterministicky z dat (počet zdrojů/
    souborů/bajtů, signatury, počet parserů C3 registry, korelace entit,
    Timeline Intel okno).
  - **Sekce 11 — Nástroje a verze**: STOPA/Python/SQLite/platforma z
    `env_snapshot()` (C5) + dostupnost TSK/EWF/cryptsetup (E12 diagnostics).
  - **Sekce 12 — Omezení analýzy**: RAM peak (BLK-001), confidence omezení,
    truncation limity.
  - **Sekce 13 — Závěr**: souhrn findings + počty rozporových/duplikátových
    skupin (STP-018).
  - **Sekce 14 — Provenience timestampů**: source vs derived (STP-018).
  - **Sekce 15 — Evidence lineage** (C2, počet kroků).
  - **Sekce 16 — Integrity Ed25519** (C4, veřejný klíč + kontrolní body).
  - **Sekce 17 — Rejstřík entit** (E4/I3).
  - **Sekce 18 — Příloha A: validace parserů** (C3 registry, deterministické
    pořadí).
  - **Sekce 19 — Příloha B: reprodukční prostředí** (C5 snapshot).
  - **Sekce 20 — Příloha C: rozložení důvěryhodnosti** (timeline + korelace).
- `domain/i18n.py` — ~60 nových klíčů cs/en pro sekce 10–20.
- `presentation/case_report.py` — defenzivní naplnění nová pole `ReportData`
  z case DB (entity, lineage, integrity checkpoints + veřejný klíč).
- Backward compat sekcí 1–9 zachována (testy asertují texty, ne čísla).

### Testy
- 14 nových testů (`tests/test_report.py`, třída `TestStp020Sections`):
  presence + pořadí všech 20 sekcí, obsah každé nové sekce na syntetickém
  bohatém případě (fixture `rich_data`), empty fallbacky u prázdného případu,
  regrese nevyhodnocených `{placeholder}`.
- Full suite **1087 passed, 1 skipped** (baseline 1073 + 14); ruff clean.

## [Unreleased] — 2026-11-03 (STP-018 Timeline Intelligence 2.0)

### Added (oblast E, priorita P2 — analytické vrstvy nad materializovanou timeline)
- `domain/timeline_intel.py` — **nový čistý modul bez IO** (301 řádků), tři
  analytické vrstvy:
  - **Rozpory** `concurrent_activity`: stejná normalizovaná entita ve dvou
    událostech v časovém okně (default 60 s) + odlišný typ/soubor; union-find
    tranzitivní uzavření, deterministické group ID (SHA-256).
  - **Duplikáty napříč zdroji** `cross_source_duplicate`: stejný obsah
    (typ+title) z ≥2 různých zdrojů/souborů; provenance všech výskytů zachována.
  - **Timestamp provenance**: `ts_origin` (source vs derived) + klasifikace
    přesnosti (`second`/`millisecond`/`microsecond`/`file_metadata`/`unknown`).
- Schéma **v12** (`db.py`): nové sloupce `timeline_events` — `ts_origin`,
  `subject_values_json`, `contradiction_group_id`, `dup_group_id`; idempotentní
  migrace `_migrate_timeline_intel()` (ALTER TABLE, bez ztráty dat);
  `add/list_timeline_event(s)` rozšířené; nové metody `set_timeline_intel_groups()`
  (idempotentní UPDATE + merge flagů do `anomaly_flags`) a
  `clear_timeline_intel_groups()`.
- Pipeline: timeline insert naplňuje `subject_values` (přes `extract_entities`,
  defenzivně) + `ts_origin`; nový post-pass **`run_timeline_intel(db,
  window_seconds=60)`** — clear → analyze → materializace; souhrn pro log/UI.
- CLI: `stopa add` spouští post-pass automaticky po ingestu;
  `stopa timeline --intel [--window N]` explicitně + tisk rozporů/duplikátů.
- Web: POST `/api/cases/{id}/timeline/intel?window_seconds=60`; GET timeline
  vrací nové sloupce automaticky (`{**e}`).
- Report sekce 8 → podsekce **Timeline Intelligence 2.0**: rozpory po skupinách
  + duplikáty s provenance; i18n klíče cs/en.
- Export: `TIMELINE_COLUMNS` + `timeline_records()` rozšířené o nové sloupce
  (reprodukovatelnost).
- Model: `Artifact.ts_origin = "source"` default (staré parsery se nemění —
  používají jen source časy, FS fallback nepoužívají).

### Testy
- 32 nových testů (`tests/test_timeline_intel.py`): čistá logika (rozpory,
  duplikáty, provenance na syntetických fixtures), DB migrace v10→v12 (bez ztráty
  dat + idempotence), roundtrip add/list, post-pass materializace + idempotence.
- Full suite **1073 passed, 1 skipped**; ruff clean.

## [Unreleased] — 2026-11-03 (ETAPA B vlna 3)

### Added (ETAPA B vlna 3 — port AXIOM extraktorů, 5 nových parserů + 75 testů)
- `artifacts/kik_messenger.py` — **Kik Messenger parser** (AXIOM
  `KikLocalUserExtractor`): SQLite dispatch chain v `sqlite_extract.py` — iOS
  `kik.sqlite` schéma (`ZKIKUSER`/`ZKIKMESSAGE`, prefix ZKIK) i Android aliasy
  (`users`+`messages`); defenzivní mapování sloupců přes aliasy, epoch s/ms;
  artifact typy `kik_user` / `kik_message`. Detekce schéma-based (iOS stačí
  `ZKIK*`, Android vyžaduje obě tabulky — proti false-positive na obecných DB).
- `artifacts/mailru_agent.py` — **Mail.ru Agent parser** (AXIOM
  `MailRuChatArtifact` + `MailRuContactArtifact` + `MailRuGroupArtifact`):
  desktop IM lokální logy, textový formát s `|` oddělovači; typ zprávy a délka
  z hranatých závorek, kontakty i skupiny; artifact typy `mailru_chat` /
  `mailru_contact` / `mailru_group`. Detekce name/content-based.
- `artifacts/bebo_chat.py` — **Bebo Live Chat parser** (AXIOM `BeboArtifact`):
  textový chat log (`[ts] user said:`) i JSON pole záznamů; konzervativní JSON
  detekce (objekt, uzavřené pole s `{}`/`""`, kompaktní pole v 1. řádku);
  artifact type `bebo_chat`.
- `artifacts/chatroulette.py` — **Chatroulette video chat parser** (AXIOM
  `ChatrouletteArtifact`): textový log i JSON; stejný vzor konzervativní JSON
  detekce; artifact type `chatroulette_message`.
- `artifacts/limewire_p2p.py` — **LimeWire/Limerunner/Luckywire P2P parser**
  (AXIOM `LimewireArtifact` + `LimerunnerArtifact` + `LuckywireArtifact`):
  shared files JSON i pipe-delimited text; detekce rodiny s prioritou
  Limerunner > Luckywire > LimeWire; artifact typy `limewire_shared_file` /
  `limerunner_shared_file` / `luckywire_shared_file`.
- Registrace: pipeline `NAME_BASED_EXTRACTORS` + `_name_based_match` (4 nových
  name-based extraktorů) a Kik do SQLite dispatch chainu; C3 Parser Validation
  Registry **+4 záznamy → 24 parserů** (`build_registry()` ověřeno).
- Coverage matrix: `scripts/build_axiom_coverage.py` COVERED +9 typů vlny 3 +
  `_covered_desc`; regenerace `STOPA_COVERAGE_MATRIX.csv` — covered **42 → 51**
  (+9 typů z 232), deterministická (SHA-256 diff ✓).

### Fixed
- Kik parser: closure `g()` v `parse_kik_users`/`parse_kik_messages` binduje
  `low` přes default argument (ruff B023); test fixture DB dostávají
  `row_factory = sqlite3.Row`.
- Bebo/Chatroulette/LimeWire: konzervativní JSON detekce — textový log začíná
  na `[ts] user said:` a narážel na `startswith("[")`; JSON se teď uznává jen
  při jasném signálu (objekt, uzavřené pole s `{}`/`""`, kompaktní pole v
  prvním řádku).

### Testy
- 75 nových testů napříč 5 novými soubory (`tests/test_{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`), plně offline syntetické fixture (in-memory SQLite + text/JSON).
- Full suite **1041 passed, 1 skipped**; ruff clean.

## [Unreleased] — 2026-11-03 (ETAPA B vlna 2)

### Added (ETAPA B vlna 2 — port AXIOM extraktorů, 7 nových parserů + 71 testů)
- `artifacts/google_search_history.py` — **Google Search History parser** (AXIOM
  `GoogleSearchHistoryArtifact`): My Activity / Takeout JSON (`searches[]`, epoch s),
  query/URL/device; artifact type `google_search`. Detekce name/content-based.
- `artifacts/google_location_history.py` — **Google Location History parser** (AXIOM
  `GoogleLocationHistoryArtifact` + cloud `CloudGoogleLocationHistoryArtifact`): Takeout JSON
  (`latitudeE7`/`longitudeE7`, epoch ms) i warrant return CSV (epoch s/ms, ISO fallback);
  artifact type `google_location`.
- `artifacts/google_login_history.py` — **Google Login/Sign-in History parser** (AXIOM
  `GoogleLoginHistoryArtifact`): sign-ins JSON (`signIns[]`) i CSV; device/IP/location/
  timestamp; artifact type `google_login`.
- `artifacts/google_account_info.py` — **Google Account Info parser** (AXIOM
  `GoogleAccountInfoArtifact`): `account_info.json` (e-mail, jméno, telefon, adresa);
  artifact type `google_account`.
- `artifacts/mem_scan.py` — **Memory scan text output parser** (AXIOM `CmdScanArtifact` +
  `FileScanArtifact`): Volatility-style textové výstupy — CmdScan (procesy: offset, PID,
  cmdline) a FileScan (souborové cesty v paměti); artifact typy `mem_process` / `mem_file`.
- `artifacts/ddg_current_tabs.py` — **DuckDuckGo Current Tabs parser** (AXIOM
  `CurrentTabsArtifact`): JSON (`tabs[]`) i textový export; dedupe URL, limit 500;
  artifact type `browser_tab`.
- `artifacts/msn_messenger.py` — **MSN/Windows Live Messenger chat log parser** (AXIOM
  `MSNArtifact`): textové chat logy (`Chat started on`, per-message řádky s odesílatelem);
  artifact type `msn_message`.
- Registrace: pipeline `NAME_BASED_EXTRACTORS` + `_name_based_match` (7 nových name-based
  detekcí) i C3 Parser Validation Registry (+7 záznamů, celkem **20 parserů**).
- Coverage matrix: covered **33 → 42** unikátních AXIOM typů (+9), deterministická.

## [Unreleased] — 2026-11-02 (ETAPA A–C)

### Added (ETAPA B vlna 1 — port AXIOM extraktorů, 6 nových parserů + 76 testů)
- `artifacts/email_mbox.py` — **mbox/EML email parser** (AXIOM `CloudMboxEmailArtifact` /
  `OfflineGmailArtifact`): rozdělení mbox na zprávy (`From ` řádky), hlavičky From/To/Cc/Bcc/
  Subject/Date, MIME body (text/plain + base64/QP decode), UTF-8/UTF-16 detekce; artifact type
  `email_message`. Detekce name/content-based (mbox nemá spolehlivou magiku).
- `artifacts/win_wlan.py` — **WiFi WLAN profile XML parser** (AXIOM `WiFiLocationsArtifact`):
  SSID (`<SSID><name>`), authentication/encryption, MAC adresy ze stationList; namespace-agnostické
  helpery `_local()`/`_find_text()` (XML má `xmlns`). Artifact type `wifi_profile`.
- `artifacts/win_schedtask.py` — **Scheduled Tasks XML parser** (AXIOM `ScheduledTasksArtifact`):
  název, akce (Exec), triggery; detekce UTF-16 LE/BE s BOM (reálné task XML jsou UTF-16).
  Artifact type `scheduled_task`.
- `artifacts/net_connections.py` — **netstat/connstat text parser** (AXIOM `ConnscanArtifact` /
  `NetScanArtifact` / `SockscanArtifact`): robustní token-based parser — Windows `netstat -ano`
  (uppercase, PID), Unix `ss`/`netstat` (State/Recv-Q/Send-Q sloupce), IPv4/IPv6 v hranatých
  závorkách, wildcard `*:*`. Artifact type `network_connection`.
- `artifacts/win_clipboard.py` — **Clipboard registry parser** (AXIOM `ClipboardArtifact`):
  sekundární průchod NTUSER.DAT (`Software\Microsoft\Windows\CurrentVersion\Clipboards\<fmt>`),
  CF_* formáty, UTF-8/UTF-16LE detekce hodnot. Artifact type `clipboard_entry`.
- `artifacts/win_sids.py` — **SID extraction parser** (AXIOM `GetsidsArtifact` / `SidsArtifact` /
  `UserSidsArtifact`): SAM/SECURITY `Sam\Domains\Account\Users\<SID>` + NTUSER.DAT ProfileList;
  zdroj rozlišen podle názvu souboru. Artifact type `user_sid`.
- `pipeline.py` — importy všech 6 parserů; `NAME_BASED_EXTRACTORS` rozšířen o email/wlan/
  schedtask/netstat; `_extract_registry_all` rozšířen o Clipboard + SID sekundární průchody
  (sdílená regf magic, pattern Amcache/ShimCache).
- `domain/validation_registry.py` — 4 nové C3 záznamy (`email_mbox`, `win_wlan`, `win_schedtask`,
  `net_connections`) + aktualizované limitations u `registry_hive`; `build_registry()` nyní
  **13 parserů** (1:1 sync s pipeline ověřen).
- Testy: `tests/test_email_mbox.py` (17), `test_win_wlan.py` (12), `test_win_schedtask.py` (11),
  `test_net_connections.py` (12), `test_win_clipboard.py` (12), `test_win_sids.py` (12) — celkem
  **76 nových testů**, plně offline (syntetické fixtures + fake regipy objekty). Plná sada:
  **895 passed, 1 skipped**; ruff clean.

### Added (FÁZE 1 — kompletní technický audit + FÁZE 15 coverage matrix CSV)
- `docs/STOPA_TECHNICAL_AUDIT.md` — přepsán na aktuální stav (commit `2244d95`,
  schema v11, **819 testů**, ruff clean): 18 oblastí × (současný stav / funguje /
  neúplné / dluh / rizika / doporučení / priorita), každé tvrzení podloženo
  zdrojovým kódem, testem nebo živým spuštěním. Souhrn priorit P0–P3.
- `scripts/build_axiom_coverage.py` — generátor matice rozšířen o export
  **`STOPA_COVERAGE_MATRIX.csv`** (FÁZE 15) do kořene projektu: 232 unikátních
  AXIOM typů × sloupce (artifact_type, platforma, zdroj_dat, parser_stopa,
  stav_implementace SUPPORTED/NOT_SUPPORTED/DEPRECATED, stav_testovani, verze,
  známá_omezeni, referencni_dataset, vysledek_validace). Deterministický výstup
  ověřen opakovaným spuštěním (shoda SHA-256).

### Added (P0 Intelligence I3 — Entity Resolution 2.0, confidence levels + normalizace účtů)
- `domain/entity_resolution.py` — nový doménový modul: čtyři úrovně confidence
  vztahů (`confirmed`, `strong_candidate`, `possible`, `unverified`) s
  `map_legacy_confidence()` (staré `verified`→`confirmed`, `inferred`→`possible`);
  normalizace platformních účtů — WhatsApp JID `+420…@c.us` → `wa:+E164`,
  skype:/telegram: handle; heuristická detekce duplicit entit
  `find_merge_candidates()` s důvody (stejný normalizovaný telefon, stejný
  e-mail local-part na různých doménách, shoda platformního účtu).
- `domain/entities.py` — nový druh entity **`user_account`**; `classify_value()`
  detekuje platformní účty (JID, skype:/telegram: handle) a vrací `user_account`.
- `domain/correlation.py` — `CONTACT_KINDS = ("phone", "email", "user_account")`;
  pravidla same_contact/hash_match → `confirmed`, temporal_overlap → `possible`;
  `CorrelationResult` rozšířen o časové rozmezí **`first_seen`/`last_seen`**;
  `run_correlation()` vrací `merge_candidates`.
- `data/db.py` — schéma **v10 → v11**: CHECK constraints pro `entities`
  (`user_account`) a `correlations` (4 confidence + `first_seen`/`last_seen`);
  idempotentní migrace `_migrate_entity_resolution()` (rebuild tabulek, protože
  SQLite nemění CHECK in-place; staré confidence hodnoty se remapují při kopii —
  bez ztráty dat); `add_correlation()`/`list_correlations()` rozšířeny o časové
  rozmezí.
- Web: nový endpoint **`GET /api/cases/{case_id}/entities/merge-candidates`**;
  audit log `correlation_run` rozšířen o počet duplicit/merge candidates.
- CLI: `stopa correlate` tiskne „Možné duplikity entit“ s důvody (max 10).
- Report/i18n: `_correlation_confidence_label()` podporuje 4 úrovně + passthrough
  neznámých hodnot; i18n rozšířen o nové confidence štítky.
- GUI graph (`graph.js`): barva `user_account`, EDGE_WIDTHS pro 4 úrovně +
  backward compat staré `verified`/`inferred`; plná hrana pro confirmed,
  přerušovaná pro ostatní.
- Testy: nový `tests/test_entity_resolution.py` (26 testů — confidence levels,
  normalizace JID/handle, merge candidates + determinismus, časové rozmezí,
  migrace v10→v11 bez ztráty dat, web endpoint); aktualizovány `test_e4/e5/e10/
  reproducibility` na novou škálu a schéma v11.

### Added (P0 Intelligence I2 — Forensic RAG, tři znalostní vrstvy)
- `intelligence/rag.py` — retrieval napříč třemi oddělenými vrstvami:
  **Case RAG** (artifacts/files/findings přes existující FTS5 indexy case DB,
  striktní izolace podle `case_id`), **Technical RAG** (`docs/formats/*.md` +
  Parser Validation Registry C3 — jeden chunk na parser) a **Knowledge RAG**
  (schválená metodika `docs/methodology/*.md`).
- Chunking markdown podle nadpisů s limitem délky; deterministický skórovací
  ranking (počet shodných slov + tie-break citace); FTS5 query sanitizace
  (každé slovo = citovaný term — žádná FTS5 syntaxe z uživatelského textu
  neunikne do dotazu; Unicode → české diakritiky).
- **Prompt injection ochrana:** importované dokumenty obalené do izolovaného
  bloku `<untrusted_source layer="…">` s instrukcí „data, ne příkazy“.
- **Audit AI dotazů:** `audit_ai_query()` → `analysis_operations`
  (op_type=`ai_query`) s verzí modelu, SHA-256 promptu a použitými citacemi.
- Napojení: orchestrátor (`build_prompt`/`orchestrate` přijímají `RagContext`),
  web endpoint `POST /api/cases/{id}/ai/analyze` (odpověď obsahuje počty RAG
  chunků) a CLI `stopa analyze` (JSON výstup s RAG metadata).

### Added (P0 Intelligence I1 — AI orchestrace, multi-agent)
- `intelligence/agents.py` — 5 deklarativních `AgentProfile` (case_analyst,
  timeline_analyst, artifact_analyst, media_analyst, report_analyst): system prompt,
  popis vstupů, Pydantic výstupní model (`CaseAnalystOutput`, `TimelineAnalystOutput`,
  `ArtifactAnalystOutput`, `MediaAnalystOutput`, `ReportAnalystOutput`), max_tokens/timeout;
  žádná autonomní smyčka — jeden LLM call na úkol
- `intelligence/case_context.py` — `CaseContext` (frozen read-only snapshot: stats,
  findings, timeline events, sample artifacts) + `build_case_context(db, case_id)`
  s limity velikosti pro prompt; čistá logika orchestrace DB nevidí
- `intelligence/ai_orchestrator.py` — `route_agent()` (explicitní volba > auto-routing
  podle klíčových slov), `build_prompt()`, `parse_output()` (**fail-closed**: JSON →
  Pydantic validace, zvládne markdown fence + proza kolem), `extract_citations()`
  ([art:<id>]/[file:<id>]), `AgentResult` (audit: prompt_chars, duration_ms, raw_text)
  a `orchestrate(llm_call, context, question)` — `llm_call` je injektovatelný callable,
  celá orchestrace se testuje offline bez LM Studio
- Web: nový endpoint **`POST /api/cases/{case_id}/ai/analyze`** (agent volitelný,
  audit záznam `ai_analyzed`, nevalidní výstup LLM → 502)
- CLI: nový subpříkaz **`stopa analyze <case> "dotaz" [--agent X] [--json]`**

### Added (P0 Core C6 — Benchmark Engine + validační reporty / E13)
- `domain/benchmark.py` — čistá logika bez I/O: `BenchmarkResult` (frozen dataclass:
  name, suite, duration_ms, ram_peak_bytes, artifacts, iterations), `RegressionWarning`,
  `detect_regressions()` (práh >20% zpomalení proti baseline, defenzivní u baseline=0),
  `validation_coverage()` (covered/total/pct + nepokrivené parsery), `env_info()`
- `data/benchmark_engine.py` — deterministické benchmarky na syntetických datech:
  core workload (pipeline ingest+extrakce stromu souborů) a per-parser workloads
  (9 parserů z registry, minimální vstup); měření času + špičkové RAM (tracemalloc);
  historie do `meta` (`benchmark_history`, max 50 záznamů), `check_regressions()`,
  `benchmark_report()`; každý workload obalen try/except (jeden selže, ostatní běží)
- `data/validation_report.py` — Evidence Validation Report per případ: per-artifact
  parser ID+verze + validation status + confidence + provenance; souhrn coverage
  (kolik artefaktů je z validovaných parserů); deterministický JSON export
- CLI: nové subpříkazy **`stopa benchmark [case] [--suite core|parsers|all]`**
  (výsledky + detekce regresí >20% proti baseline) a **`stopa validate <case> [--json]`**
  (validační report); audit záznam `benchmark_run`
- `tests/test_benchmark_engine.py` — 18 testů (čistá logika: detekce regresí/práh/coverage;
  engine: core+parser workloads, historie roundtrip, regresní detekce, report shape;
  validační report: provenance coverage, determinismus JSON, prázdný případ); suite 720 → **738 passed**

### Added (P0 Core C5 — Reproducibility Engine)
- `domain/reproducibility.py` — čistá logika bez I/O: `AnalysisOperation` (frozen dataclass:
  vstupní soubory + SHA-256, verze parserů, verze STOPA, config_hash, parametry, prostředí),
  `env_snapshot()` (python/platform/sqlite), deterministické `compare_outputs()` →
  `ComparisonReport`, `verify_inputs()` (změna/ztráta/přidání vstupního souboru)
- DB schéma **v9 → v10**: nová tabulka `analysis_operations` + idempotentní migrace sloupce
  `params_json`; metody `record_operation()` / `get_operation()` / `list_operations(case_id, op_type)`
- `pipeline.process_source()` nyní zaznamenává každou extrakci: vstupní soubory se SHA-256,
  verze parserů, config_hash profilu, parametry, deterministický souhrn výstupů
  (`summarize_outputs()` — jen stabilní počty, bez ID/časů) + `duration_ms`
- `pipeline.replay_extract(op, root)` — ověří hashe vstupů, spustí extrakci v dočasné DB
  (původní případ se nedotkne), porovná souhrny → `ReplayResult(inputs_identical, outputs_identical, diffs)`
- CLI: nový subpříkaz **`stopa replay <case_id> [op]`** — opakování zaznamenané operace +
  lidsky čitelný report (vstupy OK/ZMĚNĚNY, výstup IDENTICKÝ/LIŠÍ), audit záznam
  `operation_replayed`, exit code 0/1
- `tests/test_reproducibility.py` — 20 testů (čistá logika: porovnání/ověření vstupů/model/env;
  DB integrace: roundtrip/filtry/migrace v9→v10; pipeline: záznam operace, replay identický,
  detekce změněného i zmizelého souboru, determinismus souhrnu); suite 700 → **720 passed**

### Added (P0 Core C4 — Evidence Integrity 2.0)
- `domain/integrity.py` — čistá logika bez I/O: **hash chaining** audit logu
  (`compute_audit_hash`, `verify_chain` s detekcí rozbitého řetězce + ID prvního
  špatného řádku), **Ed25519** kontrolní body (lazy import `cryptography` — volitelná
  závislost, graceful degradation jako FDE: `generate_keypair`, `sign_hash`,
  `verify_signature`), **export manifesty** (`build_manifest` + deterministický
  `manifest_hash` — stejný vstup = stejný hash + Ed25519 podpis)
- DB schéma **v8 → v9**: audit_log +sloupce `prev_hash`/`hash`, nová tabulka
  `integrity_checkpoints`; idempotentní `_migrate_audit_chain()` (ALTER + backfill
  řetězce od GENESIS pro staré DB, triggery append-only dočasně zrušeny a obnoveny)
- `CaseDB.log_operation()` nyní chainuje; metody `ensure_integrity_key` /
  `add_integrity_checkpoint` / `verify_integrity_checkpoints`; odstraněna duplicitní
  stará `log_operation`
- CLI: nový subpříkaz **`stopa integrity <case>`** (ověření řetězce + klíč + kontrolní
  body, `--init-key`, `--checkpoint DŮVOD`); Ed25519 pár generován při `case new`;
  kontrolní body automaticky po ingest / correlate / export; `_write_export_manifest()`
  — podepsaný manifest vedle exportního souboru (reprodukovatelnost)
- `tests/test_integrity.py` — 22 testů (čistá logika: chain/tamper/Ed25519 roundtrip/
  manifest determinismus; DB integrace: chaining, backfill staré DB, kontrolní body,
  export manifest); suite 678 → **700 passed**

### Added (P0 Core C3 — Parser Validation Registry)
- `domain/validation_registry.py` — `ParserValidation` (parser_id, verze, formáty,
  omezení, referenční dataset, test files), deklarativní registry pro všech 9 parserů
  (sqlite, registry_hive, plist, lnk, win_prefetch, evtx, icloud_messages, win_jumplist,
  win_usn) s formáty a omezeními dle docstringů parserů
- `build_registry()` — synchronizace s pipeline (`parser_versions()`): každý extraktor má
  záznam v registry a naopak, verze se shodují; nesoulad → `RegistryError`; lazy import
  (domain bez tvrdé závislosti na pipeline)
- `registry_report()` — shrnutí registry pro CLI/GUI
- `tests/test_validation_registry.py` — 10 testů (sync s pipeline, verze, chybějící
  extraktor/záznam, version mismatch, frozen model, report); suite 668 → 678 passed

### Added (P0 Core C2 — Evidence Lineage Engine)
- `domain/lineage.py` — `LineageEvent` (append-only krok: verze nástroje, hash konfigurace,
  vstupní/výstupní reference), `config_hash()` (deterministický SHA-256 kanonické konfigurace),
  `build_chain()` (zpětné dohledání řetězce zdroj → … → ref); čistá logika bez I/O
- DB schéma **v8**: tabulka `lineage_events` + idempotentní migrace starých case DB
- `CaseDB`: log_lineage / list_lineage (chronologicky) / get_lineage_chain (chain traversal)
- Integrace do pipeline: krok `extract` (process_source, output_refs = ID artefaktů),
  `correlate` (run_correlation, artefakty → propojení), `finding_added` (add_finding,
  provenance refy → finding), `report_generated` (HTML/PDF report)
- `ProcessResult.extracted_artifact_ids` — output refs extrakčního kroku
- `tests/test_lineage.py` — 12 testů (model, CRUD, chain traversal, pipeline integrace, migrace v7→v8)

### Added (P0 Core C1 — Unified Evidence Model)
- `domain/evidence_model.py` — ConfidenceLevel (5 úrovní AI grounding), Provenance, Finding
  (povinná provenance = doložitelnost); čistá logika bez I/O
- `models.Artifact` +sloupce `provenance: list[Provenance]`, `validation_status`
  (staré artifacty čitelné s defaulty)
- DB schéma v7: tabulka `findings` (kind, confidence_level CHECK, provenance_json),
  sloupce `artifacts.provenance_json/validation_status`; idempotentní migrace starých DB
- `CaseDB`: add_finding / list_findings (filtry case/kind/confidence) / get_finding / delete_finding
- `tests/test_evidence_model.py` — 14 testů (modely, CRUD, CHECK constraint, migrace v6→v7, roundtrip)

### Added (dokumentace)
- `udelej.md` — master prompt STOPA Ultimate Forensic Platform (zadání)
- `docs/STOPA_TECHNICAL_AUDIT.md` — ETAPA A: kompletní technický audit (ověřená čísla,
  silné stránky, slabá místa S1–S11, návrhy architektonických změn)
- `docs/STOPA_GAP_ANALYSIS.md` — ETAPA B: gap analysis vs. zadání §4–§20
  (IMPLEMENTED/PARTIAL/MISSING/NEEDS VALIDATION/NOT RECOMMENDED + moduly/soubory)
- `docs/STOPA_TARGET_ARCHITECTURE.md` — ETAPA C: cílová architektura, datové modely
  (Unified Evidence Model, schéma v7), API kontrakty, závislosti, migrační strategie,
  technologické vyhodnocení (§20)
- `docs/STOPA_IMPLEMENTATION_ROADMAP.md` — ETAPA C: P0 Core (C1–C6), P0 Intelligence (I1–I5),
  P1 zdroje (S1–S6), P1 Multimedia (M1–M4), P2 enterprise/workspace (E1–E5) + odhady
- `docs/STOPA_VALIDATION_STRATEGY.md` — ETAPA C: Parser Validation Registry, referenční
  datasety, Benchmark Engine, regresní sada, validační reporty, kritéria validace parseru
- `docs/STOPA_SECURITY_MODEL.md` — ETAPA C: hrozby, Integrity 2.0 (hash chaining + Ed25519),
  AI bezpečnost, web API, důvěryhodnost vstupů, kontrolní seznam commitů
- `docs/STOPA_AI_ARCHITECTURE.md` — ETAPA C: multi-agent orchestrátor (5 agentů), Forensic RAG
  (Case/Technical/Knowledge vrstvy), AI grounding (5 úrovní), modelová vrstva

## [0.1.0] — 2026-11-02 (commit ae73ad0)

### Fixed (E-audit + code review)
- Path traversal case_id → `validate_case_id()` regex v open_db/delete_case
- rel_path traversal → resolve()+prefix check; RFC 5987 Content-Disposition + CRLF hardening
- RAM peak exportu → ranged read (seek+read) místo read_bytes()
- Mrtvý kód sqlite_formatter wrapper; redundantní datetime importy v db.py
- README test count; verze z jednoho zdroje (importlib.metadata)

### Added
- CI workflow od noly (ruff + pytest + JS DOM přes jsdom)
- `tests/test_audit_fixes.py` — 15 testů audit oprav
- Suite: **642 passed, 1 skipped**; ruff clean
