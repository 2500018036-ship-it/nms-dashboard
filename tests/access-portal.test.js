import test from 'node:test'
import assert from 'node:assert/strict'
import { displayURL } from '../src/data/accessClient.js'

test('native display stays on the exact HTTPS NMS hostname without bearer URL tokens', () => {
  const path = `/access-api/sessions/${'a'.repeat(32)}/display`
  assert.equal(displayURL(path, { protocol: 'https:', host: 'nms.azrilachdi.web.id' }), 'wss://nms.azrilachdi.web.id' + path)
  for (const invalid of ['https://evil.test/', '//evil.test/ws', path + '?token=secret', '/access-api/sessions/../display']) assert.throws(() => displayURL(invalid, { protocol: 'https:', host: 'nms.azrilachdi.web.id' }))
  assert.throws(() => displayURL(path, { protocol: 'http:', host: 'nms.azrilachdi.web.id' }))
})
