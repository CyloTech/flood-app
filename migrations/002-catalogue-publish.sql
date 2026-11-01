-- Publish the verified 4.16.1-0.16.25 candidate and retain -2 for rollback.
-- Run only after the grant canary has switched to the candidate cleanly.
BEGIN;
DO $publish$
DECLARE
    affected integer;
BEGIN
    PERFORM 1 FROM apps WHERE id=82 AND version='4.16.1-0.16.23-2'
        AND tag='4.16.1-0.16.23-2' AND "Image"='flood'
        AND registry='repo.cylo.io' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'App default changed'; END IF;
    PERFORM 1 FROM app_versions WHERE app_id=82 AND version='4.16.1-0.16.25'
        AND tag='4.16.1-0.16.25' AND is_default=0 AND enabled=1 AND admin_only=1
        AND installed_image_digest='repo.cylo.net/flood@sha256:31c37755be7738668134bdffc1a70fe4af55433024304f0a3e7222ce4d7a2ca8' AND length(changes)>0 FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Release candidate changed'; END IF;
    PERFORM 1 FROM customfields WHERE type='app' AND relid=82
        AND version='4.16.1-0.16.25' AND fname='PASSWORD'
        AND fieldtype='complexPassword' AND sensitive AND revealable
        AND options::jsonb='{"showOnInstalled": true}'::jsonb;
    IF NOT FOUND THEN RAISE EXCEPTION 'Password field changed'; END IF;
    UPDATE app_versions SET is_default=0,updated_at=now()
        WHERE id=1326 AND app_id=82 AND version='4.16.1-0.16.23-2'
            AND enabled=1 AND is_default=1;
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'Expected one previous default'; END IF;
    UPDATE app_versions SET is_default=1,admin_only=0,updated_at=now()
        WHERE app_id=82 AND version='4.16.1-0.16.25'
            AND is_default=0 AND enabled=1 AND admin_only=1
            AND installed_image_digest='repo.cylo.net/flood@sha256:31c37755be7738668134bdffc1a70fe4af55433024304f0a3e7222ce4d7a2ca8';
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'Expected one new default'; END IF;
    UPDATE apps SET version='4.16.1-0.16.25',tag='4.16.1-0.16.25',updated_at=now()
        WHERE id=82 AND version='4.16.1-0.16.23-2' AND tag='4.16.1-0.16.23-2'
            AND "Image"='flood' AND registry='repo.cylo.io';
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'Expected one app default update'; END IF;
    IF (SELECT count(*) FROM app_versions WHERE app_id=82 AND is_default=1)<>1
    THEN RAISE EXCEPTION 'Default version count mismatch'; END IF;
END;
$publish$;
COMMIT;
