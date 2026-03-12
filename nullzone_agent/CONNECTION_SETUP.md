# Conexion Del Panel Remoto: Paso A Paso

Este documento resume el flujo completo que finalmente dejó funcionando la conexión entre:

- backend en Replit
- UI web del panel
- agente local en macOS

## Estado final

La conexión ya quedó operativa.

Estado verificado:

- el agente local conecta al backend
- `node-pty` abre `/bin/zsh`
- el agente arranca solo con `launchd`
- `GET /api/agent/status` devuelve `connected:true`
- la UI muestra `AGENT ONLINE`
- la shell abre desde el navegador

Ejemplo real de estado:

```json
{"connected":true,"connectedAt":"2026-03-12T18:48:34.952Z","agentId":"agent-MacBook-Air-de-Francisco","ptyActive":true}
```

## 1. Corregir el routing WebSocket en Replit

### Problema inicial

El agente intentaba conectar a:

```text
/ws/agent
```

pero el deploy de Replit en producción solo estaba encaminando correctamente bajo `/api`.

Resultado inicial:

- `GET /api/healthz` respondía `200`
- `WS /ws/agent` respondía `502`

### Fix aplicado

Mover los endpoints WebSocket a:

```text
/api/ws/agent
/api/ws/browser
```

## 2. Normalizar paths en el backend de Replit

### Problema detectado

Aunque `/api/ws/agent` ya llegaba al backend, el servidor seguía cerrando con:

```text
4404 Unknown path
```

### Fix aplicado

El backend quedó aceptando ambas variantes:

```text
/ws/agent
/api/ws/agent
/ws/browser
/api/ws/browser
```

y también tolerando trailing slash.

## 3. Corregir un crash de producción en Express 5

### Problema detectado

El binario de producción se caía al arrancar por el fallback SPA:

```text
TypeError: Missing parameter name at index 1: *
```

### Causa

El fallback con `app.get("*", ...)` rompía en Express 5 bajo producción.

### Fix aplicado

Se reemplazó el fallback por middleware equivalente sin wildcard conflictivo.

Resultado:

- el servidor quedó estable en producción
- `/api/healthz` quedó respondiendo normalmente

## 4. Cambiar Replit a Reserved VM

### Problema detectado

El backend guarda la presencia del agente en memoria, algo equivalente a:

```ts
let agent = ...
```

Con `Autoscale`, el agente podía caer en una instancia y la UI/API en otra.

Entonces:

- el agente sí conectaba
- pero `/api/agent/status` devolvía `connected:false`
- la UI mostraba `AGENT OFFLINE`

### Fix aplicado

En Replit se cambió el deployment target a:

```text
Reserved VM
```

## 5. Corregir el runtime local de Node en macOS

### Problema detectado

El panel mostraba:

```text
[ERROR] Failed to spawn shell (/bin/zsh): posix_spawnp failed.
```

### Causa real

No era un problema de `/bin/zsh`.

Se verificó que:

- `/bin/zsh` existe
- `child_process.spawn('/bin/zsh')` funciona
- `node-pty` fallaba

La causa fue el runtime local:

```text
Node v25.6.1
```

### Fix aplicado

Se instaló y fijó:

```text
Node 22 LTS
```

Comando usado:

```bash
brew install node@22
```

## 6. Recompilar `node-pty`

### Problema

`node-pty` estaba enlazado al ABI del Node equivocado.

### Fix aplicado

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
env PATH="/opt/homebrew/opt/node@22/bin:$PATH" npm rebuild node-pty --build-from-source
```

## 7. Endurecer el agente para usar solo Node soportado

### Cambios hechos

Se actualizó `agent.js` para:

- rechazar Node fuera de `>=18 <25`
- recomendar explícitamente Node 22 LTS
- fallar con mensaje claro en vez de dejar un error ambiguo de `posix_spawnp`

## 8. Actualizar el LaunchAgent

### Problema

`launchd` podía tomar el `node` global equivocado.

### Fix aplicado

Se actualizó `launchd-install.sh` para:

- preferir `node@22`
- aceptar `NODE_BIN` explícito
- rechazar versiones fuera del rango soportado

Instalación usada:

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
NODE_BIN=/opt/homebrew/opt/node@22/bin/node ./launchd-install.sh
```

## 9. Evitar agentes duplicados

### Problema detectado

Había más de una instancia del agente corriendo a la vez y una expulsaba a la otra:

```text
Disconnected  code=4000  reason=Replaced by new agent connection
```

### Fix aplicado

Se dejó solo la instancia levantada por `launchd`.

## 10. Agregar `Origin` al handshake del agente

### Problema detectado

La UI del navegador sí llegaba al backend, pero el WebSocket del agente no quedaba visible en producción.

Síntoma:

- el browser se conectaba
- el agente parecía conectar
- pero la UI/API seguían sin ver al agente consistentemente

### Causa real

El proxy de producción de Replit requería un header `Origin` en el upgrade WebSocket.

Los navegadores lo envían automáticamente.
El agente con el paquete `ws` no lo enviaba por defecto.

### Fix aplicado

Se actualizó `agent.js` para construir y enviar:

```text
Origin: <PANEL_URL origin>
```

en cada handshake WebSocket del agente.

Ese fue el cambio final que permitió que producción reconociera la conexión del agente.

## 11. Verificación final exitosa

### API

Login:

```text
POST /api/auth/login => 200
```

Estado del agente:

```text
GET /api/agent/status => connected:true
```

### UI

Estado visible en el panel:

```text
AGENT ONLINE
Shell Active
```

Prompt visible en la terminal:

```text
alecksrodriguez@MacBook-Air-de-Francisco ~ %
```

## 12. Comandos útiles

### Ver versión activa de Node

```bash
node -v
```

### Ver logs del agente

```bash
tail -f /tmp/remoteshell-agent.log
```

### Ver si el LaunchAgent está cargado

```bash
launchctl list | rg 'com\\.remoteshell\\.agent'
```

### Reinstalar el LaunchAgent

```bash
cd /Users/alecksrodriguez/control/Nullzone-IT-Support-Agent
NODE_BIN=/opt/homebrew/opt/node@22/bin/node ./launchd-install.sh
```

### Descargar el agente

```bash
launchctl unload ~/Library/LaunchAgents/com.remoteshell.agent.plist
rm ~/Library/LaunchAgents/com.remoteshell.agent.plist
```

## 13. Resumen corto

Para que esto funcione de punta a punta:

1. Replit debe usar `/api/ws/...`.
2. El backend debe normalizar rutas WS.
3. El backend de producción no debe caerse al arrancar.
4. Replit debe correr en `Reserved VM`.
5. La Mac debe usar Node 22.
6. `node-pty` debe recompilarse con Node 22.
7. El agente debe correr con `launchd`.
8. El agente debe enviar `Origin` en el handshake WS.

Con todos esos puntos ya aplicados, la conexión queda funcional de extremo a extremo.
