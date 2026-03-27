# API Research

## Sources inspected
- Postman collection: `C:\Users\bohda\Downloads\Platform test.postman_collection.json`
- Bot content JSON: `C:\Users\bohda\Downloads\botContent.json`

## Authentication method
- Header-based token authentication.
- Header name: `Authorization`
- The Postman collection uses the raw token value directly.
- No `Bearer` prefix is shown in the collection, so the implementation keeps the same format.

## Confirmed endpoints

### 1. Create user
- Method: `POST`
- Path: `/public/v1/bots/{botPublicId}/ai-chat/users`
- Full template: `{{baseUrl}}/public/v1/bots/{{botPublicId}}/ai-chat/users`
- Required headers:
  - `Authorization`
- Request body schema:
  - No request body is present in the Postman collection.
  - Implementation assumption: send no JSON body unless the contract changes later.
- Response body schema:
  - JSON response with `data.userId` and `data.chatId`
- Extraction:
  - `user_id` from `data.userId`
  - `chat_id` from `data.chatId`

### 2. Update user attributes
- Method: `PUT`
- Path: `/public/v1/users/{userId}/attributes`
- Full template: `{{baseUrl}}/public/v1/users/{{userId}}/attributes`
- Required headers:
  - `Authorization`
  - `Content-Type: application/json`
  - `accept: */*`
  - `Origin: https://echo-qa.botscrew.net`
- Request body schema:
```json
{
  "attributes": {
    "browser": "Chrome"
  }
}
```
- Response body schema:
  - Not documented in the collection.
  - Implementation treats any 2xx response as success and safely parses JSON only if present.

### 3. Trigger action
- Method: `POST`
- Path: `/public/v1/bots/{botPublicId}/ai-chat/users/{userId}/chat`
- Full template: `{{baseUrl}}/public/v1/bots/{{botPublicId}}/ai-chat/users/{{userId}}/chat`
- Required headers:
  - `Authorization`
  - `Content-Type: application/json`
- Request body schema:
```json
[
  {
    "role": "user",
    "content": "Please call any available action with test args and tell me result"
  }
]
```
- Response body schema:
  - The collection description says the endpoint returns SSE chunks with typed events.
  - Expected event types include `ai_action_input` and `ai_action_output`.
  - The collection does not include example SSE payloads, so the implementation parses SSE defensively.

## Required extraction targets

### `user_id`
- Confirmed source: create user response JSON at `data.userId`

### `chat_id`
- Confirmed source: create user response JSON at `data.chatId`

### `triggered_ai_action_name`
- Inference based on the collection description:
  - Prefer the SSE event payload for `ai_action_input`
  - Look for keys such as `action_name`, `ai_action_name`, `name`, `actionName`, `aiActionName`, `tool_name`, or `toolName`
- If not available, leave blank

### `ai_action_output`
- Inference based on the collection description:
  - Prefer the SSE event payload for `ai_action_output`
  - Look for keys such as `output`, `result`, `content`, `text`, or `message`
  - If the value is nested JSON, serialize only the needed output value as JSON text

### `request input used for trigger`
- Confirmed source: the user message content sent in the trigger request body
- The implementation writes that exact string to the output CSV `input` column

## Bot content attribute mapping

### Attribute source of truth
- Source: `botContent.json` top-level `attributes` array
- The file contains a flat attribute list
- No nested attribute definitions were found in the inspected bot content example

### Relevant attributes discovered
- Existing/default examples:
  - `browser`
  - `country`
  - `email`
  - `order_id`
  - `order_status`
  - `user_email`
  - `username`
- Custom action-related attributes present in the current bot content:
  - `location`
  - `refund_reason`
  - `refund_status`
  - `shipping_priority`
  - `delivery_eta`
  - `shipping_carrier`
  - `payment_method`
  - `payment_issue`
  - `payment_resolution`

### Mapping rule used by the implementation
- Build the update payload as:
```json
{
  "attributes": {
    "...": "..."
  }
}
```
- Include only row fields that match attribute names from the bot content source of truth
- Also support CSV columns prefixed with `attr_`; for example:
  - `attr_location` -> `location`
- Ignore fields that do not exist in the bot content attributes list
- Skip empty values
- If a CSV cell contains JSON text, parse it and send the parsed JSON value

### AI action names found in bot content
- `Get Knowledge`
- `Get order status`
- `Check refund eligibility`
- `Get shipping estimate`
- `Resolve payment issue`

## Implementation assumptions
- The create user endpoint is body-less because that is what the collection shows
- The trigger endpoint is treated as SSE/text-first, not standard JSON
- Attribute updates are flat because the inspected bot content attributes are flat
- The update user attributes origin is derived from `BASE_URL`
