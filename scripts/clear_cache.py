import os
import sys
import logging
import redis

# Add project root to path
sys.path.insert(0, os.getcwd())

from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("clear_cache")

def clear_redis():
    logger.info("Connecting to Redis...")
    try:
        if settings.use_upstash:
            from upstash_redis import Redis
            r = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
            
            # Upstash redis client doesn't support flushdb directly, so scan and delete matching keys
            cursor = 0
            keys_to_delete = []
            while True:
                cursor, keys = r.scan(cursor, match="nyaya:*")
                keys_to_delete.extend(keys)
                if cursor == 0:
                    break
            
            if keys_to_delete:
                r.delete(*keys_to_delete)
                logger.info(f"✓ Deleted {len(keys_to_delete)} keys from Upstash Redis")
            else:
                logger.info("✓ No keys matching 'nyaya:*' found in Upstash Redis")
        else:
            r = redis.from_url(settings.redis_url, decode_responses=True)
            r.flushdb()
            logger.info("✓ Flushed local Redis database")
    except Exception as e:
        logger.error(f"Failed to clear Redis: {e}")

if __name__ == "__main__":
    clear_redis()
    logger.info("Cache clear complete!")
