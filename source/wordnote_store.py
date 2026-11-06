"""拾词的原有本地词库、轮换和发音逻辑。"""
from __future__ import annotations
from contextlib import closing
import copy
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import queue
import random
import shutil
import sqlite3
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
DEFAULT_SETTINGS = {"topmost": False, "dark": False, "mini": False, "voice": "", "position": None}


@lru_cache(maxsize=1)
def american_ipa_dictionary():
    dictionary = {}
    try:
        with (HERE / "ipa" / "en_US.txt").open(encoding="utf-8") as source:
            for line in source:
                word, separator, phonetic = line.rstrip().partition("\t")
                if separator and 0 < len(phonetic) <= 200:
                    dictionary[word.casefold()] = phonetic
    except (OSError, UnicodeError):
        logging.exception("Could not load the American IPA dictionary")
    return dictionary


def lookup_american_ipa(word):
    key = word.strip().casefold().replace("’", "'")
    return american_ipa_dictionary().get(key, "") if key else ""


@lru_cache(maxsize=512)
def lookup_chinese_meaning(word):
    key = word.strip().casefold().replace("’", "'")
    if not key:
        return ""
    path = HERE / "meaning" / "ecdict.sqlite"
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            result = database.execute("SELECT meaning FROM meanings WHERE word = ?", (key,)).fetchone()
    except sqlite3.Error:
        logging.exception("Could not query the English–Chinese dictionary")
        return ""
    return result[0] if result else ""


def fill_missing_details(entries):
    changed = False
    for entry in entries:
        for field, lookup in (("phonetic", lookup_american_ipa), ("meaning", lookup_chinese_meaning)):
            if not entry[field]:
                value = lookup(entry["word"])
                if value:
                    entry[field] = value
                    changed = True
    return changed


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "words.json"
        self.recovered = False

    @staticmethod
    def validate(raw):
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("words"), list):
            raise ValueError("不是有效的拾词备份，或文件版本不受支持。")
        if len(raw["words"]) > 20000:
            raise ValueError("最多支持 20000 个单词。")
        data = {"version": 1, "words": [], "settings": DEFAULT_SETTINGS.copy()}
        settings = raw.get("settings", {})
        if isinstance(settings, dict):
            for key in ("topmost", "dark", "mini"):
                if isinstance(settings.get(key), bool):
                    data["settings"][key] = settings[key]
            if isinstance(settings.get("voice"), str):
                data["settings"]["voice"] = settings["voice"]
            pos = settings.get("position")
            if isinstance(pos, list) and len(pos) == 2 and all(type(x) is int for x in pos):
                data["settings"]["position"] = pos
        names, ids = set(), set()
        for item in raw["words"]:
            if not isinstance(item, dict):
                raise ValueError("单词条目格式不正确。")
            e = {}
            for key, limit in (("word", 100), ("phonetic", 200), ("meaning", 2000)):
                value = item.get(key, "")
                if not isinstance(value, str) or len(value.strip()) > limit:
                    raise ValueError("单词、音标或释义格式不正确，或长度超限。")
                e[key] = value.strip()
            if not e["word"] or any(ord(c) < 32 for c in e["word"]):
                raise ValueError("单词不能为空，也不能包含换行等控制字符。")
            key = e["word"].casefold()
            if key in names:
                raise ValueError("文件中有重复单词：" + e["word"])
            names.add(key)
            eid = item.get("id")
            if not isinstance(eid, str) or not eid or eid in ids:
                eid = uuid.uuid4().hex
            ids.add(eid)
            e.update(id=eid, learned=item.get("learned") is True)
            data["words"].append(e)
        return data

    @staticmethod
    def read(path):
        path = Path(path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("文件过大，上限为 16 MB。")
        return Store.validate(json.loads(path.read_text(encoding="utf-8-sig")))

    @staticmethod
    def atomic_write(path, data):
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(Store.validate(data), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def load(self):
        if not self.path.exists():
            return {"version": 1, "words": [], "settings": DEFAULT_SETTINGS.copy()}
        try:
            return self.read(self.path)
        except (ValueError, OSError):
            backup = self.path.with_suffix(".json.bak")
            if not backup.exists():
                raise ValueError("无法读取本地单词本，原文件已保留：\n" + str(self.path))
            recovered = self.read(backup)
            shutil.copy2(self.path, self.directory / ("words.damaged-" + str(time.time_ns()) + ".json"))
            self.atomic_write(self.path, recovered)
            self.recovered = True
            return recovered

    def save(self, data):
        data = self.validate(data)
        if self.path.exists():
            previous = self.read(self.path)
            self.atomic_write(self.path.with_suffix(".json.bak"), previous)
        self.atomic_write(self.path, data)
        return data

    @staticmethod
    def merge(existing, incoming):
        incoming = Store.validate(incoming)
        merged = copy.deepcopy(existing)
        known = {e["word"].casefold() for e in merged["words"]}
        for entry in incoming["words"]:
            if entry["word"].casefold() not in known:
                known.add(entry["word"].casefold())
                e = dict(entry, id=uuid.uuid4().hex)
                merged["words"].append(e)
        return Store.validate(merged)


class Rotation:
    INTERVAL = 300
    BATCH_SIZE = 5

    def __init__(self, rng=None):
        self.remaining = self.INTERVAL
        self.rng = rng or random.Random()

    def reset(self):
        self.remaining = self.INTERVAL

    def advance(self, seconds, paused=False):
        if paused:
            return False
        self.remaining -= max(0, seconds)
        if self.remaining <= 0:
            self.reset()
            return True
        return False

    def pick(self, words, current=None):
        candidates = [e for e in words if e["id"] != current] or words
        return self.rng.choices(candidates, [1 if e["learned"] else 3 for e in candidates])[0] if candidates else None

    def pick_batch(self, words, previous=(), size=BATCH_SIZE):
        previous_ids = {entry["id"] for entry in previous}
        fresh = [entry for entry in words if entry["id"] not in previous_ids]
        recent = [entry for entry in words if entry["id"] in previous_ids]
        batch = []
        for pool in (fresh, recent):
            while pool and len(batch) < size:
                entry = self.pick(pool)
                batch.append(entry)
                pool.remove(entry)
        return batch


class Speech:
    """COM objects remain on their owning thread; repeated clicks replace queued audio."""
    def __init__(self):
        self.commands = queue.Queue()
        self.events = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def us_voices(voice):
        return [v for v in voice.GetVoices() if "409" in v.GetAttribute("Language").lower().split(";")]

    def _run(self):
        initialized = False
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            initialized = True
            engine = win32com.client.Dispatch("SAPI.SpVoice")
            tokens = self.us_voices(engine)
            if not tokens:
                raise RuntimeError("请在 Windows 语音设置中安装英语（美国）语音。")
            voices = {v.GetDescription(): v for v in tokens}
            default = next((name for name in voices if "Zira" in name), next(iter(voices)))
            self.events.put(("voices", (list(voices), default)))
            engine.Rate = -1
            while True:
                command = self.commands.get()
                if command is None:
                    engine.Speak("", 3)
                    break
                word, selected = command
                # Drain stale clicks, so long words never build up an audio queue.
                while not self.commands.empty():
                    later = self.commands.get_nowait()
                    if later is None:
                        engine.Speak("", 3)
                        return
                    word, selected = later
                try:
                    engine.Voice = voices.get(selected, voices[default])
                    engine.Speak(word, 3 | 16)  # async + purge + literal text (not SSML)
                    self.events.put(("spoken", word))
                except Exception as exc:
                    self.events.put(("error", str(exc)))
        except Exception as exc:
            self.events.put(("unavailable", str(exc)))
        finally:
            if initialized:
                pythoncom.CoUninitialize()

