#!/bin/bash
# Fetch Route 53 zone details: VPC associations for owned zones + shared zones per VPC
# Usage: bash fetch-route53-details.sh --profile PROFILE --region REGION

PROFILE=""
REGION=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --profile) PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROFILE" || -z "$REGION" ]]; then
  echo "Usage: bash fetch-route53-details.sh --profile PROFILE --region REGION"
  exit 1
fi

AWS="aws --profile $PROFILE --region $REGION --output json"

echo "=== Fetching Route 53 zone details ==="

# 1. Get hosted zone details (VPC associations for each private zone)
echo "📋 Fetching zone details with VPC associations..."
ZONE_DETAILS='{"HostedZoneDetails":['
FIRST=true

for ZONE_ID in $($AWS route53 list-hosted-zones --query 'HostedZones[?Config.PrivateZone==`true`].Id' --output text); do
  ZONE_ID_SHORT=$(echo "$ZONE_ID" | sed 's|/hostedzone/||')
  echo "  → Zone: $ZONE_ID_SHORT"
  DETAIL=$($AWS route53 get-hosted-zone --id "$ZONE_ID_SHORT" 2>/dev/null)
  if [[ $? -eq 0 && -n "$DETAIL" ]]; then
    if [[ "$FIRST" == "true" ]]; then
      FIRST=false
    else
      ZONE_DETAILS+=','
    fi
    ZONE_DETAILS+="$DETAIL"
  fi
done

ZONE_DETAILS+=']}'
echo "$ZONE_DETAILS" | python3 -m json.tool > hosted-zone-details.json 2>/dev/null
if [[ $? -ne 0 ]]; then
  echo "$ZONE_DETAILS" > hosted-zone-details.json
fi
echo "  ✓ Saved hosted-zone-details.json"

# 2. Get shared zones for each VPC (list-hosted-zones-by-vpc)
echo ""
echo "🔍 Fetching shared zones per VPC..."
VPC_ZONES='{"HostedZonesByVpc":{'
FIRST_VPC=true

for VPC_ID in $($AWS ec2 describe-vpcs --query 'Vpcs[*].VpcId' --output text); do
  echo "  → VPC: $VPC_ID"
  RESULT=$($AWS route53 list-hosted-zones-by-vpc --vpc-id "$VPC_ID" --vpc-region "$REGION" 2>/dev/null)
  if [[ $? -eq 0 && -n "$RESULT" ]]; then
    SUMMARIES=$(echo "$RESULT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(json.dumps(data.get('HostedZoneSummaries', [])))
" 2>/dev/null)
    if [[ -n "$SUMMARIES" ]]; then
      if [[ "$FIRST_VPC" == "true" ]]; then
        FIRST_VPC=false
      else
        VPC_ZONES+=','
      fi
      VPC_ZONES+="\"$VPC_ID\":$SUMMARIES"
    fi
  fi
done

VPC_ZONES+='}}'
echo "$VPC_ZONES" | python3 -m json.tool > hosted-zones-by-vpc.json 2>/dev/null
if [[ $? -ne 0 ]]; then
  echo "$VPC_ZONES" > hosted-zones-by-vpc.json
fi
echo "  ✓ Saved hosted-zones-by-vpc.json"

echo ""
echo "=== Done! Files created: ==="
echo "  hosted-zone-details.json  (owned zone VPC associations)"
echo "  hosted-zones-by-vpc.json  (all zones per VPC, including shared)"
