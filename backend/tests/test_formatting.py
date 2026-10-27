from html.parser import HTMLParser
import unittest
from unittest.mock import AsyncMock
from telegram.error import BadRequest,TimedOut

from app.telegram.formatting import format_messages,chunks,status_text
from app.telegram.delivery import send_part
from app.alerts.engine import Alerts

class CheckHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.stack=[];self.text=[]
    def handle_starttag(self,tag,attrs):
        assert tag in {'b','i','code','pre'} and not attrs
        if tag in {'code','pre'}:assert not self.stack
        self.stack.append(tag)
    def handle_endtag(self,tag):assert self.stack.pop()==tag
    def handle_data(self,data):self.text.append(data)

class FormattingTests(unittest.TestCase):
    def check(self,text,limit=3500,**kwargs):
        parts=list(format_messages(text,limit,**kwargs))
        for part in parts:
            parser=CheckHTML();parser.feed(part.html);parser.close()
            self.assertFalse(parser.stack)
            self.assertEqual(''.join(parser.text),part.plain)
            self.assertLessEqual(len(part.plain.encode('utf-16-le'))//2,limit)
        return parts

    def test_screenshot_headings_bullets_and_tables(self):
        text='''### 4. **Database Health**
- **MariaDB**: `not_configured` bukan berarti down.

---

## Contoh status

| Target | Status | Potensi alarm |
|---|---|---|
| `proxmox` | **UNKNOWN** | TLS belum dipercaya |
| DNS | UP | Respons berhasil |
'''
        parts=self.check(text);html=''.join(p.html for p in parts);plain=''.join(p.plain for p in parts)
        self.assertIn('<b>Database Health</b>',html)
        self.assertIn('• Status: UNKNOWN',plain)
        self.assertIn('• Potensi alarm: TLS belum dipercaya',plain)
        for marker in ('###','**','|---','| Target','```'):self.assertNotIn(marker,plain)
        self.assertIn('not_configured',plain)

    def test_untrusted_html_and_entities_escaped(self):
        text='<script>alert(1)</script>\n\nCPU < 90% & RAM > 50%'
        parts=self.check(text)
        self.assertNotIn('<script>',''.join(p.html for p in parts))
        self.assertIn('CPU &lt; 90% &amp; RAM &gt; 50%',''.join(p.html for p in parts))

    def test_long_nested_bold_code_emoji_balanced(self):
        parts=self.check('**CPU *dan RAM* '+('😀 & < > '*1200)+'`cloud-storage-app-1`**',limit=200)
        self.assertGreater(len(parts),5)
        self.assertIn('cloud-storage-app-1',''.join(p.plain for p in parts))

    def test_code_blocks_preserve_literal_markers(self):
        text='```python\nprint("** bukan bold ** <x>")\n```'
        parts=self.check(text)
        self.assertIn('<pre>',parts[0].html)
        self.assertIn('** bukan bold ** <x>',parts[0].plain)

    def test_inline_code_not_nested_in_bold(self):self.check('**Nama `container` *penting***')

    def test_plain_admin_json_preserved(self):
        text='{"pattern": "**value**", "name": "not_configured"}'
        self.assertEqual(self.check(text,markdown=False)[0].plain,text)

    def test_paragraph_and_word_boundary_no_data_loss(self):
        text='Paragraf pertama.\n\nParagraf kedua dengan kata cukup panjang.\n\nSelesai.'
        parts=list(chunks(text,40))
        self.assertEqual(''.join(parts),text)
        self.assertTrue(parts[0].endswith('\n\n'))

    def test_lists_and_safe_links(self):
        parts=self.check('3. Langkah satu\n4. Langkah dua\n\n[panel](https://example.com/?a=1&b=2)\n\n![logo](https://example.com/logo.png)')
        plain=''.join(p.plain for p in parts)
        self.assertIn('3. Langkah satu',plain);self.assertIn('4. Langkah dua',plain)
        self.assertNotIn('<a',''.join(p.html for p in parts))
        self.assertNotIn('logo.png',plain)

    def test_status_contains_readable_names_and_reason(self):
        rows=[{'target':'proxmox_resources','status':'UNKNOWN','method':'PVE API','error':'missing_readonly_token'}, {'target':'technitium_dns','status':'UP','method':'DNS A'}]
        plain=''.join(p.plain for p in self.check(status_text(rows)))
        self.assertIn('Proxmox · VM/LXC',plain);self.assertIn('Token PVE read-only belum tersedia.',plain)
        self.assertNotIn('missing_readonly_token',plain)

    def test_alert_evidence_not_python_dict(self):
        text=Alerts.text({'kind':'ALERT','key':'docker:availability','first_seen':1,'time':2,'value':{'status':'DOWN','method':'snapshot'}})
        plain=''.join(p.plain for p in self.check(text))
        self.assertIn('• Status: DOWN',plain);self.assertNotIn("{'status'",plain)

    def test_empty_answer(self):self.assertEqual(self.check('   ')[0].plain,'Tidak ada isi jawaban.')

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_native_format(self):
        method=AsyncMock();part=next(format_messages('**Temuan**\nDNS `UP`.'))
        await send_part(method,part)
        self.assertEqual(method.call_args.kwargs['parse_mode'],'HTML')
        self.assertIn('<b>Temuan</b>',method.call_args.kwargs['text'])

    async def test_parse_rejection_falls_back_clean_plain(self):
        method=AsyncMock(side_effect=[BadRequest("Can't parse entities"),None]);part=next(format_messages('### **Temuan**'))
        await send_part(method,part)
        self.assertEqual(method.await_count,2)
        self.assertEqual(method.call_args.kwargs['text'],'Temuan')
        self.assertIsNone(method.call_args.kwargs['parse_mode'])

    async def test_other_bad_request_not_retried(self):
        method=AsyncMock(side_effect=BadRequest('Chat not found'))
        with self.assertRaises(BadRequest):await send_part(method,next(format_messages('Test')))
        self.assertEqual(method.await_count,1)

    async def test_timeout_not_blindly_retried(self):
        method=AsyncMock(side_effect=TimedOut())
        with self.assertRaises(TimedOut):await send_part(method,next(format_messages('Test')))
        self.assertEqual(method.await_count,1)
