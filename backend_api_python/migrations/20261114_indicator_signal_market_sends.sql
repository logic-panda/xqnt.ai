-- Indicator signal alerts notify once per market (Crypto, Forex, ...) per candle and per minute,
-- whatever the symbol, so send claims are keyed by market instead of by symbol. Of the existing
-- claims that now share a key one stays, so candles notified before the upgrade stay claimed.
-- The lock holds off workers still on the old key (a rolling deploy) until the new key is in place.
LOCK TABLE qd_indicator_signal_sends;

DELETE FROM qd_indicator_signal_sends AS dup
USING qd_indicator_signal_sends AS kept
WHERE dup.user_id = kept.user_id
  AND dup.market = kept.market
  AND dup.slot = kept.slot
  AND dup.ctid > kept.ctid;

ALTER TABLE qd_indicator_signal_sends DROP CONSTRAINT IF EXISTS qd_indicator_signal_sends_pkey;
ALTER TABLE qd_indicator_signal_sends ADD PRIMARY KEY (user_id, market, slot);
