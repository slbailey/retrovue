-- One-time repair for ChannelActiveRevision pointer integrity.
--
-- Goal:
--   Ensure channel_active_revisions.schedule_revision_id always points to
--   an active schedule_revisions row for the same (channel_id, broadcast_day).
--
-- What this script updates:
--   1) schedule_revisions.status (active/superseded) for invalid day states
--   2) channel_active_revisions.schedule_revision_id
--   3) channel_active_revisions.updated_at
--
-- What this script does NOT do:
--   - delete rows
--   - create new revisions
--
-- Usage:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f scripts/core/repair_channel_active_revision_pointer_integrity.sql

BEGIN;

DO $$
DECLARE
    rec RECORD;
    active_count INTEGER;
    chosen_revision_id UUID;
    old_pointer_id UUID;
    processed_count INTEGER := 0;
    repaired_count INTEGER := 0;
BEGIN
    RAISE NOTICE 'Starting ChannelActiveRevision integrity repair';

    FOR rec IN
        SELECT
            car.id AS pointer_row_id,
            car.channel_id,
            car.broadcast_day,
            car.schedule_revision_id AS current_pointer_revision_id
        FROM channel_active_revisions car
        ORDER BY car.channel_id, car.broadcast_day
    LOOP
        processed_count := processed_count + 1;
        old_pointer_id := rec.current_pointer_revision_id;

        BEGIN
            -- Lock all revisions for this channel/day to make this repair atomic
            -- at the per-(channel_id, broadcast_day) boundary.
            PERFORM 1
            FROM schedule_revisions sr
            WHERE sr.channel_id = rec.channel_id
              AND sr.broadcast_day = rec.broadcast_day
            FOR UPDATE;

            SELECT COUNT(*)
            INTO active_count
            FROM schedule_revisions sr
            WHERE sr.channel_id = rec.channel_id
              AND sr.broadcast_day = rec.broadcast_day
              AND sr.status = 'active';

            -- Case A: exactly one active revision exists.
            IF active_count = 1 THEN
                SELECT sr.id
                INTO chosen_revision_id
                FROM schedule_revisions sr
                WHERE sr.channel_id = rec.channel_id
                  AND sr.broadcast_day = rec.broadcast_day
                  AND sr.status = 'active'
                ORDER BY sr.activated_at DESC NULLS LAST, sr.created_at DESC, sr.id DESC
                LIMIT 1;

                UPDATE channel_active_revisions car
                SET schedule_revision_id = chosen_revision_id,
                    updated_at = now()
                WHERE car.id = rec.pointer_row_id;

                IF old_pointer_id IS DISTINCT FROM chosen_revision_id THEN
                    repaired_count := repaired_count + 1;
                    RAISE NOTICE
                        'REPAIRED Case A: channel=% day=% pointer % -> %',
                        rec.channel_id, rec.broadcast_day, old_pointer_id, chosen_revision_id;
                ELSE
                    RAISE NOTICE
                        'NOOP Case A: channel=% day=% pointer already canonical (%)',
                        rec.channel_id, rec.broadcast_day, chosen_revision_id;
                END IF;

            -- Case B: no active revision exists.
            ELSIF active_count = 0 THEN
                SELECT sr.id
                INTO chosen_revision_id
                FROM schedule_revisions sr
                WHERE sr.channel_id = rec.channel_id
                  AND sr.broadcast_day = rec.broadcast_day
                ORDER BY sr.created_at DESC, sr.id DESC
                LIMIT 1;

                IF chosen_revision_id IS NULL THEN
                    RAISE NOTICE
                        'SKIP Case B: channel=% day=% has pointer but no schedule_revisions rows',
                        rec.channel_id, rec.broadcast_day;
                ELSE
                    -- Two-phase state repair to satisfy unique-active constraint:
                    -- 1) clear any currently active rows
                    -- 2) set exactly one chosen row active
                    UPDATE schedule_revisions sr
                    SET status = 'superseded',
                        superseded_at = COALESCE(sr.superseded_at, now())
                    WHERE sr.channel_id = rec.channel_id
                      AND sr.broadcast_day = rec.broadcast_day
                      AND sr.status = 'active';

                    UPDATE schedule_revisions sr
                    SET status = 'active',
                        activated_at = COALESCE(sr.activated_at, now()),
                        superseded_at = NULL
                    WHERE sr.id = chosen_revision_id;

                    UPDATE channel_active_revisions car
                    SET schedule_revision_id = chosen_revision_id,
                        updated_at = now()
                    WHERE car.id = rec.pointer_row_id;

                    repaired_count := repaired_count + 1;
                    RAISE NOTICE
                        'REPAIRED Case B: channel=% day=% activated=% pointer % -> %',
                        rec.channel_id, rec.broadcast_day, chosen_revision_id, old_pointer_id, chosen_revision_id;
                END IF;

            -- Case C: multiple active revisions exist.
            ELSE
                SELECT sr.id
                INTO chosen_revision_id
                FROM schedule_revisions sr
                WHERE sr.channel_id = rec.channel_id
                  AND sr.broadcast_day = rec.broadcast_day
                  AND sr.status = 'active'
                ORDER BY sr.activated_at DESC NULLS LAST, sr.created_at DESC, sr.id DESC
                LIMIT 1;

                -- Two-phase state repair to satisfy unique-active constraint:
                -- 1) clear any currently active rows
                -- 2) set exactly one chosen row active
                UPDATE schedule_revisions sr
                SET status = 'superseded',
                    superseded_at = COALESCE(sr.superseded_at, now())
                WHERE sr.channel_id = rec.channel_id
                  AND sr.broadcast_day = rec.broadcast_day
                  AND sr.status = 'active';

                UPDATE schedule_revisions sr
                SET status = 'active',
                    activated_at = COALESCE(sr.activated_at, now()),
                    superseded_at = NULL
                WHERE sr.id = chosen_revision_id;

                UPDATE channel_active_revisions car
                SET schedule_revision_id = chosen_revision_id,
                    updated_at = now()
                WHERE car.id = rec.pointer_row_id;

                repaired_count := repaired_count + 1;
                RAISE NOTICE
                    'REPAIRED Case C: channel=% day=% active_count=% chosen=% pointer % -> %',
                    rec.channel_id, rec.broadcast_day, active_count, chosen_revision_id, old_pointer_id, chosen_revision_id;
            END IF;

        EXCEPTION WHEN OTHERS THEN
            -- Subtransaction rollback for this channel/day only.
            RAISE NOTICE
                'ERROR: channel=% day=% pointer=% err=%',
                rec.channel_id, rec.broadcast_day, old_pointer_id, SQLERRM;
        END;
    END LOOP;

    RAISE NOTICE
        'Completed ChannelActiveRevision integrity repair: processed=% repaired=%',
        processed_count, repaired_count;
END
$$ LANGUAGE plpgsql;

COMMIT;
