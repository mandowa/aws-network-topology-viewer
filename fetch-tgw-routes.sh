#!/bin/bash
# Fetch TGW route table routes and save to tgw-routes.json
# Usage: bash fetch-tgw-routes.sh --profile PROFILE --region REGION

REGION="${AWS_DEFAULT_REGION:-ap-northeast-2}"
PROFILE=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    *) shift;;
  esac
done

AWS_OPTS="--region $REGION --output json"
[ -n "$PROFILE" ] && AWS_OPTS="--profile $PROFILE $AWS_OPTS"

echo "Fetching TGW route tables (region: $REGION, profile: ${PROFILE:-default})"

RT_IDS=$(eval aws ec2 describe-transit-gateway-route-tables $AWS_OPTS \
  --query 'TransitGatewayRouteTables[].TransitGatewayRouteTableId' \
  --output text 2>/dev/null)

if [ -z "$RT_IDS" ]; then
  echo "No TGW route tables found"
  echo '{"TransitGatewayRoutesByTable":{}}' > tgw-routes.json
  exit 0
fi

TMPFILE=$(mktemp)
echo '{' > "$TMPFILE"
echo '  "TransitGatewayRoutesByTable": {' >> "$TMPFILE"

FIRST=true
for RT_ID in $RT_IDS; do
  echo "  Fetching routes for $RT_ID..."
  ROUTES=$(eval aws ec2 search-transit-gateway-routes $AWS_OPTS \
    --transit-gateway-route-table-id "$RT_ID" \
    --filters "Name=type,Values=static,propagated" 2>/dev/null)

  ROUTE_ARRAY=$(echo "${ROUTES:-"{}"}" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('Routes',[])))" 2>/dev/null || echo "[]")

  [ "$FIRST" = true ] && FIRST=false || echo "," >> "$TMPFILE"
  printf '    "%s": %s' "$RT_ID" "$ROUTE_ARRAY" >> "$TMPFILE"
done

echo "" >> "$TMPFILE"
echo "  }" >> "$TMPFILE"
echo "}" >> "$TMPFILE"
mv "$TMPFILE" tgw-routes.json

echo "Done. Saved to tgw-routes.json"
