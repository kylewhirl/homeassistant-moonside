# Moonside for Home Assistant

This custom integration mirrors the Homebridge plugin that already lives in this repo: it logs into the official Moonside Firebase backend, keeps a realtime SSE connection open for instant state updates, and exposes the same theme trigger concept as stateless Home Assistant buttons.

## Highlights

- **Native lights** – Every Moonside lamp from `/userDevices/<localId>` is surfaced as a Home Assistant light entity with power, brightness, and HS color support. Commands reuse the same `LEDOFF`, `BRIGH##`, and `COLORRRRGGGBBB` payloads used in the Homebridge plugin and captured in `api.md`.
- **Realtime sync** – A background task streams Firebase RTDB events (`event: put/patch`) so automations react immediately just like the Homebridge bridge. The integration falls back to optional polling if you enable it in the config flow.
- **Theme buttons** – Provide theme names once (comma or newline separated) and the integration will look them up via Firestore (`app-lighting-effects`). Each lamp gets a `button` entity per theme; pressing it emits the corresponding `THEME.<code>.<params>` string and resets automatically.

## Installation

[![Open your Home Assistant instance and start adding an integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=moonside)

### HACS (recommended)

1. Make sure [HACS](https://hacs.xyz) is installed in your Home Assistant.
2. In HACS, add this repository (`https://github.com/kylewhirl/homeassistant-moonside`) as a custom integration (until it is accepted into the default store).
3. Install **Moonside** from HACS and restart Home Assistant.
4. Use the button above or go to **Settings → Devices & Services → Add Integration** and search for “Moonside”.

### Manual

1. Download or clone this repository.
2. Copy `custom_components/moonside` into your Home Assistant `custom_components` folder.
3. Restart Home Assistant, then add the integration from **Settings → Devices & Services**.

## Implementation notes

- Auth, token refresh, device snapshots, and SSE decoding all follow the reference Homebridge implementation (`src/moonsideApi.ts`).
- The integration sticks to Home Assistant's best practices from the latest developer docs: config flows, `DataUpdateCoordinator`, per-platform entity modules, translation files, and manifest metadata.
- State updates from the stream are merged exactly like the Homebridge accessory logic, including interpreting `controlData` to keep Home Assistant's light characteristics aligned with Firebase.
- Theme resolution uses the documented Firestore query (`app-lighting-effects`) from `api.md` and caches the selected presets per config entry.

With this in place, you can keep the Homebridge plugin running while testing the Home Assistant port side-by-side. Both talk to the same backend without interfering thanks to Firebase's multi-client semantics.
