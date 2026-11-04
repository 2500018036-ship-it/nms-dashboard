export const emptySsh=()=>({username:'',password:'',host_key_type:'ssh-ed25519',host_key_data:''})
export function sshErrors(value){
  const errors={}
  if(!value.username.trim()||value.username.toLowerCase()==='root')errors.username='Gunakan akun Linux non-root khusus monitoring.'
  if(!value.password)errors.password='Isi kata sandi SSH.'
  if(!/^[A-Za-z0-9+/]+={0,2}$/.test(value.host_key_data))errors.host_key_data='Isi bagian Base64 public host key dari console tepercaya.'
  return errors
}
