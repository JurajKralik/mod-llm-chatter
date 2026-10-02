-- Apply to the selected dedicated simulation database, not acore_characters.
CREATE TABLE IF NOT EXISTS sim_bot_identity (
 bot_guid INT UNSIGNED PRIMARY KEY,
 native_language CHAR(2) NOT NULL,
 identity_version INT UNSIGNED NOT NULL DEFAULT 1,
 identity_json JSON NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS sim_bot_player_relationship (
 bot_guid INT UNSIGNED NOT NULL, player_guid INT UNSIGNED NOT NULL,
 familiarity FLOAT NOT NULL DEFAULT 0, affinity FLOAT NOT NULL DEFAULT 0,
 trust FLOAT NOT NULL DEFAULT 0, respect FLOAT NOT NULL DEFAULT 0,
 annoyance FLOAT NOT NULL DEFAULT 0, interaction_count INT UNSIGNED NOT NULL DEFAULT 0,
 last_seen_at DATETIME NOT NULL, last_meaningful_at DATETIME NULL,
 summary VARCHAR(512) NOT NULL DEFAULT '',
 PRIMARY KEY(bot_guid, player_guid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS sim_bot_memory (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 bot_guid INT UNSIGNED NOT NULL, player_guid INT UNSIGNED NOT NULL,
 source_reference VARCHAR(80) NOT NULL,
 memory_type VARCHAR(32) NOT NULL, summary VARCHAR(1024) NOT NULL,
 salience FLOAT NOT NULL DEFAULT 0.5, decay_class VARCHAR(16) NOT NULL DEFAULT 'normal',
 occurred_at DATETIME NOT NULL, recall_count INT UNSIGNED NOT NULL DEFAULT 0,
 last_recalled_at DATETIME NULL, expires_at DATETIME NULL,
 UNIQUE KEY source_once(bot_guid, player_guid, source_reference),
 KEY recall_pair(bot_guid, player_guid, occurred_at), KEY cleanup_expiry(expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS sim_recent_dialogue (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, context_key VARCHAR(96) NOT NULL,
 source_reference VARCHAR(80) NOT NULL, speaker VARCHAR(64) NOT NULL,
 message VARCHAR(1024) NOT NULL, created_at DATETIME NOT NULL,
 UNIQUE KEY source_once(context_key, source_reference),
 KEY context_recent(context_key, id), KEY cleanup_age(created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS sim_schema_version (
 version INT UNSIGNED PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
INSERT IGNORE INTO sim_schema_version(version) VALUES(1);
