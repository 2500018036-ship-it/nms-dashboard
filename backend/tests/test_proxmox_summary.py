import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from app.ai.agent import Agent
from app.ai.tool_registry import Registry,Tool
from app.ai.proxmox_summary import requested,summary

class ProxmoxSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_guest_list_uses_actual_units_without_model_arithmetic(self):
        value=dict(target='proxmox_resources',status='UP',timestamp='2026-10-24T06:00:00+00:00',guests=[dict(id='qemu/100',vmid=100,name='DNS',node='pve',type='qemu',status='running',cpu=.007,mem=512*1024**2,maxmem=1024**3,uptime=156600)])
        reg=Registry();handler=AsyncMock(return_value=value);reg.add(Tool('check_service','read',{'type':'object','properties':{'target':{'enum':['proxmox_resources']}},'required':['target']},handler))
        client=NS(complete=AsyncMock());answer=await Agent(client,reg).run('Sebutkan VM Proxmox yang berjalan')
        client.complete.assert_not_called();handler.assert_awaited_once()
        self.assertIn('1 hari 19 jam 30 menit',answer);self.assertIn('0.7%',answer);self.assertIn('512.0 MiB / 1024.0 MiB (50.0%)',answer)

    async def test_filter_running_missing_data_and_untrusted_names(self):
        value=dict(status='UP',guests=[dict(id='qemu/1',name='<script>untrusted</script>',status='running'),dict(id='qemu/2',status='stopped')])
        answer=summary('Tampilkan VM running',[dict(result=value)])
        self.assertNotIn('qemu/2',answer);self.assertIn('belum tersedia',answer);self.assertIn('<script>untrusted</script>',answer)
        self.assertFalse(requested('Kenapa VM yang ditampilkan mati?'))

    async def test_unknown_is_not_reported_as_no_guests(self):
        value=dict(target='proxmox_resources',status='UNKNOWN',error='authentication_failed')
        answer=summary('Daftar VM',[dict(result=value,arguments={})])
        self.assertIn('belum cukup',answer);self.assertNotIn('Ditampilkan: 0',answer)
