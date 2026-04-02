#!/bin/bash
# Fetch TGW route table routes and save to tgw-routes.json
# Usage: ./fetch-tgw-routes.sh [--region REGION]

REGION="${AWS_DEFAULT_REGION:-ap-northeast-2}"
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2;;
    *) shift;;
  esac
done

echo "Fetching TGW route tables from region: $REGION"

# Get all TGW route table IDs
RT_IDS=$(aws ec2 describe-transit-gateway-route-tables \
  --region "$REGION" \
  --query 'TransitGatewayRouteTables[].TransitGatewayRouteTableId' \
  --output text 2>/dev/null)

if [ -z "$RT_IDS" ]; then
  echo "No TGW route tables found or AWS CLI error"
  echo '{"TransitGatewayRouteTableRoutes":{}}' > tgw-routes.json
  exit 0
fi

echo "{"  > tgw-routes.json
echo '  "TransitGatewayRouteTableRoutes": {' >> tgw-routes.json

FIRST=true
for RT_ID in $RT_IDS; do
  echo "  Fetching routes for $RT_ID..."

  ROUTES=$(aws ec2 search-transit-gateway-routes \
    --region "$REGION" \
    --transit-gateway-route-table-id "$RT_ID" \
    --filters "Name=type,Values=static,propagated" \
    --output json 2>/dev/null)

  if [ -z "$ROUTES" ]; then
    ROUTES='{"Routes":[]}'
  fi

  if [ "$FIRST" = true ]; then
    FIRST=false
  else
    echo "," >> tgw-routes.json
  fi

  # Extract just the Routes array
  ROUTE_ARRAY=$(echo "$ROUTES" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('Routes',[])))" 2>/dev/null || echo "[]")
  printf '    "%s": %s' "$RT_ID" "$ROUTE_ARRAY" >> tgw-routes.json
done

echo "" >> tgw-routes.json
echo "  }" >> tgw-routes.json
echo "}" >> tgw-routes.json

echo "Done. Saved to tgw-routes.json"
