"""Plex -> Discord Rich Presence.

Polls Plex server(s) for sessions belonging to your account and mirrors the
currently playing item to Discord via local RPC (Discord desktop must be running).

Config: config.json next to this file (see config.example.json).
"""
import json
import sys
import time
from pathlib import Path

import requests
from pypresence import Presence
from pypresence.exceptions import DiscordNotFound, InvalidID, PipeClosed

try:
    from pypresence import ActivityType  # pypresence >= 4.4
except ImportError:
    ActivityType = None

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

TOKEN = CFG["plex_token"]
CLIENT_ID = str(CFG["discord_client_id"])
POLL = int(CFG.get("poll_seconds", 10))
SERVER_URLS = CFG.get("plex_urls") or []  # optional manual override
LARGE_IMAGE = CFG.get("large_image", "plex")  # asset key uploaded to Discord app, or https URL
SHOW_PAUSED = CFG.get("show_paused", True)
# Plex user names whose sessions to show. Empty = the account that owns plex_token.
PLEX_USERS = {u.lower() for u in CFG.get("plex_users") or []}

HEADERS = {
    "X-Plex-Token": TOKEN,
    "X-Plex-Client-Identifier": "plex-discord-rpc",
    "X-Plex-Product": "Plex Discord RPC",
    "Accept": "application/json",
}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def plex_account():
    r = requests.get("https://plex.tv/api/v2/user", headers=HEADERS, timeout=10)
    r.raise_for_status()
    u = r.json()
    return {u.get("username", "").lower(), u.get("title", "").lower()} - {""}


def discover_servers():
    """Return list of (name, [connection uris], access_token) for servers you own or share."""
    r = requests.get(
        "https://plex.tv/api/v2/resources",
        params={"includeHttps": 1, "includeRelay": 1},
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    out = []
    for res in r.json():
        if "server" not in res.get("provides", ""):
            continue
        conns = sorted(res.get("connections", []), key=lambda c: (c.get("relay", False), not c.get("local", False)))
        out.append((res["name"], [c["uri"] for c in conns], res.get("accessToken") or TOKEN))
    return out


class Server:
    def __init__(self, name, uris, token):
        self.name, self.uris, self.token, self.good = name, uris, token, None

    def sessions(self):
        candidates = [self.good] + [u for u in self.uris if u != self.good] if self.good else self.uris
        for uri in candidates:
            try:
                r = requests.get(
                    f"{uri.rstrip('/')}/status/sessions",
                    headers={**HEADERS, "X-Plex-Token": self.token},
                    timeout=5,
                )
                r.raise_for_status()
                self.good = uri
                return r.json().get("MediaContainer", {}).get("Metadata", []) or []
            except requests.RequestException:
                continue
        self.good = None
        return []


def build_servers():
    if SERVER_URLS:
        return [Server(u, [u], TOKEN) for u in SERVER_URLS]
    servers = [Server(*s) for s in discover_servers()]
    log("Servers:", ", ".join(s.name for s in servers) or "none")
    return servers


def my_session(servers, me):
    best = None
    for s in servers:
        for m in s.sessions():
            user = (m.get("User") or {}).get("title", "").lower()
            if user not in me:
                continue
            state = (m.get("Player") or {}).get("state")
            if state == "playing":
                return m
            best = best or m
    return best


def to_activity(m):
    kind = m.get("type")
    state = (m.get("Player") or {}).get("state", "playing")
    dur = int(m.get("duration") or 0) // 1000
    pos = int(m.get("viewOffset") or 0) // 1000

    if kind == "episode":
        details = m.get("grandparentTitle", "TV Show")
        se = f"S{int(m.get('parentIndex', 0)):02d}E{int(m.get('index', 0)):02d}"
        line = f"{se} · {m.get('title', '')}"
        atype = "WATCHING"
    elif kind == "movie":
        details = m.get("title", "Movie")
        line = str(m.get("year", "")) or "Movie"
        atype = "WATCHING"
    elif kind == "track":
        details = m.get("title", "Track")
        line = f"by {m.get('originalTitle') or m.get('grandparentTitle', '')}"
        atype = "LISTENING"
    else:
        details = m.get("title", "Plex")
        line = kind or ""
        atype = "WATCHING"

    act = {
        "details": details[:128],
        "state": (line or " ")[:128],
        "large_image": LARGE_IMAGE,
        "large_text": (m.get("parentTitle") or m.get("librarySectionTitle") or "Plex")[:128],
    }
    if state == "playing" and dur:
        now = int(time.time())
        act["start"] = now - pos
        act["end"] = now - pos + dur
    else:
        act["small_text"] = "Paused"
    if ActivityType is not None:
        act["activity_type"] = getattr(ActivityType, atype)
    key = (m.get("ratingKey"), state)
    return act, key, state


def connect_rpc():
    while True:
        try:
            rpc = Presence(CLIENT_ID)
            rpc.connect()
            log("Connected to Discord")
            return rpc
        except (DiscordNotFound, ConnectionRefusedError, FileNotFoundError, InvalidID) as e:
            log("Discord not available, retry in 30s:", e.__class__.__name__)
            time.sleep(30)


def main():
    me = PLEX_USERS or plex_account()
    log("Showing sessions for:", ", ".join(sorted(me)))
    servers = build_servers()
    rpc = connect_rpc()
    last_key, last_start, cleared = None, None, True
    rediscover = time.time() + 3600

    while True:
        try:
            if not SERVER_URLS and time.time() > rediscover:
                servers, rediscover = build_servers(), time.time() + 3600
            m = my_session(servers, me)
            if m:
                act, key, state = to_activity(m)
                if state == "paused" and not SHOW_PAUSED:
                    m = None
                else:
                    # Update on item/state change, or if position jumped (seek) > 5s
                    start = act.get("start")
                    seek = start and last_start and abs(start - last_start) > 5
                    if key != last_key or seek:
                        rpc.update(**act)
                        log("Now:", act["details"], "|", act["state"], f"({state})")
                        last_key, last_start, cleared = key, start, False
            if not m and not cleared:
                rpc.clear()
                log("Cleared")
                last_key, last_start, cleared = None, None, True
        except (PipeClosed, BrokenPipeError, ConnectionResetError, InvalidID):
            log("Discord connection lost, reconnecting")
            rpc = connect_rpc()
            last_key, cleared = None, True
        except requests.RequestException as e:
            log("Plex error:", e)
        time.sleep(POLL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
