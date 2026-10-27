"""Unprivileged Linux ping socket; no shell, raw socket, or capabilities."""
import asyncio
import os
import socket
import struct
import time
from app.monitoring.common import result

def checksum(data):
    if len(data)%2:data+=b'\0'
    total=sum(struct.unpack('!%dH'%(len(data)//2),data))
    total=(total>>16)+(total&65535);total+=(total>>16)
    return (~total)&65535

async def _probe_once(target,host):
    sock=None;started=time.monotonic()
    try:
        socket.inet_pton(socket.AF_INET,host)
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_ICMP)
        sock.setblocking(False);sock.connect((host,0))
        payload=b'NMS-OBSERVE'+os.urandom(16)
        header=struct.pack('!BBHHH',8,0,0,0,1)
        packet=struct.pack('!BBHHH',8,0,checksum(header+payload),0,1)+payload
        loop=asyncio.get_running_loop()
        async with asyncio.timeout(2):
            await loop.sock_sendall(sock,packet)
            while True:
                received=await loop.sock_recv(sock,256)
                if len(received)>=8 and received[0:2]==b'\0\0' and received[8:]==payload:
                    return result(target,'ICMP echo unprivileged','UP',host=host,latency_ms=round((time.monotonic()-started)*1000,2),
                        detail='Host membalas ICMP; bukan bukti seluruh layanan sehat.')
    except PermissionError:
        return result(target,'ICMP echo',error='icmp_not_permitted',detail='Kernel tidak mengizinkan ping socket; tidak menambah capability administratif.')
    except ValueError:
        return result(target,'ICMP echo',error='invalid_host',host=host)
    except (TimeoutError,OSError):
        return result(target,'ICMP echo','DOWN',host=host,error='icmp_no_reply',
            detail='Tidak mendapat balasan ICMP. Host offline, firewall, atau gangguan jalur masih perlu dibedakan.')
    finally:
        if sock:sock.close()


async def probe(target,host):
    # Confirm a missed echo once; a successful echo remains real evidence.
    for attempt in (1,2):
        value=await _probe_once(target,host)
        value['attempts']=attempt
        if value['status']!='DOWN':return value
        if attempt==1:await asyncio.sleep(0.15)
    return value
