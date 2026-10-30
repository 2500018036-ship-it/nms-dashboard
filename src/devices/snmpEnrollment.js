export const emptySnmp = () => ({version:'v3',community:'',username:'',auth_protocol:'sha',auth_secret:'',privacy_protocol:'aes128',privacy_secret:''})
export function snmpErrors(value) {
  const errors={}
  if(!['v2c','v3'].includes(value.version))errors.version='Pilih versi SNMP.'
  if(value.version==='v2c'&&(value.community.length<8||['public','private'].includes(value.community.toLowerCase())))errors.community='Gunakan community unik minimal 8 karakter, selain public/private.'
  if(value.version==='v3') {
    if(!value.username.trim())errors.username='Isi nama pengguna SNMPv3 (nama community pada RouterOS).'
    if(!['sha','sha256'].includes(value.auth_protocol))errors.auth_protocol='Pilih SHA-1 atau SHA-256 yang sesuai perangkat.'
    if(value.auth_secret.length<8)errors.auth_secret='Kunci autentikasi minimal 8 karakter.'
    if(value.privacy_secret.length<8)errors.privacy_secret='Kunci privasi minimal 8 karakter.'
    if(value.privacy_protocol!=='aes128')errors.privacy_protocol='Gunakan AES-128.'
  }
  return errors
}
export async function saveSnmpCredentials(client,id,snmp) {
  if(Object.keys(snmpErrors(snmp)).length)throw Object.assign(new Error('invalid_credentials'),{code:'invalid_credentials'})
  // Merge with a fresh vault read; GUI/Wi-Fi/SSH values never enter inventory or browser storage.
  const existing=await client.credentials('inventory',id)
  return client.credentials('inventory',id,{credentials:{...existing.credentials,snmp:{...snmp}}})
}
