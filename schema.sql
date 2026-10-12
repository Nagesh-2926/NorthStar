BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 082c83387a35

CREATE TABLE users (
    id UUID NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    password_hash VARCHAR(512) NOT NULL, 
    role VARCHAR(24) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_users_role CHECK (role IN ('student', 'coordinator'))
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE students (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    UNIQUE (user_id)
);

CREATE TABLE enrollments (
    id UUID NOT NULL, 
    student_id UUID NOT NULL, 
    code_module VARCHAR(8) NOT NULL, 
    code_presentation VARCHAR(8) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, 
    CONSTRAINT uq_enrollment_student_module_presentation UNIQUE (student_id, code_module, code_presentation)
);

CREATE INDEX ix_enrollments_student_id ON enrollments (student_id);

CREATE TABLE academic_records (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    record_type VARCHAR(48) NOT NULL, 
    score FLOAT, 
    occurred_on TIMESTAMP WITH TIME ZONE, 
    metadata JSON NOT NULL, 
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_academic_score_range CHECK (score IS NULL OR (score >= 0 AND score <= 100)), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE
);

CREATE INDEX ix_academic_enrollment_recorded ON academic_records (enrollment_id, recorded_at);

CREATE TABLE behavioral_clusters (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    requested_by_user_id UUID NOT NULL, 
    cluster_id INTEGER NOT NULL, 
    model_version VARCHAR(32) NOT NULL, 
    feature_version VARCHAR(64) NOT NULL, 
    observed_signals JSON NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    FOREIGN KEY(requested_by_user_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_cluster_enrollment_assigned ON behavioral_clusters (enrollment_id, assigned_at);

CREATE TABLE engagement_records (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    week_index INTEGER NOT NULL, 
    clicks INTEGER NOT NULL, 
    active_days INTEGER NOT NULL, 
    metrics JSON NOT NULL, 
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_engagement_counts CHECK (clicks >= 0 AND active_days >= 0 AND active_days <= 7), 
    CONSTRAINT ck_engagement_week_range CHECK (week_index >= 0 AND week_index <= 60), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    CONSTRAINT uq_engagement_week UNIQUE (enrollment_id, week_index)
);

CREATE INDEX ix_engagement_records_enrollment_id ON engagement_records (enrollment_id);

CREATE TABLE interventions (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    created_by_user_id UUID NOT NULL, 
    title VARCHAR(160) NOT NULL, 
    notes VARCHAR(4000) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    due_date DATE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_intervention_status CHECK (status IN ('open', 'in_progress', 'completed', 'cancelled')), 
    FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE
);

CREATE INDEX ix_interventions_enrollment_id ON interventions (enrollment_id);

CREATE TABLE predictions (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    requested_by_user_id UUID NOT NULL, 
    model_name VARCHAR(64) NOT NULL, 
    model_version VARCHAR(32) NOT NULL, 
    feature_version VARCHAR(64) NOT NULL, 
    support_priority_score FLOAT NOT NULL, 
    threshold FLOAT NOT NULL, 
    priority_band VARCHAR(32) NOT NULL, 
    observed_signals JSON NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_prediction_score_range CHECK (support_priority_score >= 0 AND support_priority_score <= 1), 
    CONSTRAINT ck_prediction_threshold_range CHECK (threshold >= 0 AND threshold <= 1), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    FOREIGN KEY(requested_by_user_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_prediction_enrollment_created ON predictions (enrollment_id, created_at);

CREATE TABLE study_plans (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    created_by_user_id UUID NOT NULL, 
    source_prediction_id UUID, 
    content JSON NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    generated_by_llm BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_study_plan_status CHECK (status IN ('draft', 'active', 'completed')), 
    FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    FOREIGN KEY(source_prediction_id) REFERENCES predictions (id) ON DELETE SET NULL
);

CREATE INDEX ix_study_plans_enrollment_id ON study_plans (enrollment_id);

CREATE TABLE motivational_messages (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    study_plan_id UUID, 
    content VARCHAR(1200) NOT NULL, 
    source VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    FOREIGN KEY(study_plan_id) REFERENCES study_plans (id) ON DELETE CASCADE
);

CREATE INDEX ix_motivational_messages_enrollment_id ON motivational_messages (enrollment_id);

INSERT INTO alembic_version (version_num) VALUES ('082c83387a35') RETURNING alembic_version.version_num;

-- Running upgrade 082c83387a35 -> 6fc7d5c29b43

CREATE TABLE assessment_schedule (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    assessment_key VARCHAR(64) NOT NULL, 
    scheduled_day INTEGER, 
    weight FLOAT, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_assessment_scheduled_day CHECK (scheduled_day IS NULL OR (scheduled_day >= -365 AND scheduled_day <= 500)), 
    CONSTRAINT ck_assessment_weight CHECK (weight IS NULL OR (weight >= 0 AND weight <= 100)), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    CONSTRAINT uq_assessment_enrollment_key UNIQUE (enrollment_id, assessment_key)
);

CREATE INDEX ix_assessment_schedule_enrollment_id ON assessment_schedule (enrollment_id);

ALTER TABLE enrollments ADD COLUMN registration_day INTEGER;

ALTER TABLE enrollments ADD COLUMN num_of_prev_attempts INTEGER;

ALTER TABLE enrollments ADD COLUMN studied_credits INTEGER;

ALTER TABLE enrollments ADD CONSTRAINT ck_enrollment_registration_day CHECK (registration_day IS NULL OR (registration_day >= -322 AND registration_day <= 49));

ALTER TABLE enrollments ADD CONSTRAINT ck_enrollment_previous_attempts CHECK (num_of_prev_attempts IS NULL OR (num_of_prev_attempts >= 0 AND num_of_prev_attempts <= 6));

ALTER TABLE enrollments ADD CONSTRAINT ck_enrollment_studied_credits CHECK (studied_credits IS NULL OR (studied_credits >= 30 AND studied_credits <= 655));

ALTER TABLE engagement_records DROP CONSTRAINT ck_engagement_counts;

ALTER TABLE engagement_records ADD CONSTRAINT ck_engagement_counts CHECK (clicks >= 0 AND clicks <= 9481 AND active_days >= 0 AND active_days <= 7);

ALTER TABLE academic_records ADD COLUMN assessment_key VARCHAR(64);

ALTER TABLE academic_records ADD COLUMN submitted_day INTEGER;

ALTER TABLE academic_records ADD CONSTRAINT ck_academic_assessment_source CHECK (record_type != 'assessment_score' OR (assessment_key IS NOT NULL AND submitted_day IS NOT NULL AND submitted_day >= 0 AND submitted_day <= 608));

ALTER TABLE academic_records ADD CONSTRAINT uq_academic_enrollment_assessment UNIQUE (enrollment_id, assessment_key);

UPDATE alembic_version SET version_num='6fc7d5c29b43' WHERE alembic_version.version_num = '082c83387a35';

-- Running upgrade 6fc7d5c29b43 -> 9a1d7e04b62f

ALTER TABLE students ADD COLUMN enrollment_number VARCHAR(32);

CREATE UNIQUE INDEX ix_students_enrollment_number ON students (enrollment_number);

UPDATE alembic_version SET version_num='9a1d7e04b62f' WHERE alembic_version.version_num = '6fc7d5c29b43';

-- Running upgrade 9a1d7e04b62f -> 23ba7783d120

CREATE TABLE dataset_imports (
    id UUID NOT NULL, 
    uploaded_by_user_id UUID NOT NULL, 
    original_filename VARCHAR(255) NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    row_count INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_dataset_import_sha256 UNIQUE (sha256)
);

CREATE INDEX ix_dataset_imports_uploaded_by_user_id ON dataset_imports (uploaded_by_user_id);

CREATE TABLE imported_feature_snapshots (
    id UUID NOT NULL, 
    dataset_import_id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    source_row INTEGER NOT NULL, 
    features JSON NOT NULL, 
    weekly_sequence JSON, 
    prediction_id UUID NOT NULL, 
    forecast_prediction_id UUID, 
    cluster_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(dataset_import_id) REFERENCES dataset_imports (id) ON DELETE CASCADE, 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    FOREIGN KEY(prediction_id) REFERENCES predictions (id) ON DELETE RESTRICT, 
    FOREIGN KEY(forecast_prediction_id) REFERENCES predictions (id) ON DELETE RESTRICT, 
    FOREIGN KEY(cluster_id) REFERENCES behavioral_clusters (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_import_snapshot_source_row UNIQUE (dataset_import_id, source_row), 
    UNIQUE (prediction_id), 
    UNIQUE (forecast_prediction_id), 
    UNIQUE (cluster_id)
);

CREATE INDEX ix_imported_feature_snapshots_dataset_import_id ON imported_feature_snapshots (dataset_import_id);

CREATE INDEX ix_imported_feature_snapshots_enrollment_id ON imported_feature_snapshots (enrollment_id);

UPDATE alembic_version SET version_num='23ba7783d120' WHERE alembic_version.version_num = '9a1d7e04b62f';

-- Running upgrade 23ba7783d120 -> 4c2f981d0e73

ALTER TABLE students ADD COLUMN access_approved BOOLEAN DEFAULT true NOT NULL;

ALTER TABLE students ALTER COLUMN access_approved SET DEFAULT false;

CREATE TABLE student_access_requests (
    id UUID NOT NULL, 
    student_id UUID NOT NULL, 
    enrollment_number VARCHAR(32) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    reviewed_by_user_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    reviewed_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_student_access_request_status CHECK (status IN ('pending', 'approved', 'rejected')), 
    FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE CASCADE, 
    FOREIGN KEY(reviewed_by_user_id) REFERENCES users (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_student_access_request_student UNIQUE (student_id)
);

CREATE INDEX ix_student_access_requests_student_id ON student_access_requests (student_id);

UPDATE alembic_version SET version_num='4c2f981d0e73' WHERE alembic_version.version_num = '23ba7783d120';

-- Running upgrade 4c2f981d0e73 -> a58f9d632e10

CREATE TABLE grade_predictions (
    id UUID NOT NULL, 
    enrollment_id UUID NOT NULL, 
    requested_by_user_id UUID NOT NULL, 
    model_name VARCHAR(64) NOT NULL, 
    model_version VARCHAR(32) NOT NULL, 
    feature_version VARCHAR(64) NOT NULL, 
    target_name VARCHAR(64) NOT NULL, 
    prediction_day INTEGER DEFAULT '56' NOT NULL, 
    predicted_score FLOAT NOT NULL, 
    observed_signals JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_grade_prediction_score_range CHECK (predicted_score >= 0 AND predicted_score <= 100), 
    FOREIGN KEY(enrollment_id) REFERENCES enrollments (id) ON DELETE CASCADE, 
    FOREIGN KEY(requested_by_user_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_grade_prediction_enrollment_created ON grade_predictions (enrollment_id, created_at);

UPDATE alembic_version SET version_num='a58f9d632e10' WHERE alembic_version.version_num = '4c2f981d0e73';

-- Running upgrade a58f9d632e10 -> 1d7c8f2a6b91

ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT '0' NOT NULL;

UPDATE alembic_version SET version_num='1d7c8f2a6b91' WHERE alembic_version.version_num = 'a58f9d632e10';

COMMIT;

