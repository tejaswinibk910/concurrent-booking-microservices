import redis
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def get_redis():
    return redis_client