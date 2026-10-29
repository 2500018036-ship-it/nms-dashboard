from pathlib import Path
import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock
from theaz_access.broker import Broker


class BrokerCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.broker=Broker({},self.tmp.name,'image','/unused','/unused')
        self.identity='a'*32
        self.directory=Path(self.tmp.name)/self.identity
        self.directory.mkdir()
        (self.directory/'profile').mkdir()
        self.broker.workers[self.identity]={'id':self.identity}

    async def asyncTearDown(self):self.tmp.cleanup()

    async def test_timed_out_removal_releases_capacity_when_daemon_already_removed_container(self):
        self.broker.docker=AsyncMock(side_effect=[TimeoutError(), ''])
        await self.broker.stop(self.identity)
        self.assertNotIn(self.identity,self.broker.workers)
        self.assertFalse(self.directory.exists())
        args=self.broker.docker.call_args_list[1].args
        self.assertIn('name=^/theaz-access-'+self.identity+'$',args)
        self.assertIn('label=theaz.access.managed=true',args)
        await self.broker.stop(self.identity)
        self.assertEqual(self.broker.docker.await_count,2)

    async def test_existing_worker_and_profile_are_retained_until_removal_is_confirmed(self):
        self.broker.docker=AsyncMock(side_effect=[RuntimeError('remove_failed'),'container-id'])
        with self.assertRaises(RuntimeError):await self.broker.stop(self.identity)
        self.assertIn(self.identity,self.broker.workers)
        self.assertTrue(self.directory.exists())
        self.broker.docker=AsyncMock(return_value='')
        await self.broker.stop(self.identity)
        self.assertNotIn(self.identity,self.broker.workers)

    async def test_daemon_unavailable_cannot_falsely_free_capacity(self):
        self.broker.docker=AsyncMock(side_effect=RuntimeError('daemon_unavailable'))
        with self.assertRaises(RuntimeError):await self.broker.stop(self.identity)
        self.assertIn(self.identity,self.broker.workers)
        self.assertTrue(self.directory.exists())

    async def test_concurrent_stop_and_lease_cleanup_are_idempotent(self):
        arrived=0;gate=asyncio.Event()
        async def remove(*_):
            nonlocal arrived
            arrived+=1
            if arrived==2:gate.set()
            await gate.wait()
            return ''
        self.broker.docker=AsyncMock(side_effect=remove)
        await asyncio.gather(self.broker.stop(self.identity),self.broker.stop(self.identity))
        self.assertNotIn(self.identity,self.broker.workers)
        self.assertFalse(self.directory.exists())
