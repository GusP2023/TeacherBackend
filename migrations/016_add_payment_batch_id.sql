-- 016_add_payment_batch_id.sql
-- Ejecutado manualmente en Neon por Gustavo:
ALTER TABLE payments ADD COLUMN payment_batch_id VARCHAR(36) NULL;
CREATE INDEX ix_payments_payment_batch_id ON payments (payment_batch_id);
