import json
import os
import glob
import time as _time
import threading
import logging
from collections import OrderedDict
from config import DATA_DIR

logger = logging.getLogger(__name__)

# ==========================================
# CACHE LAYER — Multi-tier caching
# L1: In-memory LRU (fastest)
# L2: JSON file (persistent)
# Optional L3: Redis (if available)
# ==========================================
L1_MAX_SIZE = 1000
L1_TTL = 5
L2_TTL = 60


class LRUCache:
    def __init__(self, max_size=L1_MAX_SIZE):
        self.cache = OrderedDict()
        self.max_size = max_size
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def set_value(self, key, value):
        with self._lock:
            self.cache[key] = value
            self.cache.move_to_end(key)
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def delete(self, key):
        with self._lock:
            if key in self.cache:
                del self.cache[key]

    def clear(self):
        with self._lock:
            self.cache.clear()

    def size(self):
        with self._lock:
            return len(self.cache)


class MultiTierCache:
    def __init__(self, max_size=L1_MAX_SIZE, file_path=None):
        self.l1 = LRUCache(max_size)
        self.file_path = file_path or os.path.join(DATA_DIR, "cache.json")
        self._lock = threading.Lock()
        self._timestamps = {}
        self.stats = {"l1_hits": 0, "l1_misses": 0, "l2_hits": 0, "writes": 0}
        self._load_l2()

    def _load_l2(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self.l1.set_value(k, v)
        except Exception:
            pass

    def _save_l2(self):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w") as f:
                json.dump(dict(self.l1.cache), f, default=str)
        except Exception:
            pass

    def get(self, key):
        with self._lock:
            # Try L1 first
            val = self.l1.get(key)
            if val is not None:
                self.stats["l1_hits"] += 1
                return val
            
            self.stats["l1_misses"] += 1
            
            # Try L2 (file)
            filepath = os.path.join(DATA_DIR, f"cache_{key.replace('/', '_').replace(':', '_')}.json")
            try:
                if os.path.exists(filepath):
                    with open(filepath, "r") as f:
                        val = json.load(f)
                    self.l1.set_value(key, val)
                    self.stats["l2_hits"] += 1
                    return val
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("L2 cache read failed for key %s: %s", key, e)
            
            return None

    def set_value(self, key, value):
        with self._lock:
            self.l1.set_value(key, value)
            self._timestamps[key] = _time.time()
            self._cleanup_stale_timestamps()
            filepath = os.path.join(DATA_DIR, f"cache_{key.replace('/', '_').replace(':', '_')}.json")
            try:
                with open(filepath, "w") as f:
                    json.dump(value, f, default=str)
                self.stats["writes"] += 1
            except (OSError, IOError, TypeError) as e:
                logger.debug("L2 cache write failed for key %s: %s", key, e)

    def _cleanup_stale_timestamps(self):
        if len(self._timestamps) > L1_MAX_SIZE * 2:
            now = _time.time()
            stale = [k for k, v in self._timestamps.items() if now - v > L2_TTL]
            for k in stale:
                del self._timestamps[k]

    def invalidate(self, key):
        self.l1.delete(key)
        self._timestamps.pop(key, None)
        filepath = os.path.join(DATA_DIR, f"cache_{key.replace('/', '_').replace(':', '_')}.json")
        if os.path.exists(filepath):
            os.remove(filepath)

    def clear_all(self):
        self.l1.clear()
        self._timestamps.clear()
        for f in glob.glob(os.path.join(DATA_DIR, "cache_*.json")):
            try:
                os.remove(f)
            except OSError:
                pass

    def get_stats(self):
        total = self.stats["l1_hits"] + self.stats["l1_misses"]
        hit_rate = self.stats["l1_hits"] / max(total, 1) * 100
        return {
            "l1_size": self.l1.size(),
            "l1_hit_rate": round(hit_rate, 1),
            "l1_hits": self.stats["l1_hits"],
            "l2_hits": self.stats["l2_hits"],
            "writes": self.stats["writes"],
        }


class RedisCache:
    def __init__(self, host="localhost", port=6379, db=0):
        self.available = False
        try:
            import redis
            self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self.client.ping()
            self.available = True
        except (ImportError, ConnectionError, Exception) as e:
            logger.debug("Redis connection failed: %s", e)
            self.client = None

    def get(self, key):
        if not self.available:
            return None
        try:
            val = self.client.get(key)
            if val:
                return json.loads(val)
        except (json.JSONDecodeError, ConnectionError, Exception) as e:
            logger.debug("Redis get failed for key %s: %s", key, e)
        return None

    def set_value(self, key, value, ttl=60):
        if not self.available:
            return
        try:
            self.client.setex(key, ttl, json.dumps(value, default=str))
        except (ConnectionError, Exception) as e:
            logger.debug("Redis set failed for key %s: %s", key, e)

    def delete(self, key):
        if self.available:
            try:
                self.client.delete(key)
            except (ConnectionError, Exception) as e:
                logger.debug("Redis delete failed for key %s: %s", key, e)


_cache = None
_cache_lock = threading.Lock()


def get_cache():
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = MultiTierCache()
    return _cache
