"""
Builds related.json: a static "up next" graph for Meow Music.

Run by GitHub Actions (see .github/workflows/crawl.yml). Each run:
  1. starts from seeds (YouTube Music charts + anything in seeds.txt)
  2. asks YouTube Music for the radio (up-next) list of songs it hasn't
     crawled yet, up to MAX_NEW songs per run
  3. merges the results into related.json, so coverage grows every run

related.json format (compact):
  {"v":1, "songs": {id: [title, artist, seconds]}, "rel": {id: [id, id, ...]}}

Run locally too:  pip install ytmusicapi && python crawl_related.py
"""
import json
import os
import sys
import time

from ytmusicapi import YTMusic

OUT = "related.json"
SEEDS = "seeds.txt"
MAX_NEW = int(os.environ.get("MAX_NEW") or 250)     # radios fetched per run
MAX_SONGS = int(os.environ.get("MAX_SONGS") or 6000)  # keeps the file small
PER_SONG = 20                                       # related songs kept per song
COUNTRIES = (os.environ.get("COUNTRIES") or "ZZ,US,IN,GB").split(",")
SLEEP = 0.6
MAX_FAILS_IN_A_ROW = 8


def secs(t):
    if t.get("length_seconds"):
        return int(t["length_seconds"])
    try:
        n = 0
        for p in str(t.get("length") or "").split(":"):
            n = n * 60 + int(p)
        return n
    except ValueError:
        return 0


def meta(t):
    artists = ", ".join(a["name"] for a in (t.get("artists") or []) if a.get("name"))
    return [t.get("title", ""), artists, secs(t)]


def is_id(s):
    return len(s) == 11 and all(c.isalnum() or c in "-_" for c in s)


def load():
    try:
        with open(OUT, encoding="utf-8") as f:
            db = json.load(f)
        if db.get("v") == 1:
            return db
    except (OSError, ValueError):
        pass
    return {"v": 1, "songs": {}, "rel": {}}


def save(db):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)


def add_seeds(ytm, db):
    songs = db["songs"]
    found = 0
    for c in COUNTRIES:                      # charts
        try:
            charts = ytm.get_charts(c.strip())
            items = (charts.get("videos") or {}).get("items") or charts.get("videos") or []
            for it in items if isinstance(items, list) else []:
                vid = it.get("videoId")
                if vid and vid not in songs and len(songs) < MAX_SONGS:
                    songs[vid] = meta(it)
                    found += 1
        except Exception as e:
            print("  chart %s skipped: %s" % (c, e))
    if os.path.exists(SEEDS):                # your own seeds: video ids or search text
        for line in open(SEEDS, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                if is_id(line):
                    if line not in songs:
                        songs[line] = ["", "", 0]
                        found += 1
                else:
                    for it in ytm.search(line, filter="songs", limit=5):
                        vid = it.get("videoId")
                        if vid and vid not in songs and len(songs) < MAX_SONGS:
                            songs[vid] = meta(it)
                            found += 1
            except Exception as e:
                print("  seed %r skipped: %s" % (line, e))
    return found


def main():
    ytm = YTMusic()
    db = load()
    songs, rel = db["songs"], db["rel"]
    print("Loaded %d songs, %d with related lists" % (len(songs), len(rel)))

    print("Added %d seed songs" % add_seeds(ytm, db))

    todo = [i for i in songs if i not in rel][:MAX_NEW]
    print("Crawling %d songs…" % len(todo))
    done = fails = row = 0
    for vid in todo:
        try:
            data = ytm.get_watch_playlist(videoId=vid, radio=True, limit=PER_SONG + 5)
            tracks = [t for t in data.get("tracks", []) if t.get("videoId") and t["videoId"] != vid]
            row = 0
        except Exception as e:
            fails += 1
            row += 1
            print("  %s failed: %s" % (vid, str(e)[:120]))
            if row >= MAX_FAILS_IN_A_ROW:
                print("\nToo many failures in a row: YouTube is probably refusing requests from here.")
                break
            time.sleep(SLEEP * 3)
            continue
        ids = []
        for t in tracks[:PER_SONG]:
            tid = t["videoId"]
            if tid not in songs:
                if len(songs) >= MAX_SONGS:
                    continue
                songs[tid] = meta(t)
            elif not songs[tid][0]:
                songs[tid] = meta(t)
            ids.append(tid)
        if not songs[vid][0] and data.get("tracks"):
            songs[vid] = meta(data["tracks"][0])  # first track is the seed itself
        rel[vid] = ids
        done += 1
        time.sleep(SLEEP)

    print("Crawled %d, failed %d. Now %d songs, %d with related lists." % (done, fails, len(songs), len(rel)))
    if done == 0:
        print("Nothing crawled, leaving %s unchanged." % OUT)
        sys.exit(1)
    save(db)
    print("Saved %s (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
