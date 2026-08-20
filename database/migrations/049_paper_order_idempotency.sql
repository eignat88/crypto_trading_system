ALTER TABLE paper_orders
ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(160);

ALTER TABLE paper_orders
ADD COLUMN IF NOT EXISTS side VARCHAR(8) NOT NULL DEFAULT 'BUY';

ALTER TABLE paper_orders
ADD COLUMN IF NOT EXISTS quantity NUMERIC(20,8) NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_orders_client_order_id
ON paper_orders(client_order_id)
WHERE client_order_id IS NOT NULL;

ALTER TABLE paper_fills
ADD COLUMN IF NOT EXISTS fill_id VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_fills_fill_id
ON paper_fills(fill_id)
WHERE fill_id IS NOT NULL;
