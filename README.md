# MakerWorld Home Assistant Integration

Custom Home Assistant integration that pulls MakerWorld profile stats and per-model highlights and exposes them as entities under a single device.

## Features

- Profile summary stats (likes, downloads, prints, points, followers, boosts).
- Top model highlights (most liked/downloaded/printed) with model title as state and count as an attribute.
- Diagnostic sensors: Badges (state shows badge titles with verified/commercial licence as attributes) and Last Update timestamp.
- Manual refresh button.
- Binary sensors: Verified and Commercial Licence flags.
- Diagnostic binary sensors for banned permissions (comment, community, design notify, private msg, redeem, upload, whole).
- Optional limit for number of models scanned.

## Installation (HACS)

1. Add this repository as a custom repository in HACS (Integration).
2. Install the integration from HACS.
3. Restart Home Assistant.
4. Add the MakerWorld integration from Settings -> Devices & services.

## Configuration

The config flow will prompt for:

- Username (without @)
- Cookie (full Cookie header value from your browser)
- User agent (optional)

Options:

- Max models to scan (0 = all)
- Cookie (use this to update an expired cookie)

## Getting the cookie

1. Log in to MakerWorld in your browser.
2. Open Developer Tools (F12).
3. Go to the Network tab and refresh the page.
4. Click any request to `makerworld.com`.
5. In the request headers, copy the full `Cookie` header value (everything after `Cookie:`).
6. Paste it into the integration setup or options.

## Notes

This integration scrapes MakerWorld pages and requires a valid session cookie. MakerWorld may change its site structure, which can break parsing.

**Warning:** MakerWorld includes ban/permission fields in their user data, which suggests they may monitor for "unapproved" access methods. While this integration uses standard web requests with your session cookie, there is no guarantee that using it won't result in account restrictions or bans. Use at your own risk.
