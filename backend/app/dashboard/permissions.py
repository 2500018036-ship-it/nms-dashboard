"""Server-authoritative role capabilities. Legacy role names remain compatible."""
READ={'monitor.read','assistant.ask'}
NETWORK={'inventory.manage','network.change','topology.manage'}
SERVER={'inventory.manage','server.operate','topology.manage'}
ALL=READ|NETWORK|SERVER|{'config.manage','credentials.read','credentials.manage','users.manage','incidents.manage','audit.read'}
ROLE_PERMISSIONS={
 'Read-only operator':READ,'Viewer':READ,
 'Operator':READ|{'incidents.manage'},
 'Network Administrator':READ|NETWORK|{'incidents.manage','audit.read'},
 'Server Administrator':READ|SERVER|{'incidents.manage','audit.read'},
 'Administrator':ALL,'Super Administrator':ALL,
}
def permissions(session):return ROLE_PERMISSIONS.get((session or {}).get('user',{}).get('role'),set())
def require(session,permission):
 from app.dashboard.platform import Forbidden
 if permission not in permissions(session):raise Forbidden()
 return session['user']['username']
