# SmartHelp Telco Support Automation Engine (Portfolio POC)

A scaled-down, faithful replica of a serverless telco-support automation
engine: a customer reports a broadband issue, the system runs a
diagnose → interpret → act → interpret loop, pauses for **human approval**
before any network-impacting action, then notifies the customer and records
the resolution. This repo is both a deployable AWS project and my interview
study guide for it — architecture rationale and Q&A live in this README as
the project grows.

**Status: Phase 1 of 5 — API Gateway → Lambda is live.** Everything else in
the architecture diagram below is designed but not yet built; phases are
tracked at the bottom of this file.

## Architecture (target — grayed-out pieces arrive in later phases)

```mermaid
flowchart LR
    Client([Client / curl]) --> APIGW["API Gateway HTTP API"]
    APIGW --> Router["Router Lambda\n(access control + validation)"]
    Router -.Phase 2.-> SQS[(SQS Queue)]
    SQS -.Phase 2.-> SFN{{"Step Functions\nStandard Workflow"}}

    subgraph SFN_Loop [" Step Functions: diagnose/act loop "]
        direction TB
        D["Trigger Diagnostics"] --> ID["Interpret Diagnostics"]
        ID --> A["Take Action"]
        A --> IA["Interpret Results"]
        IA -->|needs approval| GATE["waitForTaskToken\nHUMAN APPROVAL GATE"]
        GATE --> A
        IA -->|resolved| RES["Resolver"]
    end

    SFN -.Phase 2.-> SFN_Loop
    SFN_Loop -.Phase 2.-> DDB[("DynamoDB\nsession/state, TTL")]
    SFN_Loop -.Phase 2.-> SNS(("SNS\ncustomer notification"))
    SFN_Loop -.Phase 2.-> SSM["SSM Parameter Store\nconfig"]

    Reaper["Reaper Lambda"] -.Phase 3.-> EventBridge["EventBridge\nscheduled rule"]
    Reaper -.Phase 3.-> DDB

    SFN_Loop -.Phase 3.-> S3[("S3\nanalytics landing")]
    S3 -.Phase 3.-> Athena["Athena queries"]

    CW["CloudWatch\nLogs + Dashboard"] -.Phase 3.-> Router
    CW -.Phase 3.-> SFN_Loop
```

### Request flow (current, Phase 1)

1. Client sends `GET /health` or `POST /cases` to the API Gateway HTTP API
   `$default` stage.
2. API Gateway proxies the entire event to a single **router Lambda**
   (`AWS_PROXY` integration, payload format 2.0).
3. Inside the Lambda, `aws-lambda-powertools`'s `APIGatewayHttpResolver` does
   the actual GET/POST routing and JSON body validation — API Gateway itself
   stays a dumb pipe. This is the same "one router Lambda, internal routing"
   shape the real system uses for its access-control layer.
4. `POST /cases` currently just validates `customer_id` + `issue_type` and
   echoes an acknowledgment. Phase 2 replaces the echo with an SQS `SendMessage`
   that kicks off the Step Functions workflow.

## Why these choices (interview notes — grows every phase)

**Why API Gateway *HTTP API* and not a REST API?**
HTTP APIs are ~70% cheaper per request and have lower latency than REST APIs
for straightforward proxy-Lambda use cases. REST API's extra features
(request validation models, usage plans, API keys, WAF integration) aren't
needed here — the router Lambda does its own validation. I'd reach for REST
API if this needed per-key usage plans/quotas or edge-optimized custom domains
with WAF.

**Why one router Lambda with internal routing instead of one Lambda per
route?**
Mirrors the real system's access/router layer: a single entry point owns
auth/validation concerns uniformly, and `APIGatewayHttpResolver` gives
Flask-like `@app.get`/`@app.post` decorators so it doesn't turn into a big
if/elif block. It also means one cold start path and one IAM role to reason
about for the entry point, with business logic split into separate Lambdas
further into the workflow (Phase 2).

**Why build the Powertools Lambda layer ourselves instead of using AWS's
public layer ARN?**
AWS publishes a managed Powertools layer, but its ARN is
region/version/architecture-specific and lives outside this repo — anyone
cloning it would need to look up the right ARN. Building it via
`pip install --target` + `archive_file` keeps the dependency pinned and
reproducible from `requirements.txt`, at the cost of a slightly more complex
module (see `infra/modules/lambda_layer`). Trade-off I'd mention: the
self-built layer costs a `pip install` on every `requirements.txt` change;
the public layer costs nothing to adopt but couples you to AWS's release
cadence and ARN naming.

**How is IAM least-privilege applied?**
Every Lambda gets its own execution role (not a shared one). The `lambda`
module scopes the logging policy to that function's exact log group ARN
(`${log_group_arn}:*`), not `arn:aws:logs:*:*:*`. Later phases attach an
`additional_policy_json` per function — e.g. the diagnose Lambda gets
DynamoDB write access, the resolver gets SNS publish — rather than one broad
policy shared across all functions.

**Why S3 + DynamoDB for remote state, and why split by `-backend-config`
instead of Terraform workspaces?**
S3 gives durable, versioned state; the DynamoDB table provides state locking
so two `apply`s can't race. I used per-env `backend.hcl` + `-var-file`
instead of workspaces because workspaces share the same backend config and
make it easy to accidentally apply the wrong `.tfvars` against the wrong
state — separate backend keys per env (`dev/terraform.tfstate`,
`qa/...`, `prod/...`) make the blast radius of a mistake smaller and the
`terraform init` command itself makes the target environment explicit.

**Tagging strategy:** every resource gets `Project=telco-support-poc` and
`Environment=<env>` via the AWS provider's `default_tags`, so Cost Explorer
can filter by tag without me having to remember to tag each resource
individually.

## Repo layout

```
infra/
  versions.tf, providers.tf, variables.tf, main.tf, outputs.tf   # root module
  envs/{dev,qa,prod}/{backend.hcl, <env>.tfvars}                 # per-env config
  modules/
    lambda/          # generic Lambda function + its own log group + IAM role
    lambda_layer/     # pip-installs a requirements.txt into a Lambda layer
    http_api/         # API Gateway HTTP API, $default route/stage, access logs
src/
  router/handler.py   # the Phase 1 Lambda
  layers/powertools/requirements.txt
tests/                # pytest, one test module per Lambda
.github/workflows/     # CI/CD (Phase 4)
```

## One-time setup: bootstrap the Terraform state backend

The S3 bucket and DynamoDB lock table have to exist *before* `terraform init`
can use them as a backend — Terraform can't create the backend it's about to
store state in. Run once, with the AWS CLI, picking a globally-unique bucket
suffix (e.g. your account ID):

```bash
export STATE_SUFFIX=<your-unique-suffix>   # e.g. your 12-digit AWS account ID
export AWS_REGION=us-east-1

aws s3api create-bucket \
  --bucket telco-support-poc-tfstate-$STATE_SUFFIX \
  --region $AWS_REGION

aws s3api put-bucket-versioning \
  --bucket telco-support-poc-tfstate-$STATE_SUFFIX \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket telco-support-poc-tfstate-$STATE_SUFFIX \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws dynamodb create-table \
  --table-name telco-support-poc-tf-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

Then replace `<YOUR_UNIQUE_SUFFIX>` in `infra/envs/dev/backend.hcl` (and
qa/prod, once you use them) with the same suffix.

## Deploy (dev)

```bash
cd infra
terraform init -backend-config=envs/dev/backend.hcl
terraform plan  -var-file=envs/dev/dev.tfvars
terraform apply -var-file=envs/dev/dev.tfvars
```

The first `apply` pip-installs the Powertools layer locally (needs `pip3` on
your machine/CI runner) — expect that resource to show as
"(known after apply)" on the *first* `plan`, since the layer's zip contents
depend on a `terraform_data` provisioner that only runs at apply time.

## Demo

```bash
API=$(terraform -chdir=infra output -raw api_endpoint)

curl "$API/health"
# {"status":"ok","service":"telco-support-router"}

curl -X POST "$API/cases" \
  -H 'content-type: application/json' \
  -d '{"customer_id": "cust-123", "issue_type": "modem_offline"}'
# {"message":"case received","customer_id":"cust-123","issue_type":"modem_offline"}

curl -X POST "$API/cases" -H 'content-type: application/json' -d '{}'
# 400 — {"statusCode":400,"message":"missing required field(s): customer_id, issue_type"}
```

## Cost & Teardown

Everything provisioned so far (API Gateway HTTP API, one Lambda, one Lambda
layer, CloudWatch log groups) fits comfortably in AWS Free Tier for demo-level
traffic. Nothing in this phase runs 24/7 or bills per-hour.

To tear down:

```bash
cd infra
terraform destroy -var-file=envs/dev/dev.tfvars
```

The S3 state bucket and DynamoDB lock table from the bootstrap step are
**not** managed by this Terraform config (chicken-and-egg), so destroy them
manually if you want a full teardown:

```bash
aws s3 rb s3://telco-support-poc-tfstate-$STATE_SUFFIX --force
aws dynamodb delete-table --table-name telco-support-poc-tf-locks
```

## Interview Q&A (running list — grows every phase)

- **"Walk me through what happens when a request comes in."** → see Request
  flow above.
- **"Why not put all the routing logic in API Gateway?"** → API Gateway route
  keys would work for this simple case, but the real system's access layer
  needs to run auth/validation code, which belongs in Lambda, not gateway
  config — so it's one proxy route in and structured routing inside the
  function.
- **"How do you avoid a surprise AWS bill on a personal account?"** →
  Free-tier-only live services, `enable_tier2`/`enable_tier3` default false
  in Terraform so nothing that costs real money deploys by accident, no NAT
  Gateway anywhere, `terraform destroy` documented, resources tagged for
  Cost Explorer.

## Phases

- [x] **Phase 1** — Terraform skeleton, backend, one Lambda, API Gateway (live)
- [ ] **Phase 2** — Step Functions workflow, DynamoDB, SQS, SNS,
      diagnose/act Lambdas, human-approval gate
- [ ] **Phase 3** — EventBridge reaper, CloudWatch dashboard, S3/Athena analytics
- [ ] **Phase 4** — GitHub Actions CI/CD
- [ ] **Phase 5 (optional, disabled by default)** — RDS/VPC, Glue/EMR, OpenSearch
