-- Applied to the new commercial Supabase project only.
-- Keeps legacy feedback categories and permits general requests for help.
ALTER TABLE commercial.feedback_messages DROP CONSTRAINT feedback_messages_kind_check;
ALTER TABLE commercial.feedback_messages ADD CONSTRAINT feedback_messages_kind_check CHECK (kind = ANY (ARRAY['error'::text, 'suggestion'::text, 'request'::text]));
