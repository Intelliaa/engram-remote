#!/bin/bash
# Engram Migration Script
# Exports local engram DB and imports to remote server
#
# Usage:
#   ./migrate.sh export              # Export local DB to engram-export.json
#   ./migrate.sh import <url>        # Import the export to remote server
#   ./migrate.sh all <url>           # Export + import in one step
#   ./migrate.sh test <url>          # Test connection to remote server

set -euo pipefail

EXPORT_FILE="engram-export.json"

case "${1:-help}" in
  export)
    echo "Exporting local engram database..."
    engram export "$EXPORT_FILE"
    echo "Exported to $EXPORT_FILE"
    echo "Size: $(du -h "$EXPORT_FILE" | cut -f1)"
    ;;

  import)
    URL="${2:?Usage: ./migrate.sh import <remote-url>}"
    URL="${URL%/}"
    echo "Importing $EXPORT_FILE to $URL..."

    if [ ! -f "$EXPORT_FILE" ]; then
      echo "Error: $EXPORT_FILE not found. Run './migrate.sh export' first."
      exit 1
    fi

    if ! curl -sf "$URL/health" > /dev/null 2>&1; then
      echo "Error: Cannot reach $URL/health"
      exit 1
    fi

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$URL/import" \
      -H "Content-Type: application/json" \
      -d @"$EXPORT_FILE")

    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
      echo "Import successful!"
      echo "Remote stats:"
      curl -s "$URL/stats" | python3 -m json.tool 2>/dev/null || curl -s "$URL/stats"
    else
      echo "Import failed with HTTP $HTTP_CODE"
      exit 1
    fi
    ;;

  all)
    URL="${2:?Usage: ./migrate.sh all <remote-url>}"
    $0 export
    $0 import "$URL"
    ;;

  test)
    URL="${2:?Usage: ./migrate.sh test <remote-url>}"
    URL="${URL%/}"
    echo "Testing connection to $URL..."
    HEALTH=$(curl -sf "$URL/health" 2>&1) && {
      echo "OK: $HEALTH"
      echo ""
      echo "Stats:"
      curl -s "$URL/stats" | python3 -m json.tool 2>/dev/null || curl -s "$URL/stats"
    } || {
      echo "FAILED: Cannot reach $URL/health"
      exit 1
    }
    ;;

  help|*)
    echo "Engram Migration Tool"
    echo ""
    echo "Usage:"
    echo "  ./migrate.sh export           Export local DB to $EXPORT_FILE"
    echo "  ./migrate.sh import <url>     Import to remote server"
    echo "  ./migrate.sh all <url>        Export + import in one step"
    echo "  ./migrate.sh test <url>       Test remote connection"
    ;;
esac
