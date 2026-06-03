import asyncio
import pytest

from honeypot.rate_limit import IpConcurrentLimiter, TooManyRequests


@pytest.mark.asyncio
async def test_block_on_exceed(fake_redis):
    held = []
    async def hold():
        async with IpConcurrentLimiter(fake_redis, "1.1.1.1", 3, True):
            held.append(1)
            await asyncio.sleep(0.2)

    t1 = asyncio.create_task(hold())
    t2 = asyncio.create_task(hold())
    t3 = asyncio.create_task(hold())
    await asyncio.sleep(0.05)
    with pytest.raises(TooManyRequests):
        async with IpConcurrentLimiter(fake_redis, "1.1.1.1", 3, True):
            pass
    await asyncio.gather(t1, t2, t3)


@pytest.mark.asyncio
async def test_wait_for_slot(fake_redis):
    async def hold(t):
        async with IpConcurrentLimiter(fake_redis, "2.2.2.2", 2, False,
                                       wait_timeout=5.0, poll_interval=0.05):
            await asyncio.sleep(t)

    tasks = [asyncio.create_task(hold(0.2)) for _ in range(2)]
    await asyncio.sleep(0.05)
    # 3rd should wait then succeed
    async with IpConcurrentLimiter(fake_redis, "2.2.2.2", 2, False,
                                   wait_timeout=5.0, poll_interval=0.05):
        pass
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_decr_on_exit(fake_redis):
    async with IpConcurrentLimiter(fake_redis, "3.3.3.3", 5, True):
        v = int(await fake_redis.get("ip:3.3.3.3:inflight") or 0)
        assert v == 1
    v2 = int(await fake_redis.get("ip:3.3.3.3:inflight") or 0)
    assert v2 == 0
