-- Additive transport extension; apply to acore_characters. No upstream columns changed.
CREATE TABLE IF NOT EXISTS llm_sim_context (
 context_key VARCHAR(96) PRIMARY KEY, event_id INT UNSIGNED NULL,
 lease_until DATETIME NULL, next_visible_at DATETIME NULL,
 last_speaker INT UNSIGNED NOT NULL DEFAULT 0,
 updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 KEY cleanup_age(updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS llm_sim_outbox (
 message_id INT UNSIGNED PRIMARY KEY, event_id INT UNSIGNED NOT NULL,
 context_key VARCHAR(96) NOT NULL, bot_guid INT UNSIGNED NOT NULL,
 player_guid INT UNSIGNED NOT NULL, map_id INT UNSIGNED NOT NULL,
 instance_id INT UNSIGNED NOT NULL, group_id INT UNSIGNED NOT NULL DEFAULT 0,
 guild_id INT UNSIGNED NOT NULL DEFAULT 0, channel_id INT UNSIGNED NOT NULL DEFAULT 0,
 intent VARCHAR(32) NOT NULL DEFAULT 'none',
 status VARCHAR(16) NOT NULL DEFAULT 'pending', reason VARCHAR(64) NOT NULL DEFAULT '',
 expires_at DATETIME NOT NULL, completed_at DATETIME NULL,
 feedback_recorded TINYINT UNSIGNED NOT NULL DEFAULT 0,
 UNIQUE KEY event_once(event_id), KEY bot_pending(bot_guid, status),
 KEY pending_expiry(status, expires_at), KEY feedback(feedback_recorded, completed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS llm_sim_action_lease (
 bot_guid INT UNSIGNED PRIMARY KEY, player_guid INT UNSIGNED NOT NULL,
 group_id INT UNSIGNED NOT NULL,
 expires_at DATETIME NOT NULL, KEY expiry(expires_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS llm_sim_speaker (
 bot_guid INT UNSIGNED PRIMARY KEY, event_id INT UNSIGNED NULL,
 lease_until DATETIME NULL, last_visible_at DATETIME NULL,
 KEY cleanup_lease(lease_until)
) ENGINE=InnoDB;
