#!/bin/bash
set -e  # exit on first error

# Generate a random operation_id for this test run using Python (no uuidgen required)
OPERATION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")

# 1. Get fresh admin token
echo "=== Refreshing admin token ==="
source env.sh
echo "ADMIN_TOKEN=$ADMIN_TOKEN"

# ----------------------------------------
# 2. Agent creates a farmer (admin acts as agent)
# ----------------------------------------
echo ""
echo "=== Creating farmer ==="
FARMER_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/agents/create-farmer" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+254523904411231",
    "full_name": "Alice Wambui",
    "region": "Kiambu",
    "crop": "potatoes",
    "quantity_bags": 30,
    "gps_latitude": -1.15,
    "gps_longitude": 36.75
  }')
echo "Farmer response: $FARMER_RESPONSE"
FARMER_ID=$(echo "$FARMER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['farmer_id'])")
HARVEST_ID=$(echo "$FARMER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['harvest_id'])")
echo "Farmer ID: $FARMER_ID"
echo "Harvest ID: $HARVEST_ID"

# ----------------------------------------
# 3. Admin creates a shipment in same region
# ----------------------------------------
echo ""
echo "=== Creating shipment ==="
SHIPMENT_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/shipments/?region=Kiambu&crop=potatoes&target_quantity_bags=50" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Shipment response: $SHIPMENT_RESPONSE"
SHIP_ID=$(echo "$SHIPMENT_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Shipment ID: $SHIP_ID"

# ----------------------------------------
# 4. Buyer places an order (admin acts as buyer)
# ----------------------------------------
echo ""
echo "=== Placing order ==="
ORDER_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/orders/" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"quantity_bags": 20, "delivery_location": "Kiambu", "crop": "potatoes"}')
echo "Order response: $ORDER_RESPONSE"
ORDER_ID=$(echo "$ORDER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
ORDER_STATUS=$(echo "$ORDER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
echo "Order ID: $ORDER_ID (status: $ORDER_STATUS)"
if [ "$ORDER_STATUS" != "reserved" ]; then
  echo "ERROR: Order should be reserved after matching!"
  exit 1
fi

# ----------------------------------------
# 5. Manually lock the shipment (since target not yet reached)
# ----------------------------------------
echo ""
echo "=== Locking shipment ==="
LOCK_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/shipments/$SHIP_ID/state?action=lock" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Lock response: $LOCK_RESPONSE"
LOCK_STATUS=$(echo "$LOCK_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
if [ "$LOCK_STATUS" != "locked" ]; then
  echo "ERROR: Shipment lock failed"
  exit 1
fi

# ----------------------------------------
# 6. Start verification
# ----------------------------------------
echo ""
echo "=== Starting verification ==="
VERIFY_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/shipments/$SHIP_ID/state?action=start_verification" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Verify response: $VERIFY_RESPONSE"

# ----------------------------------------
# 7. Agent submits verification (GPS matches farm) with unique operation_id
# ----------------------------------------
echo ""
echo "=== Submitting verification ==="
VERIF_SUBMIT=$(curl -s -X POST "http://localhost:8000/api/v1/verifications/submit" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"shipment_id\": \"$SHIP_ID\",
    \"farmer_id\": \"$FARMER_ID\",
    \"harvest_id\": \"$HARVEST_ID\",
    \"operation_id\": \"$OPERATION_ID\",
    \"claimed_quantity_bags\": 30,
    \"actual_quantity_bags\": 28,
    \"status\": \"adjusted\",
    \"gps_latitude\": -1.15,
    \"gps_longitude\": 36.75,
    \"quality_notes\": \"Good quality, slightly less\"
  }")
echo "Verification response: $VERIF_SUBMIT"
VERIF_STATUS=$(echo "$VERIF_SUBMIT" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
if [ "$VERIF_STATUS" != "adjusted" ]; then
  echo "ERROR: Verification submission failed"
  exit 1
fi

# ----------------------------------------
# 8. Check harvest status updated to VERIFIED
# ----------------------------------------
echo ""
echo "=== Checking harvest status ==="
HARVEST_CHECK=$(sudo -u postgres psql -d farmbridge_db -t -c "SELECT status, actual_quantity_bags FROM harvests WHERE id='$HARVEST_ID';")
echo "Harvest status: $HARVEST_CHECK"
if [[ "$HARVEST_CHECK" != *"VERIFIED"* ]]; then
  echo "ERROR: Harvest not updated to VERIFIED"
  exit 1
fi

# ----------------------------------------
# 9. Proceed through rest of shipment states
# ----------------------------------------
echo ""
echo "=== Advancing shipment to LOADING ==="
curl -s -X POST "http://localhost:8000/api/v1/shipments/$SHIP_ID/state?action=start_loading" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo "=== Advancing to IN_TRANSIT ==="
curl -s -X POST "http://localhost:8000/api/v1/shipments/$SHIP_ID/state?action=depart" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo "=== Advancing to ARRIVED_URBAN ==="
curl -s -X POST "http://localhost:8000/api/v1/shipments/$SHIP_ID/state?action=arrive_urban" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo "=== Advancing to DELIVERED ==="
DELIVER_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/shipments/$SHIP_ID/state?action=deliver" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Deliver response: $DELIVER_RESPONSE"
DELIVER_STATUS=$(echo "$DELIVER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
if [ "$DELIVER_STATUS" != "delivered" ]; then
  echo "ERROR: Delivery failed"
  exit 1
fi

# ----------------------------------------
# 10. Ratings should now be calculated for farmer (and admin as agent/buyer)
# ----------------------------------------
echo ""
echo "=== Checking ratings ==="
FARMER_RATING=$(curl -s "http://localhost:8000/api/v1/ratings/$FARMER_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Farmer rating: $FARMER_RATING"
if echo "$FARMER_RATING" | grep -q "overall_score"; then
  echo "Farmer rating found ✅"
else
  echo "ERROR: Farmer rating not generated"
  exit 1
fi

# Also check admin (as buyer) rating
ADMIN_RATING=$(curl -s "http://localhost:8000/api/v1/ratings/fd787c00-1303-4c18-b98b-b3831b69f934" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Admin/Buyer rating: $ADMIN_RATING"

# ----------------------------------------
# 11. Notifications should have been created
# ----------------------------------------
echo ""
echo "=== Checking notifications ==="
NOTIF_COUNT=$(sudo -u postgres psql -d farmbridge_db -t -c "SELECT COUNT(*) FROM notifications;")
echo "Notification count: $NOTIF_COUNT"
if [ "$NOTIF_COUNT" -gt 0 ]; then
  echo "Notifications exist ✅"
else
  echo "WARNING: No notifications found (may need Celery worker running)"
fi

# ----------------------------------------
# 12. Wallet check (buyer funds reserved, then ?)
# ----------------------------------------
echo ""
echo "=== Checking wallet ==="
WALLET=$(curl -s "http://localhost:8000/api/v1/wallet/" -H "Authorization: Bearer $ADMIN_TOKEN")
echo "Wallet: $WALLET"

echo ""
echo "========================================"
echo "✅ Full lifecycle test completed successfully!"
echo "========================================"