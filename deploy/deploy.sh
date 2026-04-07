#!/bin/bash
# Deploy AWS Network Topology Viewer to S3 + Lambda
# Usage: bash deploy/deploy.sh --profile PROFILE --region REGION --allowed-ips "1.2.3.4/32,5.6.7.0/24"

set -e

PROFILE=""
REGION="ap-northeast-2"
STACK_NAME="network-topology-viewer"
ALLOWED_IPS=""
DATA_REGION="ap-northeast-2"

while [[ $# -gt 0 ]]; do
  case $1 in
    --profile) PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --stack-name) STACK_NAME="$2"; shift 2 ;;
    --allowed-ips) ALLOWED_IPS="$2"; shift 2 ;;
    --data-region) DATA_REGION="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROFILE" || -z "$ALLOWED_IPS" ]]; then
  echo "Usage: bash deploy/deploy.sh --profile PROFILE --allowed-ips \"CIDR1,CIDR2\""
  echo ""
  echo "Options:"
  echo "  --profile       AWS CLI profile"
  echo "  --region        Deploy region (default: ap-northeast-2)"
  echo "  --stack-name    CloudFormation stack name (default: network-topology-viewer)"
  echo "  --allowed-ips   Comma-separated CIDR blocks for IP whitelist"
  echo "  --data-region   Region to fetch AWS data from (default: ap-northeast-2)"
  exit 1
fi

AWS="aws --profile $PROFILE --region $REGION"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Deploying CloudFormation Stack ==="
$AWS cloudformation deploy \
  --template-file "$SCRIPT_DIR/template.yaml" \
  --stack-name "$STACK_NAME" \
  --parameter-overrides \
    AllowedIPs="$ALLOWED_IPS" \
    DataRegion="$DATA_REGION" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset

# Get outputs
BUCKET=$($AWS cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' --output text)
LAMBDA=$($AWS cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`LambdaFunction`].OutputValue' --output text)
URL=$($AWS cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`WebsiteURL`].OutputValue' --output text)

echo ""
echo "=== Uploading Viewer Files ==="
$AWS s3 sync "$PROJECT_DIR/viewer/" "s3://$BUCKET/viewer/" --delete
# Upload index.html to root
$AWS s3 cp "$PROJECT_DIR/viewer/index.html" "s3://$BUCKET/index.html" --content-type "text/html"

echo ""
echo "=== Deploying Lambda Code ==="
# Package lambda with generator
TMPDIR=$(mktemp -d)
cp "$SCRIPT_DIR/lambda_handler.py" "$TMPDIR/"
cp "$PROJECT_DIR/generate_aws_diagram.py" "$TMPDIR/"
(cd "$TMPDIR" && zip -r lambda.zip .)
$AWS lambda update-function-code \
  --function-name "$LAMBDA" \
  --zip-file "fileb://$TMPDIR/lambda.zip"
rm -rf "$TMPDIR"

echo ""
echo "=== Running Initial Data Fetch ==="
$AWS lambda invoke \
  --function-name "$LAMBDA" \
  --log-type Tail \
  /tmp/lambda-output.json
echo "Lambda output:"
cat /tmp/lambda-output.json

echo ""
echo "=== Done ==="
echo "Viewer URL: $URL/viewer/"
echo "Bucket: $BUCKET"
echo "Lambda: $LAMBDA"
echo ""
echo "The topology will auto-refresh every 24 hours."
echo "To manually refresh: $AWS lambda invoke --function-name $LAMBDA /tmp/out.json"
