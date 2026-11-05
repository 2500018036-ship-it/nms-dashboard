import unittest
from unittest.mock import AsyncMock,patch
from app.monitoring.inventory import collect

class ReachabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_reply_does_not_claim_snmp_integration_or_invent_resources(self):
        item={'id':'inv_test','name':'Switch Cisco','host':'192.168.10.26','monitor_method':'snmp','monitor_port':161,'monitor_categories':['interfaces']}
        with patch('app.monitoring.inventory.snmp.probe',new=AsyncMock(return_value={'status':'UNKNOWN','error':'timeout'})),patch('app.monitoring.inventory.icmp.probe',new=AsyncMock(return_value={'status':'UP','latency_ms':1})):
            value=await collect(item,[item['host']])
        self.assertEqual(value['status'],'UNKNOWN')
        self.assertEqual(value['reachability_status'],'UP')
        self.assertNotIn('cpu_percent',value)
        self.assertNotIn('interfaces',value)
