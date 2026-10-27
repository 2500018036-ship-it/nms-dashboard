"""Sustained zero traffic is an observation, not proof that a host is offline."""
import math


class IdleTraffic:
    def __init__(self,settings,database,emit):
        self.settings,self.database,self.emit=settings,database,emit

    def observe(self,name,rx,tx,now,link_running=True):
        key='network:idle:'+name
        state=self.database.states().get(key,{'active':False,'current':'UNKNOWN'})
        if now<state.get('updated_at',0):return state
        valid=link_running and all(type(value) in (int,float) and math.isfinite(value) and value>=0 for value in (rx,tx))
        if not valid:
            state.update(candidate=None,candidate_since=None,last_valid=None,observed='UNKNOWN',updated_at=now)
            self.database.set_state(key,state);return state
        zero=rx==0 and tx==0
        candidate='ZERO' if zero else 'TRAFFIC'
        gap=now-state.get('last_valid',now) if state.get('last_valid') is not None else 0
        if candidate!=state.get('candidate') or state.get('candidate_since') is None or gap>max(30,self.settings.network_interval*2.5):
            state['candidate_since']=now
        state.update(candidate=candidate,last_valid=now,observed=candidate,updated_at=now,rx_bps=rx,tx_bps=tx)
        elapsed=now-state['candidate_since']
        threshold=self.settings.traffic_resume_seconds if state.get('active') else self.settings.traffic_zero_seconds
        transition=(not state.get('active') and zero) or (state.get('active') and not zero)
        if transition and elapsed>=threshold:
            recovery=bool(state.get('active'))
            first=state.get('first_seen') if recovery else state['candidate_since']
            self.emit(key,'RECOVERY' if recovery else 'ALERT',
                'Trafik RX/TX terdeteksi kembali' if recovery else 'Tidak ada trafik RX/TX selama '+str(threshold//60)+' menit',
                'MikroTik',{'interface':name,'rx_bps':rx,'tx_bps':tx,'sustained_seconds':round(elapsed,1),
                    'threshold_seconds':threshold,'source':'delta counter RX dan TX pada sampel yang valid; link running',
                    'certainty':'Trafik nol dapat berarti link sedang sepi. Ini bukan bukti kabel, internet atau perangkat terputus.'},
                now,'INFO' if recovery else 'WARNING',first)
            state.update(active=not recovery,current='TRAFFIC' if recovery else 'ZERO',first_seen=None if recovery else first)
        elif not state.get('active'):
            state['current']=candidate
        self.database.set_state(key,state)
        return state

    def invalidate(self):
        for key,state in self.database.states().items():
            if key.startswith('network:idle:'):
                state.update(candidate=None,candidate_since=None,last_valid=None,observed='UNKNOWN')
                self.database.set_state(key,state)
