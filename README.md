# YTK SHORTS (YouTube Shorts + Instagram Reels + TikTok)

Choose a video, describe it in one sentence, and the app generates a title, description and hashtags **in English, for a US audience**. The AI also looks at a few frames of the video, so it does not invent details that do not appear in it.
Then it posts right away or at the **US peak time**.

## How to use
1. Install Python 3.10+ (python.org), checking "Add Python to PATH".
2. Double-click `iniciar.bat` (it installs what is needed and opens the app). The first run takes a little while.
3. Click **Settings** and fill in what you will use (see below). This is only needed once.
4. Choose the video, write what it is about (any language works) and click **Generate text**.
5. Review the text, select the platforms and click **Post now**.
6. To get a .exe program: double-click `criar_exe.bat` (this step is untested; if it fails, use `iniciar.bat`).

## Multiple accounts
At the top of the window, the **Account** menu switches the account in use. **＋ Add account...** creates another one.
Each account has its own Instagram (ID and token), TikTok (login) and YouTube (login). The Gemini key and the app keys are shared.
- **YouTube:** on the first post of a new account, the browser opens; sign in to the Google account you want to use.
- **TikTok:** click Connect to TikTok and authorize with that account. While the app is in Sandbox, add the account as a Target User in the TikTok developer portal.
- **Instagram:** generate a token (and assign the Page) for that account, as you did for the first one.
- You cannot switch accounts while a post is in progress or scheduled.

## Compression and fixed hashtag
- **Compress if over the platform limit** (on by default): the app only re-encodes if the video is over 200 MB (YouTube and TikTok) or 250 MB (Instagram). It then uses two passes to get close to the limit with the best possible quality, without going over 1080 pixels wide. If the video already fits, the original is uploaded, with no quality loss. The limits are in `compactar.py` (`LIMITES_MB`).
- **Fixed hashtag** `#00874`: added at the end of the hashtags of every post. You can change or delete it in Settings > AI.

## Post at peak US time
Turn on **"Post at peak US time"**. The app shows, for each platform, the next peak time
(in New York time and in your time) and the button becomes **Schedule for peak time**.

- Each platform posts at its own best time, so they may be on different days.
- **The app must stay open and the computer on** until then. On Windows the app prevents the computer from
  sleeping while it waits.
- You can cancel at any time (the button becomes "Cancel schedule").
- The video is uploaded only at the scheduled time, not before.

### Where the times come from (New York time)
They are a starting point, not a rule: the studies do not fully agree, so I used the points they have in common
(Buffer 2026, with 52 million posts; Sprout Social 2026; ClipSpeed and MoonB).

| Platform | Times |
|---|---|
| YouTube Shorts | Mon 6 PM, Wed 6 PM, Thu 6 PM, Fri 4 PM, Sat 5 PM, Sun 3 PM |
| Instagram Reels | Mon 5 PM, Tue 6 PM, Wed 9 AM and 6 PM, Thu 9 AM and 6 PM, Sat 11 AM, Sun 12 PM |
| TikTok | Mon 1 PM, Tue 7 PM, Thu 7 PM, Fri 7 PM, Sat 9 AM and 8 PM, Sun 9 AM |

After a few weeks, compare them with your account's own statistics. To change the times, edit the
`PICOS` table in `agenda.py`.

## What each platform requires (manual step, one time only)

### Gemini (English text) – free
Get a key at aistudio.google.com > Get API key. Paste it in Settings > AI.

### YouTube Shorts
- console.cloud.google.com > create a project > enable "YouTube Data API v3".
- OAuth consent screen: type External, add your email as a test user.
- Credentials > OAuth client ID > "Desktop app" > download the JSON.
- In Settings > YouTube, choose that file. On the first post the browser opens for authorization.
- Until Google verifies the project, videos are uploaded as private.
- It becomes a Short if it is vertical (9:16) and up to 3 minutes long.

### Instagram Reels (testing)
- A professional account, a Meta app and a system user token that never expires.
- The app converts the video to Reels format before uploading.
- In some cases Meta returns error 2207085 ("Fatal") when publishing. If that happens, try YouTube.

### TikTok
- developers.tiktok.com > create an app > "Content Posting API" (Direct Post).
- Paste the client key and client secret in Settings > TikTok and click **Connect to TikTok** (the tokens are filled in automatically). If the default browser is signed in to another account, use **Copy link** and paste it into the right browser. **Disconnect from TikTok** revokes access.
- The video cover is chosen by the AI (Gemini looks at 8 frames).
- Until the app is audited by TikTok, you can only post with SELF_ONLY privacy (only you can see it).

## Security
- `config.json` stores your keys in plain text, on your PC. Do not send that file to anyone.
- Never paste keys in chats or screenshots. If one leaks, delete it and generate another.
