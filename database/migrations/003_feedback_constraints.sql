-- Additional constraints on feedback
ALTER TABLE engineer_feedback
    ADD CONSTRAINT feedback_rating_required CHECK (rating IS NOT NULL);
ALTER TABLE engineer_feedback
    ADD CONSTRAINT feedback_session_required CHECK (session_id IS NOT NULL);
