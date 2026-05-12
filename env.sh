#!/bin/bash
# Refresh admin token and store it
export ADMIN_TOKEN=$(curl -s 'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=AIzaSyAoCxmulg3mzxDfw73nASGkrFtKknDaEPI' \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com","password":"123456","returnSecureToken":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['idToken'])")
echo "ADMIN_TOKEN set"

# Create a new shipment and automatically store its ID
SHIP_ID=$(curl -s -X POST "http://localhost:8000/api/v1/shipments/?region=Kiambu&crop=potatoes&target_quantity_bags=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
export SHIP_ID
echo "SHIP_ID=$SHIP_ID"
