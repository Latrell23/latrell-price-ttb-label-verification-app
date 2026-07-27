# Review Backend Flow

```mermaid
flowchart TD
    browser["Reviewer UI"]
    listRoute["GET /review/labels"]
    assetRoute["GET /review/assets/{image}"]
    oneRoute["POST /review/labels/{label_id}/verify"]
    queueRoute["POST /review/verify"]
    fixtures["Validated JSON + image fixtures"]
    vision["OpenAI vision extraction"]
    compare["Deterministic field comparison"]
    result["Review item / queue response"]

    browser --> listRoute
    browser --> assetRoute
    listRoute --> fixtures
    assetRoute --> fixtures
    browser --> oneRoute
    browser --> queueRoute
    oneRoute --> fixtures
    queueRoute --> fixtures
    fixtures --> vision
    vision --> compare
    compare --> result
    result --> browser
```

The full-queue endpoint processes fixture records concurrently up to
`MAX_REVIEW_CONCURRENCY`. Each item receives its own `completed` or `failed`
status, so one provider or image failure does not discard the rest of the queue.

Images and expected application data are backend-owned. The service does not
accept browser uploads or manually entered application values.
