# Engram Remote — Shared Memory for Cortex

Servidor centralizado de engram para compartir memoria persistente entre la instancia local (Mac) y la instancia remota (VPS/Telegram) de Cortex.

## Arquitectura

```
┌─────────────┐          ┌──────────────────────┐          ┌─────────────┐
│   Mac        │          │   Dockploy Container │          │   VPS       │
│             │          │                      │          │             │
│ Claude Code ─┤──HTTP──▶│  engram serve :7437  │◀──HTTP──├─ Claude Code │
│ + mcp proxy │          │  SQLite (volume)     │          │ + mcp proxy │
└─────────────┘          └──────────────────────┘          └─────────────┘
```

## Paso a paso

### 1. Deploy en Dockploy

Copiar el contenido de `docker-compose.yml` en Dockploy como nuevo servicio compose.

- Mapear puerto 7437
- El volume `engram-data` persiste la DB entre restarts
- Configurar dominio o IP publica

**Seguridad:** Engram no tiene auth. Opciones:
- Restringir por IP en el firewall de Dockploy
- Poner reverse proxy con basic auth (Caddy/Traefik)
- Usar Cloudflare Tunnel

### 2. Verificar que el server esta corriendo

```bash
./migrate.sh test http://TU_DOCKPLOY_URL:7437
```

### 3. Migrar memorias existentes

**Desde Mac:**
```bash
cd /Users/camarj/Documents/Proyectos/engram-remote
./migrate.sh all http://TU_DOCKPLOY_URL:7437
```

**Desde VPS:**
```bash
engram export engram-vps-export.json
curl -X POST http://TU_DOCKPLOY_URL:7437/import \
  -H "Content-Type: application/json" \
  -d @engram-vps-export.json
```

### 4. Configurar MCP en ambas instancias

Reemplazar el MCP server de engram local por el proxy remoto.

**Mac** — en `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "engram": {
      "command": "python3",
      "args": ["/Users/camarj/Documents/Proyectos/engram-remote/engram-mcp-proxy.py"],
      "env": {
        "ENGRAM_REMOTE_URL": "http://TU_DOCKPLOY_URL:7437"
      }
    }
  }
}
```

**VPS** — misma config apuntando a la misma URL.

### 5. Verificar

Desde cualquier instancia de Claude Code, las tools `mem_save`, `mem_search`, `mem_context`, etc. ahora hablan con el server remoto compartido.

## Archivos

| Archivo | Descripcion |
|---------|-------------|
| `docker-compose.yml` | Compose para Dockploy — descarga binario engram y corre `engram serve` |
| `engram-mcp-proxy.py` | MCP stdio proxy — traduce 14 tools MCP a HTTP API calls |
| `migrate.sh` | Script para exportar DB local e importar al server remoto |

## Notas

- El compose usa `alpine:3.19` + descarga del binario en runtime (no requiere build)
- Si tu servidor Dockploy es ARM64, cambia `amd64` por `arm64` en el URL del compose
- El proxy no tiene dependencias externas — solo stdlib de Python 3
- Engram v1.10.4 — verificar compatibilidad si actualizas
