# The poster on your Mac

The poster publishes your scheduled CBC posts from **your own Google Chrome on your
own internet connection**, with accounts you log into yourself. Platforms trust a
home connection far more than a server's, so logins and "is this you?" checks are
rarer than on the server poster.

It never solves a CAPTCHA or hides that it is automated. When a platform asks for a
check, it stops, leaves the page open, and waits for you to finish it.

## Install

You need Google Chrome in `/Applications`, Python 3.10 or newer (`brew install python@3.12`),
and a CBC API key that belongs to a video maker (Settings → API keys). Don't paste the
key in chat or commit it.

```bash
cd ~/Projects/cbc-api && git pull
bash poster/mac/install.sh
```

The installer asks for the CBC address (default `https://cbc.gidraf.dev`) and the key.
The key isn't shown while you paste it, and it's saved in `~/.cbc/poster/.env` (mode 600).
It also checks that the key works, then starts the poster as a login item.

## Use

1. Open the console at **Play → Auto-post**. It shows *On &lt;your Mac&gt;* once the poster has checked in.
2. For each platform, press **Log in**. A Chrome window opens on your Mac; log in there yourself.
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
