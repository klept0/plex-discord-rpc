# plex-discord-rpc

Shows what you are playing on Plex as your Discord Rich Presence. TV episodes and movies show as "Watching", music as "Listening", with a progress bar that follows seeks and pauses.

The Discord desktop app must be running on the same machine.

## Setup

1. Create an application at https://discord.com/developers/applications. Its name is what Discord shows (for example "Plex"). Copy the Application ID.
2. Optional: under Rich Presence > Art Assets, upload a logo with the key `plex`.
3. Get your Plex token: in Plex Web, open any item, choose Get Info, then View XML, and copy the `X-Plex-Token` value from the URL.
4. Copy `config.example.json` to `config.json` and fill it in.
5. Install and run:

   ```
   pip install -r requirements.txt
   python plex_rpc.py
   ```

## Config

| Key | Meaning |
| --- | --- |
| `plex_token` | Your Plex token. |
| `discord_client_id` | Discord application ID. |
| `plex_users` | Plex user names whose sessions to show. Empty means the account that owns the token. Set this if you watch under a managed or different user. |
| `poll_seconds` | How often to check Plex. |
| `show_paused` | Keep the presence while paused. |
| `large_image` | Asset key in your Discord app, or an https image URL. |
| `plex_urls` | Server URLs to poll. Empty means discover your servers through plex.tv. |

## Notes

- Only a server's admin can see its sessions. Shared servers you do not own return 403 and are skipped.
- Cover art is not shown, because Plex image URLs contain your token and Discord fetches images through its own servers.
