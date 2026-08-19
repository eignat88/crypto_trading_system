ALTER TABLE raw_system.api_responses
    ADD COLUMN IF NOT EXISTS request_id text;

CREATE INDEX IF NOT EXISTS idx_api_responses_request_id
    ON raw_system.api_responses (exchange_name, request_id);
