-- Register 4.16.1-0.16.25 as a private release candidate by copying the
-- 4.16.1-0.16.23-2 resource contract and its version-specific password field.
-- 0.16.25 stops rTorrent aborting on torrents with many files and raises its
-- open-file cache from 64 to 2048. -2 stays the enabled default.
-- The password field gains explicit sensitive/revealable flags and is shown
-- masked on the installed page, as the current release policy requires.
-- Run only after the exact image passes the release gate and registry verification.
BEGIN;
DO $release$
DECLARE
    baseline app_versions%ROWTYPE;
    candidate app_versions%ROWTYPE;
    new_id integer;
    affected integer;
BEGIN
    PERFORM 1 FROM apps WHERE id=82 AND version='4.16.1-0.16.23-2'
        AND tag='4.16.1-0.16.23-2' AND app_slots=1 AND "Memory"=0
        AND "MemorySwap"=0 AND "MemoryReservation"=0 AND "CPUs"=0
        AND allow_downgrade=1 AND registry='repo.cylo.io' AND "Image"='flood' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'App baseline changed'; END IF;
    SELECT * INTO STRICT baseline FROM app_versions
        WHERE id=1326 AND app_id=82 AND version='4.16.1-0.16.23-2'
        AND is_default=1 AND enabled=1 AND admin_only=0
        AND tag='4.16.1-0.16.23-2'
        AND installed_image_digest='repo.cylo.net/flood@sha256:2714c4f24faabe999a1c23cb75110f006c3dcf81216ef5c8b9ffe96e38a784f5' FOR UPDATE;
    IF baseline.memory<>0 OR baseline.memory_swap<>0
        OR baseline.memory_reservation<>0 OR baseline.cpus<>0
        OR baseline.app_slots<>1 OR baseline.tcp_dynamic_ports<>1
        OR baseline.udp_dynamic_ports<>1 OR baseline.pids_limit<>0
        OR baseline.combined_dynamic_ports IS NOT NULL
    THEN RAISE EXCEPTION 'Version resource baseline changed'; END IF;
    IF EXISTS (SELECT 1 FROM app_versions WHERE app_id=82
        AND version='4.16.1-0.16.25')
    THEN RAISE EXCEPTION 'Release already registered'; END IF;

    INSERT INTO app_versions (
        app_id,version,tag,enabled,is_default,changes,min_memory,min_cpus,
        deprecated,deprecation_message,created_at,updated_at,user_id,admin_only,
        memory,memory_swap,memory_reservation,cpus,init,privileged,cap_add,cap_drop,
        tcp_port_range,udp_port_range,tcp_dynamic_ports,udp_dynamic_ports,pids_limit,
        combined_port_range,combined_dynamic_ports,app_slots,image,
        custom_field_preinstall_description,custom_field_postinstall_description,installed_image_digest
    ) SELECT app_id,'4.16.1-0.16.25','4.16.1-0.16.25',1,0,
        'Fixes rTorrent crashing and restarting when torrents with many files are started, stopped or removed. Each crash dropped every peer connection, so seeding stalled until rTorrent reconnected. rTorrent and libtorrent are updated to 0.16.25. rTorrent can now keep 2,048 files open instead of 64, so large torrents no longer keep closing and reopening files, and it allows about 800 peer connections instead of about 340. If rTorrent does crash, it no longer leaves a large core file in your downloading folder. Your torrents, settings and login stay the same when you update, and a socket limit you set yourself in .rtorrent.rc is kept. The app also stops resending its setup-complete notice after the dashboard rejects it.',
        min_memory,min_cpus,0,NULL,now(),now(),2,1,
        memory,memory_swap,memory_reservation,cpus,init,privileged,cap_add,cap_drop,
        tcp_port_range,udp_port_range,tcp_dynamic_ports,udp_dynamic_ports,pids_limit,
        combined_port_range,combined_dynamic_ports,app_slots,image,
        custom_field_preinstall_description,custom_field_postinstall_description,'repo.cylo.net/flood@sha256:31c37755be7738668134bdffc1a70fe4af55433024304f0a3e7222ce4d7a2ca8'
        FROM app_versions WHERE id=baseline.id RETURNING id INTO new_id;
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'Expected one new version'; END IF;
    SELECT * INTO STRICT candidate FROM app_versions WHERE id=new_id;
    IF (to_jsonb(candidate)-ARRAY['id','version','tag','enabled','is_default','changes','deprecated','deprecation_message','created_at','updated_at','user_id','admin_only','installed_image_digest'])
        IS DISTINCT FROM
       (to_jsonb(baseline)-ARRAY['id','version','tag','enabled','is_default','changes','deprecated','deprecation_message','created_at','updated_at','user_id','admin_only','installed_image_digest'])
    THEN RAISE EXCEPTION 'Resource parity failed'; END IF;

    INSERT INTO customfields (
        type,relid,relid2,fname,display_name,fieldtype,description,default_value,
        required,options,regex,adminonly,sort_order,flex,customtable_editable,
        template_type,"minLength","maxLength",version,app_version_id,stable_id,
        condition_json,sensitive,revealable,"unique"
    ) SELECT type,relid,relid2,fname,display_name,fieldtype,description,default_value,
        required,'{"showOnInstalled": true}',regex,adminonly,sort_order,flex,customtable_editable,
        template_type,"minLength","maxLength",'4.16.1-0.16.25',new_id,stable_id,
        condition_json,true,true,"unique"
        FROM customfields WHERE id=1118 AND type='app' AND relid=82
            AND version=baseline.version AND app_version_id=baseline.id
            AND fname='PASSWORD' AND fieldtype='complexPassword'
            AND template_type='password' AND options IS NULL;
    GET DIAGNOSTICS affected=ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'Expected one version-specific field'; END IF;
END;
$release$;
COMMIT;
