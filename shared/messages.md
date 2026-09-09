# Extension IPC catalog

All `chrome.runtime.sendMessage` payloads have a `type` string. Unknown types are ignored.

## DetectedItem

```json
{
  "ratingKey": "65547",
  "machineIdentifier": "…",
  "pmsBaseUrl": "https://192-168-1-50.abc.plex.direct:32400",
  "plexToken": "<session token>",
  "titleHint": "Aladdin",
  "mediaId": null,
  "partId": null,
  "offsetMs": null
}
```

v1 leaves `mediaId` / `partId` / `offsetMs` null. The helper uses `Media[0]`, all parts, and metadata `viewOffset`.

| type | From → To | Notes |
| --- | --- | --- |
| `plexvlc.detect` | popup/background → content | `{}` |
| `plexvlc.detectResult` | content → requester | `{ item, error? }` |
| `plexvlc.launch` | content/popup/background → background | `{ item }` |
| `plexvlc.launchResult` | background → requester | `{ ok, mode?, title?, pathHint?, message, error? }` |
| `plexvlc.health` | popup/options → background | |
| `plexvlc.healthResult` | background → requester | |
| `plexvlc.pair` | options → background | `{ code }` |
| `plexvlc.pairResult` | background → options | |
| `plexvlc.registerLan` | options/popup → background | `{ origin }` — SW only `registerContentScripts` |

Helper URL is always `http://127.0.0.1:${helperPort}` — never `localhost`.
