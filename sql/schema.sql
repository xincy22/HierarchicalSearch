CREATE TABLE IF NOT EXISTS documents (
    doc_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    doc_key VARCHAR(512) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    file_topic TEXT NOT NULL,
    doc_title VARCHAR(512) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ux_documents_doc_key (doc_key)
);

CREATE TABLE IF NOT EXISTS sections (
    doc_id BIGINT NOT NULL,
    section_id VARCHAR(64) NOT NULL,
    level INT NOT NULL,
    title_text VARCHAR(512) NOT NULL,
    body_text LONGTEXT NOT NULL,
    heading_raw VARCHAR(512) NULL,
    heading_prefix_raw VARCHAR(128) NULL,
    start_pos INT NULL,
    end_pos INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (doc_id, section_id),
    KEY idx_sections_doc_level (doc_id, level),
    CONSTRAINT fk_sections_document FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);
