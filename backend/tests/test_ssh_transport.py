"""Exercise the SSH collector over a real, private loopback SSH transport."""
import asyncio
import os
import secrets
import unittest

import asyncssh

from app.monitoring import ssh


@unittest.skipUnless(os.path.isfile('/proc/stat'), 'Linux procfs is required')
class SSHTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_readonly_transport_reads_real_procfs_and_rejects_other_key(self):
        password = secrets.token_urlsafe(24)
        key = asyncssh.generate_private_key('ssh-ed25519')
        client_key = asyncssh.generate_private_key('ssh-ed25519')
        categories = list(ssh.COMMANDS)
        commands = []

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True

            def password_auth_supported(self):
                return True

            def public_key_auth_supported(self):
                return True

            def validate_public_key(self, username, supplied):
                return username == 'nms_readonly' and supplied == client_key.convert_to_public()

            def validate_password(self, username, supplied):
                return username == 'nms_readonly' and secrets.compare_digest(supplied, password)

        async def process_handler(process):
            commands.append(process.command)
            if process.command != ssh._command(categories):
                process.exit(126)
                return
            child = await asyncio.create_subprocess_exec('/bin/sh', '-c', process.command, stdout=asyncio.subprocess.PIPE)
            output, _ = await child.communicate()
            process.stdout.write(output.decode())
            process.exit(child.returncode)

        listener = await asyncssh.create_server(Server, '127.0.0.1', 0, server_host_keys=[key], process_factory=process_handler)
        credentials = {'username': 'nms_readonly', 'password': password, 'host_key_type': 'ssh-ed25519', 'host_key_data': key.export_public_key().decode().split()[1]}
        try:
            first = await ssh.probe('transport', '127.0.0.1', listener.get_port(), credentials, categories)
            self.assertEqual(first['status'], 'UP', first.get('error'))
            self.assertGreater(first['memory_total'], 0)
            self.assertGreater(first['uptime_seconds'], 0)
            self.assertTrue(first['interfaces'])
            await asyncio.sleep(1.05)
            second = await ssh.probe('transport', '127.0.0.1', listener.get_port(), credentials, categories, previous=first)
            self.assertEqual(second['status'], 'UP')
            self.assertIn('cpu_percent', second)
            self.assertTrue(any('rx_bps' in row for row in second['interfaces']))
            wrong = dict(credentials, host_key_data=asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode().split()[1])
            rejected = await ssh.probe('transport', '127.0.0.1', listener.get_port(), wrong, categories)
            self.assertEqual(rejected['error'], 'ssh_host_key_mismatch')
            self.assertEqual(len(commands), 2)
            key_credentials=dict(credentials,password='',auth_method='key',private_key=client_key.export_private_key().decode(),key_passphrase='')
            with_key=await ssh.probe('transport','127.0.0.1',listener.get_port(),key_credentials,categories)
            self.assertEqual(with_key['status'],'UP',with_key.get('error'))
            self.assertGreater(with_key['memory_total'],0)
            self.assertEqual(len(commands),3)
        finally:
            listener.close()
            await listener.wait_closed()
