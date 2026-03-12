# Requisitos Previos En macOS Para Conexion Exitosa

Este documento describe únicamente lo que debe tener preparada una Mac para que el agente local pueda conectarse correctamente al panel remoto.

## Objetivo

Dejar una Mac lista para:

- ejecutar el agente local
- abrir una PTY real con `node-pty`
- conectarse al backend de Replit
- reconectar automáticamente
- iniciar sola después de reiniciar sesión
- ser visible como `connected:true` en el panel remoto

## Compatibilidad

Requisitos mínimos:

- macOS 11 o superior
- Mac Intel (`x64`) o Apple Silicon (`arm64`)
- acceso a internet
- salida HTTPS/WSS permitida hacia el dominio de Replit

## Requisito 1: Xcode Command Line Tools

`node-pty` necesita herramientas nativas para compilar correctamente.

Instalar:

```bash
xcode-select --install
```

Verificar:

```bash
xcode-select -p
```

Debe devolver algo como:

```text
/Library/Developer/CommandLineTools
```

## Requisito 2: Homebrew

Si la Mac no tiene Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Verificar:

```bash
brew --version
```

## Requisito 3: Node 22 LTS

No usar `node` latest.

Para este agente, la versión recomendada es:

```text
Node 22 LTS
```

Instalar:

```bash
brew install node@22
```

Verificar:

```bash
/opt/homebrew/opt/node@22/bin/node -v
/opt/homebrew/opt/node@22/bin/npm -v
```

En Macs Intel, si no existe `/opt/homebrew`, revisar también:

```bash
/usr/local/opt/node@22/bin/node -v
/usr/local/opt/node@22/bin/npm -v
```

## Requisito 4: Carpeta del agente

La Mac debe tener el proyecto local del agente. Ejemplo:

```text
/Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
```

Entrar:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
```

Verificar que existan estos archivos:

```bash
ls -la
```

Debe haber por lo menos:

- `agent.js`
- `package.json`
- `.env`
- `launchd-install.sh`

## Requisito 5: Usar la versión actual del agente

La copia del repo en la Mac debe incluir la versión más reciente de `agent.js`.

Importante:

- la versión correcta ya incluye el header `Origin` en el handshake WebSocket
- sin ese cambio, el proxy de Replit puede aceptar la UI del navegador pero no el socket del agente

Verificar que el agente tenga la función `buildWsOrigin`:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
rg "buildWsOrigin|Origin" agent.js
```

## Requisito 6: Archivo `.env`

La Mac necesita un `.env` válido dentro de la carpeta del agente.

Contenido mínimo:

```env
PANEL_URL=https://remote-terminal-link.replit.app
AGENT_TOKEN=TU_TOKEN_DEL_AGENTE

AGENT_ID=
RECONNECT_DELAY_MS=5000
MAX_RECONNECT_DELAY_MS=30000
SHELL_OVERRIDE=
```

Crear o editar:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
cp .env.example .env 2>/dev/null || true
nano .env
```

Verificar sin exponer el token completo:

```bash
python3 - <<'PY'
from pathlib import Path
for line in Path('.env').read_text().splitlines():
    if '=' not in line or line.startswith('#'):
        continue
    k,v = line.split('=',1)
    if k == 'AGENT_TOKEN':
        print(f'{k}={v[:4]}...{v[-4:]}')
    else:
        print(f'{k}={v}')
PY
```

## Requisito 7: Instalar dependencias del agente

Usar siempre Node 22 para instalar o reconstruir dependencias.

Instalar:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm install
```

Si la Mac es Intel y no existe `/opt/homebrew`, usar:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/usr/local/opt/node@22/bin:$PATH" npm install
```

## Requisito 8: Recompilar `node-pty`

Esto es importante para que la shell no falle con errores como:

```text
posix_spawnp failed
```

Apple Silicon:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm rebuild node-pty --build-from-source
```

Intel:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/usr/local/opt/node@22/bin:$PATH" npm rebuild node-pty --build-from-source
```

## Requisito 9: Probar que la PTY abra localmente

Antes de conectar el panel, conviene probar que `node-pty` sí puede abrir `/bin/zsh`.

Apple Silicon:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" node - <<'NODE'
const pty = require('node-pty');
const os = require('os');
try {
  const p = pty.spawn('/bin/zsh', [], {
    name: 'xterm-256color',
    cols: 80,
    rows: 24,
    cwd: os.homedir(),
    env: process.env,
  });
  console.log('SPAWN_OK');
  p.onData((d) => {
    console.log(d.slice(0, 80));
    p.kill();
    process.exit(0);
  });
  p.onExit(() => process.exit(0));
} catch (err) {
  console.error('SPAWN_ERR', err.message);
  process.exit(1);
}
NODE
```

El resultado esperado debe incluir:

```text
SPAWN_OK
```

## Requisito 10: Probar el agente manualmente

Antes de instalar `launchd`, probar el agente a mano.

Apple Silicon:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" node agent.js
```

Intel:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/usr/local/opt/node@22/bin:$PATH" node agent.js
```

Resultado esperado:

```text
Connecting to backend...
Connected  (agentId: ...)
```

Si aparece un error de versión de Node, la Mac sigue usando un runtime incorrecto.

## Requisito 11: Instalar el LaunchAgent

Para que el agente arranque solo al iniciar sesión:

Apple Silicon:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
chmod +x launchd-install.sh
NODE_BIN=/opt/homebrew/opt/node@22/bin/node ./launchd-install.sh
```

Intel:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
chmod +x launchd-install.sh
NODE_BIN=/usr/local/opt/node@22/bin/node ./launchd-install.sh
```

Esto crea:

```text
~/Library/LaunchAgents/com.remoteshell.agent.plist
```

## Requisito 12: Verificar que `launchd` lo dejó corriendo

Ver LaunchAgent:

```bash
launchctl list | rg 'com\.remoteshell\.agent'
```

Ver proceso:

```bash
ps aux | rg 'com\.remoteshell\.agent|node agent\.js|node@22/bin/node'
```

Ver logs:

```bash
tail -f /tmp/remoteshell-agent.log
```

Resultado esperado en logs:

```text
Connecting to backend...
Connected  (agentId: ...)
```

## Requisito 13: Evitar agentes duplicados

No dejar uno manual y otro por `launchd` al mismo tiempo.

Si se ve algo como:

```text
Disconnected  code=4000  reason=Replaced by new agent connection
```

significa que hay dos procesos compitiendo.

Ver procesos:

```bash
ps aux | rg 'node agent\.js|node@22/bin/node'
```

Si hay uno manual extra, matarlo:

```bash
kill <PID>
```

## Requisito 14: Validar conectividad de red desde la Mac

Healthcheck:

```bash
curl -i -sS https://remote-terminal-link.replit.app/api/healthz
```

Debe responder:

```text
HTTP/2 200
{"status":"ok"}
```

Si quieres validar que el WebSocket del agente sí hace upgrade:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" node - <<'NODE'
const fs = require('fs');
const WebSocket = require('ws');
const env = fs.readFileSync('.env', 'utf8');
const get = (k) => (env.match(new RegExp('^' + k + '=(.*)$', 'm')) || [])[1];
const base = get('PANEL_URL').replace(/^https?:\/\//, 'wss://').replace(/\/$/, '');
const token = get('AGENT_TOKEN');
const url = `${base}/api/ws/agent?token=${encodeURIComponent(token)}&agentId=mac-prereq-check`;
const origin = base.replace(/^wss:\/\//, 'https://').replace(/^ws:\/\//, 'http://');
const ws = new WebSocket(url, {
  handshakeTimeout: 10000,
  headers: { Origin: origin },
});
ws.on('open', () => {
  console.log('WS_OPEN');
  setTimeout(() => ws.close(), 2000);
});
ws.on('close', (code, reason) => {
  console.log('WS_CLOSE', code, String(reason));
  process.exit(0);
});
ws.on('unexpected-response', (_req, res) => {
  console.log('WS_UNEXPECTED', res.statusCode);
  process.exit(1);
});
ws.on('error', (err) => {
  console.log('WS_ERROR', err.message);
  process.exit(1);
});
NODE
```

Validación adicional del estado visto por el panel:

```bash
python3 - <<'PY'
import requests
base='https://remote-terminal-link.replit.app'
admin='TU_ADMIN_TOKEN'
r=requests.post(base + '/api/auth/login', json={'token': admin}, timeout=10)
print('LOGIN', r.status_code, r.text)
if r.ok:
    token = r.json()['sessionToken']
    r2 = requests.get(
        base + '/api/agent/status',
        headers={'Authorization': f'Bearer {token}'},
        timeout=10,
    )
    print('STATUS', r2.status_code, r2.text)
PY
```

Resultado esperado:

```text
STATUS 200 {"connected":true,...}
```

## Requisito 15: Requisito externo en Replit

Aunque la Mac esté perfecta, la conexión completa no será estable si Replit sigue en `Autoscale`.

El deploy debe estar en:

```text
Reserved VM
```

Si no:

- el agente puede conectarse a una instancia
- la UI/API pueden caer en otra
- el panel mostrará `AGENT OFFLINE` aunque el agente sí esté conectado

## Secuencia completa recomendada

Ejecutar en este orden:

```bash
xcode-select --install
brew install node@22
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
rg "buildWsOrigin|Origin" agent.js
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm install
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm rebuild node-pty --build-from-source
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" node agent.js
chmod +x launchd-install.sh
NODE_BIN=/opt/homebrew/opt/node@22/bin/node ./launchd-install.sh
launchctl list | rg 'com\.remoteshell\.agent'
tail -f /tmp/remoteshell-agent.log
```

## Resultado final esperado

Cuando la Mac está lista correctamente:

- `node-pty` abre `/bin/zsh`
- el agente conecta al backend
- `launchd` lo deja persistente
- al reiniciar sesión, vuelve a arrancar solo
- el backend de Replit puede recibir la conexión
- `/api/agent/status` devuelve `connected:true`

Y cuando Replit también esté en `Reserved VM`:

- la UI mostrará `AGENT ONLINE`
- el terminal abrirá la shell correctamente
