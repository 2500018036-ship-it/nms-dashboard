export const emptySsh=()=>({username:'',password:'',auth_method:'password',private_key:'',key_passphrase:'',host_key_type:'ssh-ed25519',host_key_data:''})
export function sshErrors(value){
  const errors={}
  if(!value.username.trim()||value.username.toLowerCase()==='root')errors.username='Gunakan akun Linux non-root khusus monitoring.'
  if((value.auth_method||'password')==='password'&&!value.password)errors.password='Isi kata sandi SSH.'
  if(!/^[A-Za-z0-9+/]+={0,2}$/.test(value.host_key_data))errors.host_key_data='Isi bagian Base64 public host key dari console tepercaya.'
  if(value.auth_method==='key'&&!value.private_key?.includes('PRIVATE KEY'))errors.private_key='Isi private key SSH milik akun monitoring.'
  return errors
}
