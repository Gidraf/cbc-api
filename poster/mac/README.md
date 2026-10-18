# The poster on your Mac

The poster publishes your scheduled CBC posts from **your own Google Chrome on your
own internet connection**, with accounts you log into yourself. Platforms trust a
home connection far more than a server's, so logins and "is this you?" checks are
rarer than on the server poster.

It never solves a CAPTCHA or hides that it is automated. When a platform asks for a
check, it stops, leaves the page open, and waits for you to finish it.

## Install or update, with one line

Paste in the Mac's Terminal. The same line installs on a new Mac and updates one that has it
(the key already saved is reused); run it again after each update. The console shows these under
Play → Auto-post → Set up the poster on another Mac.

The poster:

```bash
cd ~ && { [ -d cbc-api ] || git clone https://github.com/Gidraf/cbc-api.git; } && cd cbc-api && git checkout main && git pull && bash poster/mac/install.sh
```

The poster and the render helper together:

```bash
cd ~ && { [ -d cbc-api ] || git clone https://github.com/Gidraf/cbc-api.git; } && cd cbc-api && git checkout main && git pull && bash poster/mac/install.sh && bash poster/mac/install-render.sh
```

## Install

You need Google Chrome in `/Applications`, Python 3.10 or newer (`brew install python@3.12`),
and a CBC API key that belongs to a video maker (Settings → API keys). Don't paste the
key in chat or commit it.

```bash
cd ~/Projects/cbc-api && git pull
bash poster/mac/install.sh
```

The installer asks for the CBC address (default `https://cbc.gidraf.dev`). It then reuses a
key already saved on this Mac, if the API accepts it. It looks in `CBC_API_KEY` in your
environment, then `POSTER_API_KEY` or `CBC_API_KEY` in the repo's `.env`, then the agent
runners' `~/.cbc/*/.env`. It only asks you to paste a key when none of those work.
The key isn't shown while you paste it, and it's saved in `~/.cbc/poster/.env` (mode 600).
It also checks that the key works, then starts the poster as a login item.

## Render videos on a Mac

A Mac draws videos for the server in about two minutes each. On any Mac with Google Chrome,
paste this in Terminal — it gets the code and installs everything else (Homebrew, ffmpeg,
Cairo, Pango, and LaTeX for Manim), asking for the Mac's password once:

```bash
cd ~ && { [ -d cbc-api ] || git clone https://github.com/Gidraf/cbc-api.git; } && cd cbc-api && git checkout main && git pull && bash poster/mac/install-render.sh
```

On a Mac without the poster it asks for the server's address and an API key. Run the same line
again to update. Logs: `tail -f ~/.cbc/render/render.log`. The console shows this under
Play → Auto-post → 🎬 Render videos on a Mac.

## Use

1. Open the console at **Play → Auto-post**. It shows *On &lt;your Mac&gt;* once the poster has checked in.
2. For each platform, press **Log in**. A Chrome window opens on your Mac; log in there yourself.
   If a site keeps asking for codes or won't let you in (that window says it is controlled
   by automated test software), run `bash poster/mac/login.sh` instead. It opens the same
   profile in ordinary Chrome. Log in, quit Chrome (Cmd+Q), and the poster starts again.
3. Press **Check**, then **Dry run** on one platform. A dry run does every step except the
   final Post and sends back a screenshot.
4. Turn on **Settings → Auto-post**. The server still enforces the limits: at most 30 posts a
   day across all channels, spaced out, and only within posting hours.

The poster keeps the Mac from going to sleep while it's idle. It can't post while the lid
is closed or the Mac is asleep. Any post it misses goes out on the next tick.

The poster's Chrome has its own profile in `~/.cbc/poster/profile`, so your everyday
Chrome isn't touched. If you close its window, it opens again the next time it's needed.

## Manage

```bash
tail -f ~/.cbc/poster/poster.log                                        # what it is doing
launchctl bootout gui/$(id -u)/com.cbc.poster                           # stop
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cbc.poster.plist   # start
bash poster/mac/install.sh                                              # update after git pull
bash poster/mac/install.sh --reconfigure                                # new address or key
bash poster/mac/uninstall.sh            # remove; keeps your logins
bash poster/mac/uninstall.sh --all      # remove everything, logins too
```

While the Mac poster is checking in, the console sends commands to it. When it isn't,
the console falls back to the server poster, if one is running.
